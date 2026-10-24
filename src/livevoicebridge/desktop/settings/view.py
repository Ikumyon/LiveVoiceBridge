from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices
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
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QWidget,
)

from livevoicebridge.core.chat.models import StreamingConfig
from livevoicebridge.core.dictionary.models import DictionaryConfig
from livevoicebridge.core.settings.models import AppConfig, ApplicationConfig, PopupMetricsConfig, ResourceLimits
from livevoicebridge.core.speech.forms import normalize_read_blocks
from livevoicebridge.core.speech.models import (
    EngineConfig,
    ReadBlock,
    ReadBlockKind,
    Speaker,
    SpeechConfig,
    TtsEngineKind,
    update_engine,
)
from livevoicebridge.desktop.dictionary.delegates import HiraganaDelegate
from livevoicebridge.desktop.dictionary.model import DictionaryTableModel
from livevoicebridge.desktop.forms import load_form
from livevoicebridge.desktop.monitoring.popup import POPUP_METRIC_MODES, POPUP_METRIC_PLACEMENTS
from livevoicebridge.desktop.resources import EXTERNAL_LINK_ICON_FILE
from livevoicebridge.desktop.settings.read_blocks import PlaceholderFrame, ReadBlockFrame
from livevoicebridge.desktop.settings.speakers import SPEAKER_GROUP_ORDER, group_speakers_by_kana, speaker_sort_key


def _engine_form(config: EngineConfig) -> dict:
    from dataclasses import asdict

    values = asdict(config)
    values["path"] = values.pop("executable_path")
    return values


def _read_block_forms(blocks: tuple[ReadBlock, ...]) -> list[dict[str, str]]:
    return [
        {"type": block.kind.value, **({"value": block.value} if block.kind is ReadBlockKind.TEXT else {})}
        for block in blocks
    ]


def _engine_from_form(existing: EngineConfig, form: dict) -> EngineConfig:
    values = dict(form)
    values["executable_path"] = values.pop("path", "")
    return update_engine(existing, values)


