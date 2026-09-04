from __future__ import annotations

import os
import platform
from dataclasses import replace

# 循環参照を防ぐためにTYPE_CHECKINGを使用
from typing import TYPE_CHECKING

from PySide6.QtCore import QFile, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from livevoicebridge.application.comment_processing import normalize_read_blocks
from livevoicebridge.paths import EXTERNAL_LINK_ICON_FILE, SETTINGS_UI_FILE

if TYPE_CHECKING:
    from livevoicebridge.application.runtime import LiveVoiceBridgeApp
    from livevoicebridge.infrastructure.tts.base import BaseTTSEngine

import livevoicebridge.infrastructure.dictionary_repository as dictionary
from livevoicebridge.application.models import (
    ApplicationConfig,
    DictionaryConfig,
    EngineConfig,
    PopupMetricsConfig,
    ReadBlock,
    ReadBlockKind,
    SpeechConfig,
    StreamingConfig,
    TtsEngineKind,
)
from livevoicebridge.infrastructure.tts.engines.supertonic import SupertonicEngine
from livevoicebridge.infrastructure.tts.engines.supertonic_lightweight import SupertonicLightweightEngine
from livevoicebridge.infrastructure.tts.registry import config_from_backend
from livevoicebridge.presentation.delegates import HiraganaDelegate
from livevoicebridge.presentation.popup_metrics import POPUP_METRIC_MODES, POPUP_METRIC_PLACEMENTS
from livevoicebridge.presentation.read_blocks import PlaceholderFrame, ReadBlockFrame
from livevoicebridge.presentation.speaker_utils import SPEAKER_GROUP_ORDER, group_speakers_by_kana, speaker_sort_key


def _engine_form(config: EngineConfig) -> dict:
    return {
        "url": config.url,
        "path": config.model_path or config.executable_path,
        "speaker_id": config.speaker_id,
        "speed": config.speed,
        "pitch": config.pitch,
        "intonation": config.intonation,
        "volume": config.volume,
        "pause_length": config.pause_length,
        "pre_phoneme_length": config.pre_phoneme_length,
        "post_phoneme_length": config.post_phoneme_length,
        "max_length": config.max_length,
        "num_steps": config.num_steps,
        "num_threads": config.num_threads,
        "device": config.device,
        "device_policy": config.device_policy,
        "device_priority": list(config.device_priority),
        "backend": config.backend,
    }


def _read_block_forms(blocks: tuple[ReadBlock, ...]) -> list[dict[str, str]]:
    return [
        {"type": block.kind.value, **({"value": block.value} if block.kind is ReadBlockKind.TEXT else {})}
        for block in blocks
    ]


def _engine_from_form(existing: EngineConfig, form: dict) -> EngineConfig:
    path = str(form.get("path", ""))
    local = existing.kind in {TtsEngineKind.SUPERTONIC, TtsEngineKind.SUPERTONIC_LIGHTWEIGHT}
    return replace(
        existing,
        url=str(form.get("url", existing.url)),
        executable_path="" if local else path,
        model_path=path if local else "",
        speaker_id=int(form.get("speaker_id", existing.speaker_id)),
        speed=float(form.get("speed", existing.speed)),
        pitch=float(form.get("pitch", existing.pitch)),
        intonation=form.get("intonation"),
        volume=float(form.get("volume", existing.volume)),
        pause_length=form.get("pause_length"),
        pre_phoneme_length=form.get("pre_phoneme_length"),
        post_phoneme_length=form.get("post_phoneme_length"),
        max_length=int(form.get("max_length", existing.max_length)),
        num_steps=form.get("num_steps"),
        num_threads=form.get("num_threads"),
        device=str(form.get("device", existing.device)),
    )