class SettingsDialog(QObject):
    # 設定が変更されたことをメインウィンドウへ通知するシグナル
    settings_changed = Signal()
    speakers_received = Signal(object, str)
    speakers_requested = Signal(object)
    import_requested = Signal(str)
    import_received = Signal(object, str)

    def __init__(self, config: AppConfig, word_dict_data: dict[str, list[dict]], catalog: list, executable_filter: str):
        super().__init__()
        self.config = config
        self.metric_catalog = catalog
        self._executable_filter = executable_filter
        self.speakers_received.connect(self._on_speakers_received)
        self.import_received.connect(self._on_import_received)
        self._initial_word_dict_data = word_dict_data
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

        self._bind_resource_widgets()
        self.load_settings()
        self.connect_signals()

    def _bind_resource_widgets(self) -> None:
        self._resource_controls: dict[str, tuple[QSlider, QSpinBox]] = {}
        for name in ("comment_count", "log_lines", "audio_mib", "avatar_mib"):
            slider = self.dialog_window.findChild(QSlider, name + "Slider")
            spin = self.dialog_window.findChild(QSpinBox, name + "SpinBox")
            self._resource_controls[name] = (slider, spin)
            spin.setValue(getattr(self.config.resources, name))
            slider.setValue(spin.value())
            slider.valueChanged.connect(lambda value, key=name: self._set_resource_value(key, value))
            spin.valueChanged.connect(lambda value, key=name: self._set_resource_value(key, value))

    def _set_resource_value(self, key: str, value: int) -> None:
        slider, spin = self._resource_controls[key]
        step = spin.singleStep()
        value = min(spin.maximum(), max(spin.minimum(), round(value / step) * step))
        with QSignalBlocker(slider), QSignalBlocker(spin):
            slider.setValue(value)
            spin.setValue(value)
        self.settings_changed.emit()

    def _load_dialog_window(self) -> QWidget:
        return load_form("settings_dialog", widgets=(PlaceholderFrame,))

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
                from livevoicebridge.desktop.comments.rendering import load_svg_icon

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
        self.qwen3_page: QWidget = self.dialog_window.findChild(QWidget, "qwen3Page")
        self.qwen3_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "qwen3UrlLineEdit")
        self.qwen3_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "qwen3VolumeSpinBox")
        self.qwen3_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "qwen3MaxLengthSpinBox")

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
        self.settings_tabs: QTabWidget = self.dialog_window.findChild(QTabWidget, "settingsTabWidget")
        self.dictionary_tab: QWidget = self.dialog_window.findChild(QWidget, "dictionaryTab")
        self.word_table: QTableView = self.dialog_window.findChild(QTableView, "wordTableView")
        self.add_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "addWordButton")
        self.delete_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteWordButton")
        self.import_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "importWordButton")
        self.group_combo: QComboBox = self.dialog_window.findChild(QComboBox, "dictionaryGroupComboBox")
        self.add_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "addGroupButton")
        self.rename_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "renameGroupButton")
        self.delete_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteGroupButton")

    def _setup_dictionary_table(self) -> None:
        self.word_model = DictionaryTableModel(self.word_table)
        self.word_table.setModel(self.word_model)
        self.word_table.horizontalHeader().setStretchLastSection(True)
        # 読み列（0列目）をひらがな限定に制限
        self.word_table.setItemDelegateForColumn(0, HiraganaDelegate(self.word_table))

    def _init_dictionary_state(self) -> None:
        self.word_dict: dict[str, list[dict]] = {}
        self.current_active_group_name = ""
        self._block_group_change_signal = False
        self._dictionary_view_loaded = False

    def _setup_read_block_placeholder(self) -> None:
        self.placeholder = self.dialog_window.findChild(PlaceholderFrame, "readBlockPlaceholder")
        self.placeholder.dialog = self
        self.placeholder.hide()

    def _setup_speaker_menu(self) -> None:
        # プルダウンメニューの初期設定
        self.speakers_data: dict[str, list[tuple[str, int]]] = {}
        self.current_speaker_id = 1
        self._speaker_source_loaded: tuple[str, str, str] | None = None
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

    def _setup_tts_engine_combo(self) -> None:
        # 音声エンジン選択のバインド
        self.tts_engine_combo: QComboBox = self.dialog_window.findChild(QComboBox, "ttsEngineComboBox")

    def _init_engine_settings(self) -> None:
        self.engine_settings = {engine.kind.value: _engine_form(engine) for engine in self.config.speech.engines}
        self.current_active_engine = self.config.speech.active_engine.value

    def _init_color_state(self) -> None:
        # カラー値の保持
        self.bg_color_hex = ""
        self.border_color_hex = ""

    def _get_engine_key(self, display_name: str) -> str:
        return display_name.lower()

    def _get_engine_display_name(self, key: str) -> str:
        return key.upper()

    def _update_ui_for_active_engine(self) -> None:
        # アクティブなエンジンのパラメータを共通ウィジェットへロード
        active_config = self.engine_settings[self.current_active_engine]

        self.current_speaker_id = active_config.get("speaker_id", 0)
        self.set_speaker_button_id(self.current_speaker_id)

        self.speakers_data = {}
        self._speaker_source_loaded = None
        self.rebuild_speaker_menu()

        # StackedWidget ページの切り替え
        if self.current_active_engine == "voicevox":
            self.tts_engine_stacked.setCurrentWidget(self.voicevox_page)
        elif self.current_active_engine == "coeiroink":
            self.tts_engine_stacked.setCurrentWidget(self.coeiroink_page)
        elif self.current_active_engine == "bouyomichan":
            self.tts_engine_stacked.setCurrentWidget(self.bouyomichan_page)
        elif self.current_active_engine == "qwen3":
            self.tts_engine_stacked.setCurrentWidget(self.qwen3_page)

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        config = self.config
        self.api_key_line.setText(config.streaming.youtube_api_key or env_key)
        self.current_active_engine = config.speech.active_engine.value
        for engine in config.speech.engines:
            self.engine_settings[engine.kind.value].update(_engine_form(engine))

        vv = self.engine_settings["voicevox"]
        coe = self.engine_settings["coeiroink"]
        bc = self.engine_settings["bouyomichan"]
        qwen3 = self.engine_settings["qwen3"]
        self.qwen3_url_line.setText(qwen3["url"])
        self.qwen3_volume_spin.setValue(qwen3["volume"])
        self.qwen3_max_length_spin.setValue(qwen3["max_length"])

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
        self.word_dict = deepcopy(self._initial_word_dict_data)

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
        self.refresh_popup_metric_catalog(self.metric_catalog)

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
        self.engine_settings["qwen3"].update(self._qwen3_form())
        # 読み替え辞書のセーブ
        self.word_dict = self._clean_word_dict()

        current = self.config
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
                queue_limit=current.speech.queue_limit,
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
            resources=ResourceLimits(**{key: spin.value() for key, (_, spin) in self._resource_controls.items()}),
            application=ApplicationConfig(
                check_updates=self.check_updates_check.isChecked(),
                use_ime=current.application.use_ime,
            ),
        )
        self.config = updated

    def _qwen3_form(self) -> dict:
        return {
            "url": self.qwen3_url_line.text().strip(),
            "path": "",
            "speaker_id": self.get_current_speaker_id()
            if self.current_active_engine == "qwen3"
            else self.engine_settings["qwen3"]["speaker_id"],
            "speed": 1.0,
            "pitch": 0.0,
            "volume": self.qwen3_volume_spin.value(),
            "max_length": self.qwen3_max_length_spin.value(),
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
        self.qwen3_url_line.editingFinished.connect(self.settings_changed.emit)
        self.qwen3_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.qwen3_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

        self.speaker_menu.aboutToShow.connect(self._load_speakers_for_current_source)

        # 読み替え辞書シグナル
        self.add_word_button.clicked.connect(self.add_word_row)
        self.delete_word_button.clicked.connect(self.delete_word_row)
        self.import_word_button.clicked.connect(self.import_words)
        self.add_group_button.clicked.connect(self.add_dictionary_group)
        self.rename_group_button.clicked.connect(self.rename_dictionary_group)
        self.delete_group_button.clicked.connect(self.delete_dictionary_group)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.word_model.changed.connect(self.settings_changed.emit)
        self.settings_tabs.currentChanged.connect(self.on_settings_tab_changed)
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

        if self.settings_tabs.currentWidget() is self.dictionary_tab:
            self._load_dictionary_view()

    def refresh_popup_metric_catalog(self, catalog: list) -> None:
        """検出済みメトリクスを設定表へ反映し、編集中の選択を保持する。"""
        if getattr(self, "_rendered_catalog", None) == catalog:
            return
        self._rendered_catalog = list(catalog)
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
        current = self.config.presentation.popup_metrics
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
        elif old_engine == "qwen3":
            self.engine_settings[old_engine].update(self._qwen3_form())

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
        filter_str = self._executable_filter
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

    def _load_speakers_for_current_source(self) -> None:
        engine_type, url, path = self._current_speaker_source()
        source = (engine_type, url, path)
        if source == self._speaker_source_loaded:
            return
        self._speaker_source_loaded = source
        self.update_speakers_from_engine()

    def _current_speaker_source(self) -> tuple[str, str, str]:
        if self.current_active_engine == "voicevox":
            return (
                self.current_active_engine,
                self.vv_url_line.text().strip().rstrip("/"),
                self.vv_path_line.text().strip(),
            )
        if self.current_active_engine == "coeiroink":
            return (
                self.current_active_engine,
                self.coe_url_line.text().strip().rstrip("/"),
                self.coe_path_line.text().strip(),
            )
        if self.current_active_engine == "bouyomichan":
            return (
                self.current_active_engine,
                self.bc_url_line.text().strip().rstrip("/"),
                self.bc_path_line.text().strip(),
            )
        if self.current_active_engine == "qwen3":
            return self.current_active_engine, self.qwen3_url_line.text().strip().rstrip("/"), ""
        raise ValueError(f"未対応のTTSエンジンです: {self.current_active_engine}")

    def _on_speakers_received(self, speakers: tuple[Speaker, ...], error: str) -> None:
        self.tts_test_button.setEnabled(True)
        if error:
            self._speaker_source_loaded = None
            QMessageBox.warning(self.dialog_window, "話者取得", error)
            return
        self.speakers_data = {}
        for speaker in speakers:
            self.speakers_data.setdefault(speaker.name, []).append((speaker.style, speaker.identifier))
        self.rebuild_speaker_menu()
        self.set_speaker_button_id(self.current_speaker_id)

    def update_speakers_from_engine(self) -> None:
        engine_type, url, path = self._current_speaker_source()
        config = update_engine(
            self.config.speech.engine(TtsEngineKind(engine_type)), {"url": url, "executable_path": path}
        )
        self.tts_test_button.setEnabled(False)
        self.speakers_requested.emit(config)

    def test_tts_connection(self) -> None:
        self.update_speakers_from_engine()

    def on_group_changed(self, new_group_name: str) -> None:
        if self._block_group_change_signal:
            return
        if not new_group_name:
            return
        self.current_active_group_name = new_group_name
        if self._dictionary_view_loaded:
            self.word_model.set_rows(self.word_dict[new_group_name])

    def on_settings_tab_changed(self, _index: int) -> None:
        if self.settings_tabs.currentWidget() is self.dictionary_tab:
            self._load_dictionary_view()

    def _load_dictionary_view(self) -> None:
        if self._dictionary_view_loaded:
            return
        self._dictionary_view_loaded = True
        self.word_model.set_rows(self.word_dict.get(self.current_active_group_name, []))

    def _clean_word_dict(self) -> dict[str, list[dict]]:
        return {
            group: [
                {
                    "word": str(item.get("word", "")).strip(),
                    "reading": str(item.get("reading", "")).strip(),
                    "pos": str(item.get("pos", "名詞")).strip() or "名詞",
                    "comment": str(item.get("comment", "")).strip(),
                }
                for item in words
                if str(item.get("word", "")).strip()
            ]
            for group, words in self.word_dict.items()
        }

    def add_word_row(self) -> None:
        self._load_dictionary_view()
        self.word_model.append_empty_row()
        self.word_table.edit(self.word_model.index(self.word_model.rowCount() - 1, 0))

    def delete_word_row(self) -> None:
        self.word_model.remove_row(self.word_table.currentIndex().row())

    def import_words(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog_window,
            "辞書インポート",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return

        self.import_word_button.setEnabled(False)
        self.group_combo.setEnabled(False)
        for button in (self.add_group_button, self.rename_group_button, self.delete_group_button):
            button.setEnabled(False)
        self.import_requested.emit(file_path)

    def _on_import_received(self, entries, error):
        self.import_word_button.setEnabled(True)
        self.group_combo.setEnabled(True)
        for button in (self.add_group_button, self.rename_group_button, self.delete_group_button):
            button.setEnabled(True)
        if error:
            QMessageBox.critical(self.dialog_window, "インポートエラー", error)
            return
        imported = [
            {"word": entry.word, "reading": entry.reading, "pos": entry.part_of_speech, "comment": entry.comment}
            for entry in entries
        ]
        self._load_dictionary_view()
        self.word_model.append_rows(imported)
        if imported:
            QMessageBox.information(self.dialog_window, "インポート", f"{len(imported)}件の単語をインポートしました。")

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

            # 新規追加
            self.word_dict[group_name] = []

            self._block_group_change_signal = True
            self.group_combo.addItem(group_name)
            self.group_combo.setCurrentText(group_name)
            self.current_active_group_name = group_name
            self._block_group_change_signal = False

            self.word_model.set_rows(self.word_dict[group_name])
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

            self.word_model.set_rows(self.word_dict[self.current_active_group_name])
            self.settings_changed.emit()

    def get_active_word_list(self) -> list[dict]:
        cleaned = self._clean_word_dict()
        if self.current_active_group_name and self.current_active_group_name in cleaned:
            return cleaned[self.current_active_group_name]
        return []

    def get_all_merged_word_list(self) -> list[dict]:
        merged = []
        for words in self._clean_word_dict().values():
            merged.extend(words)
        return merged