class SettingsDialog(QObject):
    # 設定が変更されたことをメインウィンドウへ通知するシグナル
    settings_changed = Signal()

    def __init__(self, parent_app: LiveVoiceBridgeApp):
        super().__init__()
        self.main_app = parent_app
        self.dialog_window = self._load_dialog_window()

        self._bind_basic_widgets()
        self._bind_tts_page_widgets()
        self._bind_read_block_widgets()
        self._bind_dictionary_widgets()
        self._setup_dictionary_table()
        self._init_dictionary_state()
        self._setup_read_block_placeholder()
        self._setup_speaker_menu()
        self._bind_popout_widgets()
        self._setup_tts_engine_combo()
        self._init_engine_settings()
        self._init_color_state()

        self.load_settings()
        self.connect_signals()

    def _load_dialog_window(self) -> QWidget:
        # UIファイルの読み込み
        loader = QUiLoader()
        ui_file = QFile(str(SETTINGS_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {SETTINGS_UI_FILE}")
        self.dialog_window = loader.load(ui_file)
        ui_file.close()
        return self.dialog_window

    def _bind_basic_widgets(self) -> None:
        # ウィジェットのバインド
        self.api_key_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "apiKeyLineEdit")
        self.api_key_btn: QToolButton = self.dialog_window.findChild(QToolButton, "apiKeyButton")
        self.speaker_button: QPushButton = self.dialog_window.findChild(QPushButton, "speakerButton")
        self.skip_history_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_super_chat_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.check_updates_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "checkUpdatesCheckBox")
        self.tts_test_button: QPushButton = self.dialog_window.findChild(QPushButton, "ttsTestButton")
        self.button_box: QDialogButtonBox = self.dialog_window.findChild(QDialogButtonBox, "buttonBox")

        # APIキーボタンの設定
        if self.api_key_btn:
            if EXTERNAL_LINK_ICON_FILE.exists():
                from livevoicebridge.presentation.helpers import load_svg_icon

                self.api_key_btn.setIcon(load_svg_icon(EXTERNAL_LINK_ICON_FILE, self.api_key_btn))

            self.api_key_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(
                    QUrl("https://console.cloud.google.com/apis/library/youtube.googleapis.com")
                )
            )

    def _bind_tts_page_widgets(self) -> None:
        # StackedWidget とページのバインド
        self.tts_engine_stacked: QStackedWidget = self.dialog_window.findChild(QStackedWidget, "ttsEngineStackedWidget")
        self.voicevox_page: QWidget = self.dialog_window.findChild(QWidget, "voicevoxPage")
        self.coeiroink_page: QWidget = self.dialog_window.findChild(QWidget, "coeiroinkPage")
        self.bouyomichan_page: QWidget = self.dialog_window.findChild(QWidget, "bouyomichanPage")
        self.supertonic_lightweight_page: QWidget = self.dialog_window.findChild(QWidget, "supertonicLightweightPage")
        self.supertonic_page: QWidget = self.dialog_window.findChild(QWidget, "supertonicPage")

        # VOICEVOX ウィジェット
        self.vv_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxUrlLineEdit")
        self.vv_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxPathLineEdit")
        self.vv_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "voicevoxPathBrowseButton")
        self.vv_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxSpeedDoubleSpinBox")
        self.vv_pitch_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxPitchDoubleSpinBox")
        self.vv_intonation_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "voicevoxIntonationDoubleSpinBox"
        )
        self.vv_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "voicevoxVolumeDoubleSpinBox"
        )
        self.vv_pause_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "voicevoxPauseLengthDoubleSpinBox"
        )
        self.vv_pre_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "voicevoxPrePhonemeLengthDoubleSpinBox"
        )
        self.vv_post_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "voicevoxPostPhonemeLengthDoubleSpinBox"
        )
        self.vv_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "voicevoxMaxLengthSpinBox")

        # COEIROINK ウィジェット
        self.coe_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "coeiroinkUrlLineEdit")
        self.coe_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "coeiroinkPathLineEdit")
        self.coe_path_browse_button: QPushButton = self.dialog_window.findChild(
            QPushButton, "coeiroinkPathBrowseButton"
        )
        self.coe_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkSpeedDoubleSpinBox"
        )
        self.coe_pitch_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkPitchDoubleSpinBox"
        )
        self.coe_intonation_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkIntonationDoubleSpinBox"
        )
        self.coe_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkVolumeDoubleSpinBox"
        )
        self.coe_pause_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkPauseLengthDoubleSpinBox"
        )
        self.coe_pre_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkPrePhonemeLengthDoubleSpinBox"
        )
        self.coe_post_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "coeiroinkPostPhonemeLengthDoubleSpinBox"
        )
        self.coe_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "coeiroinkMaxLengthSpinBox")

        # 棒読みちゃん ウィジェット
        self.bc_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "bouyomichanUrlLineEdit")
        self.bc_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "bouyomichanPathLineEdit")
        self.bc_path_browse_button: QPushButton = self.dialog_window.findChild(
            QPushButton, "bouyomichanPathBrowseButton"
        )
        self.bc_speed_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanSpeedSpinBox")
        self.bc_pitch_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanPitchSpinBox")
        self.bc_volume_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanVolumeSpinBox")
        self.bc_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanMaxLengthSpinBox")

        # Supertonic 3 軽量版ウィジェット
        self.lightweight_st_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "supertonicLightweightSpeedDoubleSpinBox"
        )
        self.lightweight_st_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "supertonicLightweightVolumeDoubleSpinBox"
        )
        self.lightweight_st_max_length_spin: QSpinBox = self.dialog_window.findChild(
            QSpinBox, "supertonicLightweightMaxLengthSpinBox"
        )
        self.lightweight_st_download_button: QPushButton = self.dialog_window.findChild(
            QPushButton, "supertonicLightweightDownloadButton"
        )

        # Supertonic 3 ウィジェット
        self.st_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "supertonicSpeedDoubleSpinBox"
        )
        self.st_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(
            QDoubleSpinBox, "supertonicVolumeDoubleSpinBox"
        )
        self.st_steps_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "supertonicStepsSpinBox")
        self.st_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "supertonicMaxLengthSpinBox")
        self.st_device_combo: QComboBox = self.dialog_window.findChild(QComboBox, "supertonicDeviceComboBox")
        self.st_download_button: QPushButton = self.dialog_window.findChild(QPushButton, "supertonicDownloadButton")
        self._setup_supertonic_devices()

    def _setup_supertonic_devices(self) -> None:
        from livevoicebridge.infrastructure.tts.engines.supertonic import SupertonicEngine

        self.st_device_combo.clear()
        for device_id, display_name in SupertonicEngine.available_devices():
            self.st_device_combo.addItem(display_name, device_id)

    def _bind_read_block_widgets(self) -> None:
        self.read_block_scroll_area: QScrollArea = self.dialog_window.findChild(QScrollArea, "readBlockScrollArea")
        self.read_block_container: QWidget = self.dialog_window.findChild(QWidget, "readBlockScrollContent")
        self.read_block_layout: QHBoxLayout = self.dialog_window.findChild(QHBoxLayout, "readBlockHBoxLayout")
        self.read_block_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.add_author_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addAuthorBlockButton")
        self.add_message_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addMessageBlockButton")
        self.add_text_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addTextBlockButton")
        self._read_block_next_id = 1

    def _bind_dictionary_widgets(self) -> None:
        # 読み替え辞書UIのバインド
        self.word_table: QTableWidget = self.dialog_window.findChild(QTableWidget, "wordTableWidget")
        self.add_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "addWordButton")
        self.delete_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteWordButton")
        self.import_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "importWordButton")
        self.group_combo: QComboBox = self.dialog_window.findChild(QComboBox, "dictionaryGroupComboBox")
        self.add_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "addGroupButton")
        self.rename_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "renameGroupButton")
        self.delete_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteGroupButton")

    def _setup_dictionary_table(self) -> None:
        # テーブル設定
        self.word_table.setColumnCount(4)
        self.word_table.setHorizontalHeaderLabels(["読み", "単語", "品詞", "コメント"])
        self.word_table.horizontalHeader().setStretchLastSection(True)
        # 読み列（0列目）をひらがな限定に制限
        self.word_table.setItemDelegateForColumn(0, HiraganaDelegate(self.word_table))

    def _init_dictionary_state(self) -> None:
        self.word_dict = {}
        self.current_active_group_name = ""
        self._block_group_change_signal = False

    def _setup_read_block_placeholder(self) -> None:
        self.placeholder = PlaceholderFrame(self)
        self.placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.placeholder.setStyleSheet(
            "QFrame { border: 2px dashed #3498db; background-color: rgba(52, 152, 219, 20); }"
        )
        self.placeholder.hide()

    def _setup_speaker_menu(self) -> None:
        # プルダウンメニューの初期設定
        self.speakers_data = {}
        self.current_speaker_id = 1
        self.speaker_menu = QMenu(self.dialog_window)
        self.speaker_button.setMenu(self.speaker_menu)
        self.rebuild_speaker_menu()

    def _bind_popout_widgets(self) -> None:
        # UIからPiP設定ウィジェットを取得
        self.opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "opacitySlider")
        self.opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "opacitySpinBox")
        self.header_opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "headerOpacitySlider")
        self.header_opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "headerOpacitySpinBox")
        self.border_opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "borderOpacitySlider")
        self.border_opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "borderOpacitySpinBox")
        self.bg_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "bgColorButton")
        self.border_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "borderColorButton")
        self.popup_metrics_placement_combo: QComboBox = self.dialog_window.findChild(
            QComboBox, "popupMetricsPlacementComboBox"
        )
        self.popup_metrics_table: QTableWidget = self.dialog_window.findChild(QTableWidget, "popupMetricsTableWidget")
        self.popup_metrics_placement_combo.clear()
        for placement, label in POPUP_METRIC_PLACEMENTS.items():
            self.popup_metrics_placement_combo.addItem(label, placement)
        self.popup_metrics_table.setColumnCount(2)
        self.popup_metrics_table.setHorizontalHeaderLabels(["項目", "表示"])
        self.popup_metrics_table.verticalHeader().setVisible(False)
        self.popup_metrics_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.popup_metrics_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.popup_metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.popup_metrics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._popup_metric_display_modes: dict[str, str] = {}
        self._popup_metric_combos: dict[str, QComboBox] = {}
        if hasattr(self.main_app, "metric_catalog_changed"):
            self.main_app.metric_catalog_changed.connect(self.refresh_popup_metric_catalog)

    def _setup_tts_engine_combo(self) -> None:
        # 音声エンジン選択のバインド
        self.tts_engine_combo: QComboBox = self.dialog_window.findChild(QComboBox, "ttsEngineComboBox")
        if self.tts_engine_combo.findText("BOUYOMICHAN") == -1:
            self.tts_engine_combo.addItem("BOUYOMICHAN")
        if self.tts_engine_combo.findText("SUPERTONIC 3") == -1:
            self.tts_engine_combo.addItem("SUPERTONIC 3")
        if self.tts_engine_combo.findText("SUPERTONIC 3 軽量版") == -1:
            self.tts_engine_combo.addItem("SUPERTONIC 3 軽量版")

    def _init_engine_settings(self) -> None:
        # 各エンジン用の一時設定バッファ（話速、音高などのパラメータも保持）
        self.engine_settings = {
            "voicevox": {
                "url": "http://127.0.0.1:50021",
                "path": "",
                "speaker_id": 1,
                "speed": 1.0,
                "pitch": 0.0,
                "intonation": 1.0,
                "volume": 1.0,
                "pause_length": 1.0,
                "pre_phoneme_length": 0.1,
                "post_phoneme_length": 0.1,
                "max_length": 50,
            },
            "coeiroink": {
                "url": "http://127.0.0.1:50032",
                "path": "",
                "speaker_id": 1,
                "speed": 1.0,
                "pitch": 0.0,
                "intonation": 1.0,
                "volume": 1.0,
                "pause_length": 1.0,
                "pre_phoneme_length": 0.1,
                "post_phoneme_length": 0.1,
                "max_length": 50,
            },
            "bouyomichan": {
                "url": "127.0.0.1:50001",
                "path": "",
                "speaker_id": 0,
                "speed": -1,
                "pitch": -1,
                "volume": -1,
                "max_length": 50,
            },
            "supertonic_lightweight": {
                "url": "local://supertonic-lightweight",
                "path": "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
                "speaker_id": 0,
                "speed": 1.0,
                "volume": 1.0,
                "max_length": 50,
            },
            "supertonic": {
                "url": "local://supertonic",
                "path": "models/supertonic-3",
                "speaker_id": 0,
                "speed": 1.0,
                "volume": 1.0,
                "max_length": 50,
                "num_steps": 8,
                "device": "cpu",
            },
        }
        self.current_active_engine = "voicevox"

    def _init_color_state(self) -> None:
        # カラー値の保持
        self.bg_color_hex = ""
        self.border_color_hex = ""

    def _get_engine_key(self, display_name: str) -> str:
        name_lower = display_name.lower()
        if name_lower == "supertonic 3":
            return "supertonic"
        if name_lower == "supertonic 3 軽量版":
            return "supertonic_lightweight"
        return name_lower

    def _get_engine_display_name(self, key: str) -> str:
        if key == "supertonic_lightweight":
            return "SUPERTONIC 3 軽量版"
        if key == "supertonic":
            return "SUPERTONIC 3"
        return key.upper()

    def _lightweight_model_available(self) -> bool:
        path = self.engine_settings["supertonic_lightweight"].get("path", "")
        return SupertonicLightweightEngine.has_model_files(path)

    def _supertonic_model_available(self) -> bool:
        path = self.engine_settings["supertonic"].get("path", "")
        return SupertonicEngine.has_model_files(path)

    def _refresh_lightweight_model_selection(self) -> None:
        model_available = self._lightweight_model_available()
        is_active = self.current_active_engine == "supertonic_lightweight"

        for widget in (
            self.lightweight_st_speed_spin,
            self.lightweight_st_volume_spin,
            self.lightweight_st_max_length_spin,
        ):
            widget.setEnabled(model_available)

        if self.lightweight_st_download_button:
            self.lightweight_st_download_button.setEnabled(not model_available)
        if is_active:
            self.speaker_button.setEnabled(model_available)
            self.tts_test_button.setEnabled(model_available)
        else:
            self.speaker_button.setEnabled(True)
            self.tts_test_button.setEnabled(True)

        lightweight_index = self.tts_engine_combo.findText(self._get_engine_display_name("supertonic_lightweight"))
        if lightweight_index < 0:
            return

        if model_available:
            self.tts_engine_combo.setItemData(
                lightweight_index,
                "",
                Qt.ItemDataRole.ToolTipRole,
            )
            return

        self.tts_engine_combo.setItemData(
            lightweight_index,
            "モデル未ダウンロードのため、設定変更と接続テストはできません。ダウンロードボタンからモデルを取得してください。",
            Qt.ItemDataRole.ToolTipRole,
        )

    def _refresh_supertonic_model_selection(self) -> None:
        model_available = self._supertonic_model_available()
        is_active = self.current_active_engine == "supertonic"

        for widget in (
            self.st_speed_spin,
            self.st_volume_spin,
            self.st_steps_spin,
            self.st_max_length_spin,
            self.st_device_combo,
        ):
            widget.setEnabled(model_available)

        if self.st_download_button:
            self.st_download_button.setEnabled(not model_available)
        if is_active:
            self.speaker_button.setEnabled(model_available)
            self.tts_test_button.setEnabled(model_available)
        elif self.current_active_engine != "supertonic_lightweight":
            self.speaker_button.setEnabled(True)
            self.tts_test_button.setEnabled(True)

    def _update_ui_for_active_engine(self) -> None:
        # アクティブなエンジンのパラメータを共通ウィジェットへロード
        active_config = self.engine_settings[self.current_active_engine]

        self.current_speaker_id = active_config.get("speaker_id", 0)
        self.set_speaker_button_id(self.current_speaker_id)

        # 新しいエンジンのURL/パスを基に、話者リストを自動で更新・メニュー構築する
        self.update_speakers_from_engine()

        # StackedWidget ページの切り替え
        if self.current_active_engine == "voicevox":
            self.tts_engine_stacked.setCurrentWidget(self.voicevox_page)
        elif self.current_active_engine == "coeiroink":
            self.tts_engine_stacked.setCurrentWidget(self.coeiroink_page)
        elif self.current_active_engine == "bouyomichan":
            self.tts_engine_stacked.setCurrentWidget(self.bouyomichan_page)
        elif self.current_active_engine == "supertonic_lightweight":
            self.tts_engine_stacked.setCurrentWidget(self.supertonic_lightweight_page)
        elif self.current_active_engine == "supertonic":
            self.tts_engine_stacked.setCurrentWidget(self.supertonic_page)
        self._refresh_lightweight_model_selection()
        self._refresh_supertonic_model_selection()

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        config = self.main_app.config
        self.api_key_line.setText(config.streaming.youtube_api_key or env_key)
        self.current_active_engine = config.speech.active_engine.value
        for engine in config.speech.engines:
            self.engine_settings[engine.kind.value].update(_engine_form(engine))

        vv = self.engine_settings["voicevox"]
        coe = self.engine_settings["coeiroink"]
        bc = self.engine_settings["bouyomichan"]
        st = self.engine_settings["supertonic_lightweight"]
        supertonic = self.engine_settings["supertonic"]

        # VOICEVOX ウィジェットへの適用
        self.vv_url_line.setText(vv["url"])
        self.vv_path_line.setText(vv["path"])
        self.vv_speed_spin.setValue(vv["speed"])
        self.vv_pitch_spin.setValue(vv["pitch"])
        self.vv_intonation_spin.setValue(vv["intonation"])
        self.vv_volume_spin.setValue(vv["volume"])
        self.vv_pause_spin.setValue(vv["pause_length"])
        self.vv_pre_phoneme_spin.setValue(vv["pre_phoneme_length"])
        self.vv_post_phoneme_spin.setValue(vv["post_phoneme_length"])
        self.vv_max_length_spin.setValue(vv["max_length"])

        # COEIROINK ウィジェットへの適用
        self.coe_url_line.setText(coe["url"])
        self.coe_path_line.setText(coe["path"])
        self.coe_speed_spin.setValue(coe["speed"])
        self.coe_pitch_spin.setValue(coe["pitch"])
        self.coe_intonation_spin.setValue(coe["intonation"])
        self.coe_volume_spin.setValue(coe["volume"])
        self.coe_pause_spin.setValue(coe["pause_length"])
        self.coe_pre_phoneme_spin.setValue(coe["pre_phoneme_length"])
        self.coe_post_phoneme_spin.setValue(coe["post_phoneme_length"])
        self.coe_max_length_spin.setValue(coe["max_length"])

        # 棒読みちゃん ウィジェットへの適用
        self.bc_url_line.setText(bc["url"])
        self.bc_path_line.setText(bc["path"])
        self.bc_speed_spin.setValue(bc["speed"])
        self.bc_pitch_spin.setValue(bc["pitch"])
        self.bc_volume_spin.setValue(bc["volume"])
        self.bc_max_length_spin.setValue(bc["max_length"])

        # Supertonic 3 軽量版ウィジェットへの適用
        self.lightweight_st_speed_spin.setValue(st["speed"])
        self.lightweight_st_volume_spin.setValue(st["volume"])
        self.lightweight_st_max_length_spin.setValue(st["max_length"])

        # Supertonic 3 ウィジェットへの適用
        self.st_speed_spin.setValue(supertonic["speed"])
        self.st_volume_spin.setValue(supertonic["volume"])
        self.st_steps_spin.setValue(supertonic["num_steps"])
        self.st_max_length_spin.setValue(supertonic["max_length"])
        device_index = self.st_device_combo.findData(supertonic["device"])
        self.st_device_combo.setCurrentIndex(device_index if device_index >= 0 else 0)
        self._refresh_lightweight_model_selection()
        self._refresh_supertonic_model_selection()

        # 画面のコントロールへ現在アクティブなエンジンの設定値を適用
        self._update_ui_for_active_engine()

        # 音声エンジンの選択状態を復元
        display_name = self._get_engine_display_name(self.current_active_engine)
        idx = self.tts_engine_combo.findText(display_name)
        if idx >= 0:
            self.tts_engine_combo.setCurrentIndex(idx)

        self.skip_history_check.setChecked(config.streaming.skip_history)
        self.read_super_chat_check.setChecked(config.streaming.read_paid_events)
        self.check_updates_check.setChecked(config.application.check_updates)
        self.set_read_blocks(_read_block_forms(config.speech.read_blocks))

        # 読み替え辞書のロード
        self.word_dict = self.main_app.load_all_word_dict_data()

        # グループリストをコンボボックスへ設定
        self._block_group_change_signal = True
        self.group_combo.clear()
        self.group_combo.addItems(list(self.word_dict.keys()))

        active_group = config.dictionary.active_group
        if active_group not in self.word_dict:
            active_group = list(self.word_dict.keys())[0] if self.word_dict else ""

        self.current_active_group_name = active_group
        if active_group:
            self.group_combo.setCurrentText(active_group)
        self._block_group_change_signal = False

        self.display_words_for_group()

        opacity = int(config.presentation.comment_opacity * 100)
        self.opacity_slider.setValue(opacity)
        self.opacity_spin.setValue(opacity)

        header_opacity = int(config.presentation.header_opacity * 100)
        self.header_opacity_slider.setValue(header_opacity)
        self.header_opacity_spin.setValue(header_opacity)

        border_opacity = int(config.presentation.border_opacity * 100)
        self.border_opacity_slider.setValue(border_opacity)
        self.border_opacity_spin.setValue(border_opacity)

        self.bg_color_hex = config.presentation.background_color
        self.border_color_hex = config.presentation.border_color
        self.update_color_button_style(self.bg_color_button, self.bg_color_hex)
        self.update_color_button_style(self.border_color_button, self.border_color_hex)

        popup_metrics = config.presentation.popup_metrics
        placement_index = self.popup_metrics_placement_combo.findData(popup_metrics.placement)
        self.popup_metrics_placement_combo.setCurrentIndex(placement_index if placement_index >= 0 else 0)
        self._popup_metric_display_modes = dict(popup_metrics.display_modes)
        self.refresh_popup_metric_catalog(getattr(self.main_app, "metric_catalog", []))

    def save_settings(self) -> None:
        # 各個別の設定値を画面から取得して engine_settings バッファへ格納
        # VOICEVOX
        self.engine_settings["voicevox"].update(
            {
                "url": self.vv_url_line.text().strip(),
                "path": self.vv_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id()
                if self.current_active_engine == "voicevox"
                else self.engine_settings["voicevox"]["speaker_id"],
                "speed": self.vv_speed_spin.value(),
                "pitch": self.vv_pitch_spin.value(),
                "intonation": self.vv_intonation_spin.value(),
                "volume": self.vv_volume_spin.value(),
                "pause_length": self.vv_pause_spin.value(),
                "pre_phoneme_length": self.vv_pre_phoneme_spin.value(),
                "post_phoneme_length": self.vv_post_phoneme_spin.value(),
                "max_length": self.vv_max_length_spin.value(),
            }
        )
        # COEIROINK
        self.engine_settings["coeiroink"].update(
            {
                "url": self.coe_url_line.text().strip(),
                "path": self.coe_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id()
                if self.current_active_engine == "coeiroink"
                else self.engine_settings["coeiroink"]["speaker_id"],
                "speed": self.coe_speed_spin.value(),
                "pitch": self.coe_pitch_spin.value(),
                "intonation": self.coe_intonation_spin.value(),
                "volume": self.coe_volume_spin.value(),
                "pause_length": self.coe_pause_spin.value(),
                "pre_phoneme_length": self.coe_pre_phoneme_spin.value(),
                "post_phoneme_length": self.coe_post_phoneme_spin.value(),
                "max_length": self.coe_max_length_spin.value(),
            }
        )
        # 棒読みちゃん
        self.engine_settings["bouyomichan"].update(
            {
                "url": self.bc_url_line.text().strip(),
                "path": self.bc_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id()
                if self.current_active_engine == "bouyomichan"
                else self.engine_settings["bouyomichan"]["speaker_id"],
                "speed": self.bc_speed_spin.value(),
                "pitch": self.bc_pitch_spin.value(),
                "volume": self.bc_volume_spin.value(),
                "max_length": self.bc_max_length_spin.value(),
            }
        )
        # Supertonic 3 軽量版
        self.engine_settings["supertonic_lightweight"].update(
            {
                "speaker_id": self.get_current_speaker_id()
                if self.current_active_engine == "supertonic_lightweight"
                else self.engine_settings["supertonic_lightweight"]["speaker_id"],
                "speed": self.lightweight_st_speed_spin.value(),
                "volume": self.lightweight_st_volume_spin.value(),
                "max_length": self.lightweight_st_max_length_spin.value(),
            }
        )
        # Supertonic 3
        self.engine_settings["supertonic"].update(
            {
                "speaker_id": self.get_current_speaker_id()
                if self.current_active_engine == "supertonic"
                else self.engine_settings["supertonic"]["speaker_id"],
                "speed": self.st_speed_spin.value(),
                "volume": self.st_volume_spin.value(),
                "max_length": self.st_max_length_spin.value(),
                "num_steps": self.st_steps_spin.value(),
                "device": self.st_device_combo.currentData(),
            }
        )

        # 読み替え辞書のセーブ
        if self.current_active_group_name:
            self.update_current_group_data_for(self.current_active_group_name)

        current = self.main_app.config
        engines = tuple(
            _engine_from_form(engine, self.engine_settings[engine.kind.value]) for engine in current.speech.engines
        )
        blocks = tuple(
            ReadBlock(ReadBlockKind(item["type"]), str(item.get("value", ""))) for item in self.get_read_blocks()
        )
        popup = self.get_popup_metrics_settings()
        active_group = self.group_combo.currentText() or current.dictionary.active_group
        updated = replace(
            current,
            streaming=StreamingConfig(
                youtube_api_key=self.api_key_line.text().strip(),
                youtube_source=current.streaming.youtube_source,
                skip_history=self.skip_history_check.isChecked(),
                read_paid_events=self.read_super_chat_check.isChecked(),
            ),
            speech=SpeechConfig(
                active_engine=TtsEngineKind(self._get_engine_key(self.tts_engine_combo.currentText())),
                engines=engines,
                read_blocks=blocks or (ReadBlock(ReadBlockKind.MESSAGE),),
            ),
            presentation=replace(
                current.presentation,
                comment_opacity=self.opacity_slider.value() / 100.0,
                header_opacity=self.header_opacity_slider.value() / 100.0,
                border_opacity=self.border_opacity_slider.value() / 100.0,
                background_color=self.bg_color_hex,
                border_color=self.border_color_hex,
                popup_metrics=PopupMetricsConfig(
                    placement=str(popup["placement"]),
                    vertical_ratio=float(popup["vertical_ratio"]),
                    horizontal_ratio=float(popup["horizontal_ratio"]),
                    display_modes=tuple(sorted(dict(popup["display_modes"]).items())),
                ),
            ),
            dictionary=DictionaryConfig(active_group=active_group),
            application=ApplicationConfig(
                check_updates=self.check_updates_check.isChecked(),
                use_ime=current.application.use_ime,
            ),
        )
        self.main_app.replace_config(updated)

        try:
            dictionary.save_word_dict_data(self.word_dict)
        except Exception as exc:
            QMessageBox.critical(self.dialog_window, "エラー", f"辞書ファイルの保存に失敗しました: {exc}")

    def get_live_settings(self) -> dict:
        """現在の画面上の設定値を辞書として取得する (リアルタイム反映用)"""
        engine_key = self.current_active_engine

        # 各音声エンジン固有の設定値を構築
        engine_config = {}
        if engine_key == "voicevox":
            engine_config = {
                "url": self.vv_url_line.text().strip(),
                "path": self.vv_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id(),
                "speed": self.vv_speed_spin.value(),
                "pitch": self.vv_pitch_spin.value(),
                "intonation": self.vv_intonation_spin.value(),
                "volume": self.vv_volume_spin.value(),
                "pause_length": self.vv_pause_spin.value(),
                "pre_phoneme_length": self.vv_pre_phoneme_spin.value(),
                "post_phoneme_length": self.vv_post_phoneme_spin.value(),
                "max_length": self.vv_max_length_spin.value(),
            }
        elif engine_key == "coeiroink":
            engine_config = {
                "url": self.coe_url_line.text().strip(),
                "path": self.coe_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id(),
                "speed": self.coe_speed_spin.value(),
                "pitch": self.coe_pitch_spin.value(),
                "intonation": self.coe_intonation_spin.value(),
                "volume": self.coe_volume_spin.value(),
                "pause_length": self.coe_pause_spin.value(),
                "pre_phoneme_length": self.coe_pre_phoneme_spin.value(),
                "post_phoneme_length": self.coe_post_phoneme_spin.value(),
                "max_length": self.coe_max_length_spin.value(),
            }
        elif engine_key == "bouyomichan":
            engine_config = {
                "url": self.bc_url_line.text().strip(),
                "path": self.bc_path_line.text().strip(),
                "speaker_id": self.get_current_speaker_id(),
                "speed": self.bc_speed_spin.value(),
                "pitch": self.bc_pitch_spin.value(),
                "volume": self.bc_volume_spin.value(),
                "max_length": self.bc_max_length_spin.value(),
            }
        elif engine_key == "supertonic_lightweight":
            engine_config = {
                "url": "local://supertonic-lightweight",
                "path": self.engine_settings["supertonic_lightweight"]["path"],
                "speaker_id": self.get_current_speaker_id(),
                "speed": self.lightweight_st_speed_spin.value(),
                "volume": self.lightweight_st_volume_spin.value(),
                "max_length": self.lightweight_st_max_length_spin.value(),
            }
        elif engine_key == "supertonic":
            engine_config = {
                "url": "local://supertonic",
                "path": self.engine_settings["supertonic"]["path"],
                "speaker_id": self.get_current_speaker_id(),
                "speed": self.st_speed_spin.value(),
                "volume": self.st_volume_spin.value(),
                "max_length": self.st_max_length_spin.value(),
                "num_steps": self.st_steps_spin.value(),
                "device": self.st_device_combo.currentData(),
            }

        return {
            "engine_type": engine_key,
            "engine_config": engine_config,
            "skip_history": self.skip_history_check.isChecked(),
            "read_super_chat": self.read_super_chat_check.isChecked(),
            "read_blocks": self.get_read_blocks(),
            "word_list": self.get_all_merged_word_list(),
            "comment_opacity": self.opacity_slider.value() / 100.0,
            "comment_header_opacity": self.header_opacity_slider.value() / 100.0,
            "comment_border_opacity": self.border_opacity_slider.value() / 100.0,
            "comment_bg_color": self.bg_color_hex,
            "comment_border_color": self.border_color_hex,
            "popup_metrics": self.get_popup_metrics_settings(),
        }

    def connect_signals(self) -> None:
        # パス参照ボタンの接続
        self.vv_path_browse_button.clicked.connect(self.browse_voicevox_path)
        self.coe_path_browse_button.clicked.connect(self.browse_coeiroink_path)
        self.bc_path_browse_button.clicked.connect(self.browse_bouyomichan_path)
        self.tts_test_button.clicked.connect(self.test_tts_connection)

        # OK / キャンセルボタン
        self.button_box.accepted.connect(self.accept_settings)
        self.button_box.rejected.connect(self.dialog_window.reject)

        # リアルタイム反映用の変更検知
        self.skip_history_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.read_super_chat_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.check_updates_check.stateChanged.connect(lambda _: self.settings_changed.emit())

        # 新しい個別スピンボックスのリアルタイム反映用バインド
        # VOICEVOX
        self.vv_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_pitch_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_intonation_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_pause_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_pre_phoneme_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_post_phoneme_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.vv_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

        # COEIROINK
        self.coe_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_pitch_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_intonation_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_pause_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_pre_phoneme_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_post_phoneme_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.coe_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

        # 棒読みちゃん
        self.bc_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.bc_pitch_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.bc_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.bc_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

        # Supertonic 3 軽量版
        self.lightweight_st_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.lightweight_st_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.lightweight_st_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

        # Supertonic 3
        self.st_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_steps_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_device_combo.currentIndexChanged.connect(lambda _: self.settings_changed.emit())

        # ダウンロードボタン
        self.lightweight_st_download_button.clicked.connect(self.download_supertonic_lightweight_model)
        self.st_download_button.clicked.connect(self.download_supertonic_model)

        # 読み替え辞書シグナル
        self.add_word_button.clicked.connect(self.add_word_row)
        self.delete_word_button.clicked.connect(self.delete_word_row)
        self.import_word_button.clicked.connect(self.import_words)
        self.add_group_button.clicked.connect(self.add_dictionary_group)
        self.rename_group_button.clicked.connect(self.rename_dictionary_group)
        self.delete_group_button.clicked.connect(self.delete_dictionary_group)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.word_table.itemChanged.connect(lambda _: self.settings_changed.emit())
        self.opacity_slider.valueChanged.connect(self.opacity_spin.setValue)
        self.opacity_spin.valueChanged.connect(self.opacity_slider.setValue)
        self.opacity_slider.valueChanged.connect(self.on_opacity_slider_changed)

        self.header_opacity_slider.valueChanged.connect(self.header_opacity_spin.setValue)
        self.header_opacity_spin.valueChanged.connect(self.header_opacity_slider.setValue)
        self.header_opacity_slider.valueChanged.connect(lambda _: self.settings_changed.emit())

        self.border_opacity_slider.valueChanged.connect(self.border_opacity_spin.setValue)
        self.border_opacity_spin.valueChanged.connect(self.border_opacity_slider.setValue)
        self.border_opacity_slider.valueChanged.connect(lambda _: self.settings_changed.emit())

        self.bg_color_button.clicked.connect(self.select_bg_color)
        self.border_color_button.clicked.connect(self.select_border_color)
        self.popup_metrics_placement_combo.currentIndexChanged.connect(lambda _: self.settings_changed.emit())
        self.tts_engine_combo.currentTextChanged.connect(self.on_tts_engine_changed)
        self.add_author_block_button.clicked.connect(lambda: self.add_read_block("author"))
        self.add_message_block_button.clicked.connect(lambda: self.add_read_block("message"))
        self.add_text_block_button.clicked.connect(lambda: self.add_read_block("text", ""))

    def refresh_popup_metric_catalog(self, catalog: list) -> None:
        """検出済みメトリクスを設定表へ反映し、編集中の選択を保持する。"""
        current_modes = self.get_popup_display_modes()
        self._popup_metric_display_modes.update(current_modes)
        self.popup_metrics_table.setRowCount(len(catalog))
        self._popup_metric_combos.clear()

        for row, entry in enumerate(catalog):
            metric_id = str(entry.get("id", ""))
            title = str(entry.get("title", metric_id))
            item = QTableWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, metric_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.popup_metrics_table.setItem(row, 0, item)

            combo = QComboBox(self.popup_metrics_table)
            for mode, label in POPUP_METRIC_MODES.items():
                combo.addItem(label, mode)
            selected_mode = self._popup_metric_display_modes.get(metric_id, "hidden")
            mode_index = combo.findData(selected_mode)
            combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _, key=metric_id, widget=combo: self._on_popup_metric_mode_changed(key, widget)
            )
            self._popup_metric_combos[metric_id] = combo
            self.popup_metrics_table.setCellWidget(row, 1, combo)

        self._fit_popup_metrics_table_to_contents()

    def _fit_popup_metrics_table_to_contents(self) -> None:
        """内側をスクロールさせず、全メトリクス行が収まる高さにする。"""
        self.popup_metrics_table.resizeRowsToContents()
        rows_height = sum(self.popup_metrics_table.rowHeight(row) for row in range(self.popup_metrics_table.rowCount()))
        header_height = self.popup_metrics_table.horizontalHeader().height()
        frame_height = self.popup_metrics_table.frameWidth() * 2
        self.popup_metrics_table.setFixedHeight(header_height + rows_height + frame_height)

    def _on_popup_metric_mode_changed(self, metric_id: str, combo: QComboBox) -> None:
        self._popup_metric_display_modes[metric_id] = combo.currentData()
        self.settings_changed.emit()

    def get_popup_display_modes(self) -> dict[str, str]:
        modes = dict(self._popup_metric_display_modes)
        for metric_id, combo in self._popup_metric_combos.items():
            mode = combo.currentData()
            modes[metric_id] = mode if mode in POPUP_METRIC_MODES else "hidden"
        return modes

    def get_popup_metrics_settings(self) -> dict:
        current = self.main_app.config.presentation.popup_metrics
        placement = self.popup_metrics_placement_combo.currentData()
        if placement not in POPUP_METRIC_PLACEMENTS:
            placement = "top"
        return {
            "placement": placement,
            "vertical_ratio": current.vertical_ratio,
            "horizontal_ratio": current.horizontal_ratio,
            "display_modes": self.get_popup_display_modes(),
        }

    def set_read_blocks(self, blocks: object) -> None:
        while self.read_block_layout.count():
            item = self.read_block_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for block in normalize_read_blocks(blocks):
            self.add_read_block(block["type"], block.get("value", ""), emit_changed=False)
        self.update_read_block_scroll_area_height()

    def add_read_block(self, block_type: str, value: str = "", emit_changed: bool = True) -> None:
        labels = {
            "author": "投稿者名",
            "message": "本文",
            "text": "テキスト",
        }
        block_id = self._read_block_next_id
        self._read_block_next_id += 1

        block_widget = ReadBlockFrame(block_id, self)
        block_widget.move_requested.connect(self.drop_on_placeholder)
        block_widget.setProperty("blockType", block_type)
        block_widget.setFrameShape(QFrame.Shape.StyledPanel)
        block_widget.setStyleSheet(
            "QFrame { background-color: palette(base); border: 1px solid transparent; }"
            "QFrame:hover { border: 1px solid #3498db; background-color: rgba(52, 152, 219, 20); }"
        )
        layout = QHBoxLayout(block_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetFixedSize)

        if block_type != "text":
            title_label = QLabel(labels[block_type])
            title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(title_label)

        text_input = None
        if block_type == "text":
            text_input = QLineEdit(value)
            text_input.setPlaceholderText("読み上げる固定テキスト")
            text_input.textChanged.connect(lambda _: self.on_text_block_changed(text_input, block_widget))
            layout.addWidget(text_input)
            self.update_text_block_width(text_input, block_widget)

        delete_button = QToolButton()
        delete_button.setText("×")
        delete_button.setAutoRaise(True)
        delete_button.setToolTip("削除")
        delete_button.setStyleSheet("QToolButton:hover { background-color: #c0392b; color: white; }")
        delete_button.clicked.connect(lambda: self.delete_read_block(block_widget))
        layout.addWidget(delete_button)

        self.read_block_layout.addWidget(block_widget)
        self.update_read_block_scroll_area_height()
        if emit_changed:
            self.settings_changed.emit()

    def update_text_block_width(self, text_input: QLineEdit, block_widget: QFrame) -> None:
        text = text_input.text() or text_input.placeholderText()
        width = text_input.fontMetrics().horizontalAdvance(text) + 36
        text_input.setFixedWidth(max(80, min(width, 360)))
        block_widget.adjustSize()

    def on_text_block_changed(self, text_input: QLineEdit, block_widget: QFrame) -> None:
        self.update_text_block_width(text_input, block_widget)
        self.update_read_block_scroll_area_height()
        self.settings_changed.emit()

    def read_block_widgets(self) -> list[QFrame]:
        widgets = []
        for index in range(self.read_block_layout.count()):
            widget = self.read_block_layout.itemAt(index).widget()
            if widget is not None and widget is not self.placeholder:
                widgets.append(widget)
        return widgets

    def update_read_block_scroll_area_height(self) -> None:
        widgets = self.read_block_widgets()
        height = max((widget.sizeHint().height() for widget in widgets), default=0)
        if height <= 0:
            return
        margins = self.read_block_layout.contentsMargins()
        spacing = self.read_block_layout.spacing() * max(len(widgets) - 1, 0)
        width = sum(widget.sizeHint().width() for widget in widgets)
        self.read_block_container.setMinimumWidth(width + spacing + margins.left() + margins.right())
        frame = self.read_block_scroll_area.frameWidth() * 2
        scrollbar = self.read_block_scroll_area.horizontalScrollBar().sizeHint().height()
        self.read_block_scroll_area.setFixedHeight(height + margins.top() + margins.bottom() + frame + scrollbar)

    def get_read_blocks(self) -> list[dict]:
        blocks = []
        for widget in self.read_block_widgets():
            block_type = widget.property("blockType")
            if block_type == "text":
                text_input = widget.findChild(QLineEdit) if widget else None
                blocks.append({"type": "text", "value": text_input.text() if text_input else ""})
            elif block_type in {"author", "message"}:
                blocks.append({"type": block_type})
        return normalize_read_blocks(blocks)

    def delete_read_block(self, block_widget: QFrame) -> None:
        self.read_block_layout.removeWidget(block_widget)
        block_widget.deleteLater()
        if not self.read_block_widgets():
            self.add_read_block("message", emit_changed=False)
        self.update_read_block_scroll_area_height()
        self.settings_changed.emit()

    def drop_on_placeholder(self, source_id: int) -> None:
        widgets = self.read_block_widgets()
        source_widget = next((widget for widget in widgets if widget.block_id == source_id), None)
        if source_widget is None:
            return
        layout = self.read_block_layout
        target_index = layout.indexOf(self.placeholder)
        if target_index == -1:
            return
        source_index = layout.indexOf(source_widget)
        layout.removeWidget(source_widget)
        if source_index != -1 and source_index < target_index:
            target_index -= 1
        layout.insertWidget(target_index, source_widget)
        self.placeholder.hide()
        layout.removeWidget(self.placeholder)
        self.update_read_block_scroll_area_height()
        self.settings_changed.emit()

    def on_tts_engine_changed(self, engine_name: str) -> None:
        new_engine = self._get_engine_key(engine_name)
        if new_engine == self.current_active_engine:
            return

        # 1. 現在のアクティブなエンジン（旧エンジン）の個別 URL/パス をバッファへ退避
        old_engine = self.current_active_engine
        if old_engine == "voicevox":
            self.engine_settings[old_engine]["url"] = self.vv_url_line.text().strip()
            self.engine_settings[old_engine]["path"] = self.vv_path_line.text().strip()
        elif old_engine == "coeiroink":
            self.engine_settings[old_engine]["url"] = self.coe_url_line.text().strip()
            self.engine_settings[old_engine]["path"] = self.coe_path_line.text().strip()
        elif old_engine == "bouyomichan":
            self.engine_settings[old_engine]["url"] = self.bc_url_line.text().strip()
            self.engine_settings[old_engine]["path"] = self.bc_path_line.text().strip()

        self.engine_settings[old_engine]["speaker_id"] = self.get_current_speaker_id()

        # 2. 現在アクティブなエンジンを新しいものに更新
        self.current_active_engine = new_engine

        # 3. 新しいエンジンのパラメータを画面へロードする
        self._update_ui_for_active_engine()

        self.settings_changed.emit()

    def on_opacity_slider_changed(self, value: int) -> None:
        self.settings_changed.emit()

    def select_bg_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.bg_color_hex), self.dialog_window, "背景色を選択")
        if color.isValid():
            self.bg_color_hex = color.name()
            self.update_color_button_style(self.bg_color_button, self.bg_color_hex)
            self.settings_changed.emit()

    def select_border_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.border_color_hex), self.dialog_window, "縁色を選択")
        if color.isValid():
            self.border_color_hex = color.name()
            self.update_color_button_style(self.border_color_button, self.border_color_hex)
            self.settings_changed.emit()

    def update_color_button_style(self, button: QPushButton, hex_color: str) -> None:
        color = QColor(hex_color)
        luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255.0
        text_color = "#000000" if luminance > 0.5 else "#ffffff"
        button.setStyleSheet(
            f"background-color: {hex_color}; color: {text_color}; border: 1px solid #555555; font-weight: bold;"
        )

    def accept_settings(self) -> None:
        self.save_settings()
        self.dialog_window.accept()

    def browse_voicevox_path(self) -> None:
        self._browse_path_for_line(self.vv_path_line)

    def browse_coeiroink_path(self) -> None:
        self._browse_path_for_line(self.coe_path_line)

    def browse_bouyomichan_path(self) -> None:
        self._browse_path_for_line(self.bc_path_line)

    def _browse_path_for_line(self, line_edit: QLineEdit) -> None:
        system = platform.system()
        filter_str = "Executable Files (*.exe);;All Files (*)" if system == "Windows" else "All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog_window, "音声合成エンジン実行ファイルを選択", line_edit.text().strip(), filter_str
        )
        if file_path:
            line_edit.setText(file_path)

    def rebuild_speaker_menu(self) -> None:
        self.speaker_menu.clear()
        grouped_speakers = group_speakers_by_kana(self.speakers_data)

        # グループごとにメニューを作成
        for group_name in SPEAKER_GROUP_ORDER:
            speakers_in_group = grouped_speakers[group_name]
            if not speakers_in_group:
                continue

            # 五十音グループのサブメニューを作成 (例: "あ行")
            group_menu = self.speaker_menu.addMenu(group_name)

            sorted_speakers = sorted(speakers_in_group.keys(), key=speaker_sort_key)

            for speaker_name in sorted_speakers:
                styles = speakers_in_group[speaker_name]
                char_menu = group_menu.addMenu(speaker_name)
                for style_name, style_id in styles:
                    action = QAction(style_name, self.dialog_window)
                    action.setData(style_id)
                    action.triggered.connect(
                        lambda checked=False, s_name=speaker_name, st_name=style_name, s_id=style_id: (
                            self.on_style_selected(s_name, st_name, s_id)
                        )
                    )
                    char_menu.addAction(action)

    def on_style_selected(self, speaker_name: str, style_name: str, speaker_id: int) -> None:
        self.current_speaker_id = speaker_id
        self.speaker_button.setText(f"{speaker_name} ({style_name})")
        self.settings_changed.emit()

    def get_current_speaker_id(self) -> int:
        return self.current_speaker_id

    def set_speaker_button_id(self, speaker_id: int) -> None:
        self.current_speaker_id = speaker_id
        found = False
        for speaker_name, styles in self.speakers_data.items():
            for style_name, style_id in styles:
                if style_id == speaker_id:
                    self.speaker_button.setText(f"{speaker_name} ({style_name})")
                    found = True
                    break
            if found:
                break

        if not found:
            self.speaker_button.setText(f"カスタム (ID: {speaker_id})")

    def get_engine_instance(self, url: str, exe_path: str) -> BaseTTSEngine:
        kind = TtsEngineKind(self.current_active_engine)
        config = config_from_backend(
            kind,
            {"url": url, "path": exe_path},
            self.main_app.config.speech.engine(kind),
        )
        return self.main_app.tts_registry.create(config)

    def _fetch_speaker_data(
        self,
        url: str,
        path: str = "",
    ) -> tuple[list[dict], dict[str, list[tuple[str, int]]]]:
        engine = self.get_engine_instance(url, path)
        speakers = engine.get_speakers()
        if not speakers:
            return [], {}

        new_data = {}
        for sp in speakers:
            name = sp.get("name", "")
            styles_list = []
            for style in sp.get("styles", []):
                style_name = style.get("name", "")
                style_id = style.get("id")
                styles_list.append((style_name, style_id))
            if styles_list:
                new_data[name] = styles_list
        return speakers, new_data

    def _apply_speaker_data(self, speaker_data: dict[str, list[tuple[str, int]]]) -> bool:
        if not speaker_data:
            return False
        self.speakers_data = speaker_data
        self.rebuild_speaker_menu()
        self.set_speaker_button_id(self.current_speaker_id)
        return True

    def update_speakers_from_engine(self) -> bool:
        # アクティブなエンジンの URL を取得
        if self.current_active_engine == "voicevox":
            url = self.vv_url_line.text().strip().rstrip("/")
        elif self.current_active_engine == "coeiroink":
            url = self.coe_url_line.text().strip().rstrip("/")
        elif self.current_active_engine == "bouyomichan":
            url = self.bc_url_line.text().strip().rstrip("/")
        elif self.current_active_engine == "supertonic_lightweight":
            url = "local://supertonic-lightweight"
        elif self.current_active_engine == "supertonic":
            url = "local://supertonic"
        else:
            url = ""

        if not url:
            return False
        try:
            path = (
                self.engine_settings["supertonic_lightweight"]["path"]
                if self.current_active_engine == "supertonic_lightweight"
                else ""
            )
            _, speaker_data = self._fetch_speaker_data(url, path)
            return self._apply_speaker_data(speaker_data)
        except Exception as exc:
            self.main_app.append_log(f"[情報] 話者リスト取得スキップ: {exc}")
        return False

    def test_tts_connection(self) -> None:
        if self.current_active_engine == "voicevox":
            url = self.vv_url_line.text().strip().rstrip("/")
            path = self.vv_path_line.text().strip()
        elif self.current_active_engine == "coeiroink":
            url = self.coe_url_line.text().strip().rstrip("/")
            path = self.coe_path_line.text().strip()
        elif self.current_active_engine == "bouyomichan":
            url = self.bc_url_line.text().strip().rstrip("/")
            path = self.bc_path_line.text().strip()
        elif self.current_active_engine == "supertonic_lightweight":
            url = "local://supertonic-lightweight"
            path = self.engine_settings["supertonic_lightweight"]["path"]
        elif self.current_active_engine == "supertonic":
            url = "local://supertonic"
            path = self.engine_settings["supertonic"]["path"]
        else:
            url = ""
            path = ""

        if not url and self.current_active_engine not in {"supertonic_lightweight", "supertonic"}:
            QMessageBox.warning(self.dialog_window, "入力不足", "接続URLを入力してください。")
            return

        engine_type = self._get_engine_key(self.tts_engine_combo.currentText())
        device = self.st_device_combo.currentData() if engine_type == "supertonic" else "cpu"

        if engine_type == "supertonic":
            self._start_supertonic_connection_test(url, path, engine_type, device)
            return

        kind = TtsEngineKind(engine_type)
        engine = config_from_backend(
            kind,
            {"url": url, "path": path, "device": device},
            self.main_app.config.speech.engine(kind),
        )
        self.main_app.ensure_tts_running(engine)

        try:
            speakers, speaker_data = self._fetch_speaker_data(url, path)
            if not speakers:
                raise RuntimeError("話者情報が取得できませんでした。")

            if self._apply_speaker_data(speaker_data):
                self.main_app.append_log("話者リストを更新しました。")

            lines: list[str] = []
            for speaker in speakers[:8]:
                name = speaker.get("name", "?")
                styles = speaker.get("styles", [])
                style_text = ", ".join(f"{s.get('name')}={s.get('id')}" for s in styles[:6])
                lines.append(f"{name}: {style_text}")
            self.main_app.append_log("接続OK")
            self.main_app.append_log(" / ".join(lines) if lines else "speaker情報なし")
        except Exception as exc:
            self.main_app.show_error(f"接続に失敗しました: {exc}")

    def _start_supertonic_connection_test(
        self,
        url: str,
        path: str,
        engine_type: str,
        device: str,
    ) -> None:
        device_name = self.st_device_combo.currentText()
        self.tts_test_button.setEnabled(False)
        self.connection_progress = QProgressDialog(
            f"{device_name}でモデルを初期化しています。\n初回は1～2分かかる場合があります。",
            "",
            0,
            0,
            self.dialog_window,
        )
        self.connection_progress.setWindowTitle("SUPERTONIC 3 接続確認")
        self.connection_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.connection_progress.setCancelButton(None)
        self.connection_progress.setMinimumDuration(0)
        self.connection_progress.show()

        self.main_app.test_tts_configuration(
            {
                "engine_type": engine_type,
                "engine_config": self.engine_settings[engine_type],
                "url": url,
                "path": path,
                "device": device,
                "signature": (engine_type, url, path, device),
            },
            self._on_supertonic_connection_test_completed,
        )

    def _on_supertonic_connection_test_completed(
        self,
        success: bool,
        error: str,
    ) -> None:
        self.connection_progress.close()
        self.tts_test_button.setEnabled(True)

        engine = self.main_app.tts_engine
        if not success or engine is None:
            detail = f"\n\n詳細: {error}" if error else ""
            self.main_app.show_error(f"SUPERTONIC 3の初期化に失敗しました。{detail}")
            return

        try:
            speakers = engine.get_speakers() or []
            speaker_data = self._convert_speakers(speakers)
            if self._apply_speaker_data(speaker_data):
                self.main_app.append_log("話者リストを更新しました。")

            active_device = getattr(engine, "active_device", "")
            self.main_app.append_log(f"接続OK: {active_device or engine.DISPLAY_NAME}")
        except Exception as exc:
            self.main_app.show_error(f"話者情報の取得に失敗しました: {exc}")

    @staticmethod
    def _convert_speakers(
        speakers: list[dict],
    ) -> dict[str, list[tuple[str, int]]]:
        speaker_data = {}
        for speaker in speakers:
            styles = [
                (style.get("name", ""), style.get("id"))
                for style in speaker.get("styles", [])
                if style.get("name", "") and style.get("id") is not None
            ]
            if styles:
                speaker_data[speaker.get("name", "")] = styles
        return speaker_data

    def on_group_changed(self, new_group_name: str) -> None:
        if self._block_group_change_signal:
            return
        if not new_group_name:
            return
        # 旧グループに対する自動退避
        if self.current_active_group_name and self.current_active_group_name in self.word_dict:
            self.update_current_group_data_for(self.current_active_group_name)

        self.current_active_group_name = new_group_name
        self.display_words_for_group()
        self.settings_changed.emit()

    def display_words_for_group(self) -> None:
        self._block_group_change_signal = True
        self.word_table.blockSignals(True)
        self.word_table.setUpdatesEnabled(False)
        self.word_table.setRowCount(0)

        group_name = self.group_combo.currentText()
        if group_name and group_name in self.word_dict:
            words = self.word_dict[group_name]
            self.word_table.setRowCount(len(words))
            for row, item in enumerate(words):
                self.word_table.setItem(row, 0, QTableWidgetItem(item.get("reading", "")))
                self.word_table.setItem(row, 1, QTableWidgetItem(item.get("word", "")))
                self.word_table.setItem(row, 2, QTableWidgetItem(item.get("pos", "名詞")))
                self.word_table.setItem(row, 3, QTableWidgetItem(item.get("comment", "")))
        self.word_table.setUpdatesEnabled(True)
        self.word_table.blockSignals(False)
        self._block_group_change_signal = False

    def update_current_group_data_for(self, group_name: str) -> None:
        if not group_name:
            return

        word_list = []
        for row in range(self.word_table.rowCount()):
            reading_item = self.word_table.item(row, 0)
            word_item = self.word_table.item(row, 1)
            pos_item = self.word_table.item(row, 2)
            comment_item = self.word_table.item(row, 3)

            reading = reading_item.text().strip() if reading_item else ""
            word = word_item.text().strip() if word_item else ""
            pos = pos_item.text().strip() if pos_item else "名詞"
            comment = comment_item.text().strip() if comment_item else ""

            if word:
                word_list.append({"word": word, "reading": reading, "pos": pos, "comment": comment})
        self.word_dict[group_name] = word_list

    def add_word_row(self) -> None:
        self.word_table.blockSignals(True)
        row = self.word_table.rowCount()
        self.word_table.insertRow(row)
        self.word_table.setItem(row, 0, QTableWidgetItem(""))
        self.word_table.setItem(row, 1, QTableWidgetItem(""))
        self.word_table.setItem(row, 2, QTableWidgetItem("名詞"))
        self.word_table.setItem(row, 3, QTableWidgetItem(""))
        self.word_table.blockSignals(False)
        self.settings_changed.emit()

    def delete_word_row(self) -> None:
        row = self.word_table.currentRow()
        if row >= 0:
            self.word_table.removeRow(row)
            self.settings_changed.emit()

    def import_words(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog_window,
            "辞書インポート",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return

        try:
            imported_words = dictionary.load_import_word_list(file_path)
            self.word_table.blockSignals(True)
            self.word_table.setUpdatesEnabled(False)

            start_row = self.word_table.rowCount()
            self.word_table.setRowCount(start_row + len(imported_words))
            for i, item in enumerate(imported_words):
                row = start_row + i
                self.word_table.setItem(row, 0, QTableWidgetItem(item.get("reading", "")))
                self.word_table.setItem(row, 1, QTableWidgetItem(item.get("word", "")))
                self.word_table.setItem(row, 2, QTableWidgetItem(item.get("pos", "名詞")))
                self.word_table.setItem(row, 3, QTableWidgetItem(item.get("comment", "")))

            self.word_table.setUpdatesEnabled(True)
            self.word_table.blockSignals(False)
            imported_count = len(imported_words)
            if imported_count > 0:
                self.settings_changed.emit()
                QMessageBox.information(
                    self.dialog_window, "インポート", f"{imported_count}件の単語をインポートしました。"
                )
        except Exception as exc:
            self.word_table.blockSignals(False)
            QMessageBox.critical(self.dialog_window, "インポートエラー", f"インポートに失敗しました: {exc}")

    def add_dictionary_group(self) -> None:
        group_name, ok = QInputDialog.getText(
            self.dialog_window, "グループ追加", "新しい辞書グループ名を入力してください:"
        )
        if ok and group_name:
            group_name = group_name.strip()
            if not group_name:
                return
            if group_name in self.word_dict:
                QMessageBox.warning(self.dialog_window, "重複エラー", "同名のグループが既に存在します。")
                return

            # 現在のデータを保存
            if self.current_active_group_name:
                self.update_current_group_data_for(self.current_active_group_name)

            # 新規追加
            self.word_dict[group_name] = []

            self._block_group_change_signal = True
            self.group_combo.addItem(group_name)
            self.group_combo.setCurrentText(group_name)
            self.current_active_group_name = group_name
            self._block_group_change_signal = False

            self.display_words_for_group()
            self.settings_changed.emit()

    def rename_dictionary_group(self) -> None:
        current_group = self.group_combo.currentText()
        if not current_group:
            return

        new_name, ok = QInputDialog.getText(
            self.dialog_window,
            "グループ名変更",
            "新しいグループ名を入力してください:",
            QLineEdit.EchoMode.Normal,
            current_group,
        )
        if ok and new_name:
            new_name = new_name.strip()
            if not new_name or new_name == current_group:
                return
            if new_name in self.word_dict:
                QMessageBox.warning(self.dialog_window, "重複エラー", "同名のグループが既に存在します。")
                return

            # 現在のデータを一時保存
            self.update_current_group_data_for(current_group)

            # キーの差し替え
            self.word_dict[new_name] = self.word_dict.pop(current_group)

            # コンボボックスの更新
            self._block_group_change_signal = True
            idx = self.group_combo.currentIndex()
            self.group_combo.setItemText(idx, new_name)
            self.group_combo.setCurrentText(new_name)
            self.current_active_group_name = new_name
            self._block_group_change_signal = False

            self.settings_changed.emit()

    def delete_dictionary_group(self) -> None:
        current_group = self.group_combo.currentText()
        if not current_group:
            return

        if self.group_combo.count() <= 1:
            QMessageBox.warning(self.dialog_window, "削除エラー", "最後のグループは削除できません。")
            return

        reply = QMessageBox.question(
            self.dialog_window,
            "グループ削除",
            f"グループ「{current_group}」を削除しますか？\n登録されている単語リストも削除されます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.word_dict.pop(current_group, None)

            self._block_group_change_signal = True
            idx = self.group_combo.currentIndex()
            self.group_combo.removeItem(idx)
            self.group_combo.setCurrentIndex(0)
            self.current_active_group_name = self.group_combo.currentText()
            self._block_group_change_signal = False

            self.display_words_for_group()
            self.settings_changed.emit()

    def get_active_word_list(self) -> list[dict]:
        if self.current_active_group_name:
            self.update_current_group_data_for(self.current_active_group_name)
        if self.current_active_group_name and self.current_active_group_name in self.word_dict:
            return self.word_dict[self.current_active_group_name]
        return []

    def get_all_merged_word_list(self) -> list[dict]:
        if self.current_active_group_name:
            self.update_current_group_data_for(self.current_active_group_name)
        merged = []
        for words in self.word_dict.values():
            merged.extend(words)
        return merged

    def download_supertonic_lightweight_model(self) -> None:
        from livevoicebridge.infrastructure.downloads.lightweight import ModelDownloader

        self.downloader = ModelDownloader(self.dialog_window, self.engine_settings, self.settings_changed)
        self.downloader.start()
        self._refresh_lightweight_model_selection()

    def download_supertonic_model(self) -> None:
        from livevoicebridge.infrastructure.downloads.supertonic import SupertonicModelDownloader

        self.supertonic_downloader = SupertonicModelDownloader(
            self.dialog_window,
            self.engine_settings,
            self.settings_changed,
        )
        self.supertonic_downloader.start()
        self._refresh_supertonic_model_selection()
