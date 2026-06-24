from __future__ import annotations

import os
import platform
import tarfile
import urllib.request
import tempfile
from pathlib import Path

from PySide6.QtCore import QFile, QMimeData, QObject, QPoint, QRegularExpression, Signal, Qt, QThread
from PySide6.QtGui import QAction, QDrag, QRegularExpressionValidator, QColor
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QComboBox,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QInputDialog,
    QHBoxLayout,
    QSlider,
    QLabel,
    QColorDialog,
    QFrame,
    QWidget,
    QProgressDialog,
    QStackedWidget,
)

from core.app_config import SETTINGS_UI_FILE, EXE_DIR
from core.comment_processing import normalize_read_blocks

# 循環参照を防ぐためにTYPE_CHECKINGを使用
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import LiveVoiceBridgeApp
    from core.tts.base import BaseTTSEngine
 
import core.dictionary as dictionary
import core.tts.factory as tts_factory
from core.speakers.utils import SPEAKER_GROUP_ORDER, group_speakers_by_kana, speaker_sort_key


class ModelDownloadWorker(QThread):
    progress = Signal(int, str)  # 進捗率 (%), メッセージ
    finished = Signal(bool, str) # 成功したか, メッセージ

    def __init__(self, download_url: str, dest_dir: Path):
        super().__init__()
        self.download_url = download_url
        self.dest_dir = dest_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress.emit(0, "ダウンロード中...")
            
            # 一時ファイルへダウンロード
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.bz2")
            temp_file.close()
            temp_path = Path(temp_file.name)
            
            req = urllib.request.Request(self.download_url, headers={"User-Agent": "LiveVoiceBridge"})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get("Content-Length", 0))
                downloaded_size = 0
                block_size = 8192
                
                with open(temp_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            self.finished.emit(False, "キャンセルされました。")
                            try:
                                temp_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                            return
                            
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded_size += len(buffer)
                        if total_size > 0:
                            pct = int((downloaded_size / total_size) * 80)
                            self.progress.emit(pct, f"ダウンロード中... ({downloaded_size // 1024} KB / {total_size // 1024} KB)")
            
            self.progress.emit(80, "アーカイブを展開中...")
            if self._is_cancelled:
                self.finished.emit(False, "キャンセルされました。")
                temp_path.unlink(missing_ok=True)
                return
                
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(temp_path, "r:bz2") as tar:
                members = tar.getmembers()
                total_members = len(members)
                for idx, member in enumerate(members):
                    if self._is_cancelled:
                        self.finished.emit(False, "キャンセルされました。")
                        temp_path.unlink(missing_ok=True)
                        return
                    
                    tar.extract(member, path=self.dest_dir)
                    
                    if total_members > 0:
                        pct = 80 + int((idx / total_members) * 20)
                        self.progress.emit(pct, f"展開中... ({idx} / {total_members})")
            
            temp_path.unlink(missing_ok=True)
            self.progress.emit(100, "完了しました。")
            self.finished.emit(True, "モデルのダウンロードと配置が完了しました。")
            
        except Exception as e:
            self.finished.emit(False, f"エラーが発生しました: {e}")


class HiraganaDelegate(QStyledItemDelegate):
    """読み列（0列目）をひらがなのみ入力に制限するデリゲート。"""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        # ひらがな・長音符・句読点などを許可する正規表現
        pattern = QRegularExpression("[\u3040-\u309F\u30FC]*")
        validator = QRegularExpressionValidator(pattern, editor)
        editor.setValidator(validator)
        return editor


class PlaceholderFrame(QFrame):
    def __init__(self, dialog: SettingsDialog):
        super().__init__()
        self.dialog = dialog
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(ReadBlockFrame.MIME_TYPE)).decode("utf-8"))
            self.dialog.drop_on_placeholder(source_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ReadBlockFrame(QFrame):
    move_requested = Signal(int)
    MIME_TYPE = "application/x-livevoicebridge-read-block"

    def __init__(self, block_id: int, dialog: SettingsDialog):
        super().__init__()
        self.block_id = block_id
        self.dialog = dialog
        self._drag_start_pos = QPoint()
        self.setAcceptDrops(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        mime_data = QMimeData()
        mime_data.setData(self.MIME_TYPE, str(self.block_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.MoveAction)
        # ドラッグ終了時のクリーンアップ
        self.dialog.placeholder.hide()
        if self.dialog.read_block_layout.indexOf(self.dialog.placeholder) != -1:
            self.dialog.read_block_layout.removeWidget(self.dialog.placeholder)
        self.dialog.update_read_block_scroll_area_height()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
            if source_id != self.block_id:
                self._update_placeholder_pos(event.position().x(), source_id)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
            if source_id != self.block_id:
                self._update_placeholder_pos(event.position().x(), source_id)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(self.MIME_TYPE):
            super().dropEvent(event)
            return
        source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
        if source_id != self.block_id:
            self.move_requested.emit(source_id)
        event.acceptProposedAction()

    def _update_placeholder_pos(self, x: float, source_id: int) -> None:
        widgets = self.dialog.read_block_widgets()
        source_widget = next((w for w in widgets if w.block_id == source_id), None)
        if source_widget:
            self.dialog.placeholder.setFixedSize(source_widget.size())
            
        layout = self.dialog.read_block_layout
        target_index = layout.indexOf(self)
        
        insert_after = x > (self.width() / 2)
        if insert_after:
            target_index += 1
            
        current_placeholder_idx = layout.indexOf(self.dialog.placeholder)
        
        if current_placeholder_idx == target_index:
            return
            
        if current_placeholder_idx != -1:
            layout.removeWidget(self.dialog.placeholder)
            
        layout.insertWidget(target_index, self.dialog.placeholder)
        self.dialog.placeholder.show()
        self.dialog.update_read_block_scroll_area_height()


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
        self._setup_individual_max_length_spins()
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
        self.speaker_button: QPushButton = self.dialog_window.findChild(QPushButton, "speakerButton")
        self.skip_history_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_super_chat_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.check_updates_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "checkUpdatesCheckBox")
        self.tts_test_button: QPushButton = self.dialog_window.findChild(QPushButton, "ttsTestButton")
        self.button_box: QDialogButtonBox = self.dialog_window.findChild(QDialogButtonBox, "buttonBox")

    def _bind_tts_page_widgets(self) -> None:
        # StackedWidget とページのバインド
        self.tts_engine_stacked: QStackedWidget = self.dialog_window.findChild(QStackedWidget, "ttsEngineStackedWidget")
        self.voicevox_page: QWidget = self.dialog_window.findChild(QWidget, "voicevoxPage")
        self.coeiroink_page: QWidget = self.dialog_window.findChild(QWidget, "coeiroinkPage")
        self.bouyomichan_page: QWidget = self.dialog_window.findChild(QWidget, "bouyomichanPage")
        self.sherpa_supertonic_page: QWidget = self.dialog_window.findChild(QWidget, "sherpaSupertonicPage")

        # VOICEVOX ウィジェット
        self.vv_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxUrlLineEdit")
        self.vv_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxPathLineEdit")
        self.vv_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "voicevoxPathBrowseButton")
        self.vv_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxSpeedDoubleSpinBox")
        self.vv_pitch_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxPitchDoubleSpinBox")
        self.vv_intonation_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxIntonationDoubleSpinBox")
        self.vv_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxVolumeDoubleSpinBox")
        self.vv_pause_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxPauseLengthDoubleSpinBox")
        self.vv_pre_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxPrePhonemeLengthDoubleSpinBox")
        self.vv_post_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "voicevoxPostPhonemeLengthDoubleSpinBox")
        self.vv_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "voicevoxMaxLengthSpinBox")

        # COEIROINK ウィジェット
        self.coe_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "coeiroinkUrlLineEdit")
        self.coe_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "coeiroinkPathLineEdit")
        self.coe_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "coeiroinkPathBrowseButton")
        self.coe_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkSpeedDoubleSpinBox")
        self.coe_pitch_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkPitchDoubleSpinBox")
        self.coe_intonation_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkIntonationDoubleSpinBox")
        self.coe_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkVolumeDoubleSpinBox")
        self.coe_pause_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkPauseLengthDoubleSpinBox")
        self.coe_pre_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkPrePhonemeLengthDoubleSpinBox")
        self.coe_post_phoneme_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "coeiroinkPostPhonemeLengthDoubleSpinBox")
        self.coe_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "coeiroinkMaxLengthSpinBox")

        # 棒読みちゃん ウィジェット
        self.bc_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "bouyomichanUrlLineEdit")
        self.bc_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "bouyomichanPathLineEdit")
        self.bc_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "bouyomichanPathBrowseButton")
        self.bc_speed_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanSpeedSpinBox")
        self.bc_pitch_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanPitchSpinBox")
        self.bc_volume_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanVolumeSpinBox")
        self.bc_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "bouyomichanMaxLengthSpinBox")

        # Supertonic 3 ウィジェット
        self.st_speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "sherpaSupertonicSpeedDoubleSpinBox")
        self.st_volume_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "sherpaSupertonicVolumeDoubleSpinBox")
        self.st_max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "sherpaSupertonicMaxLengthSpinBox")
        self.st_download_button: QPushButton = self.dialog_window.findChild(QPushButton, "sherpaSupertonicDownloadButton")

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
        self.placeholder.setStyleSheet("QFrame { border: 2px dashed #3498db; background-color: rgba(52, 152, 219, 20); }")
        self.placeholder.hide()

    def _setup_speaker_menu(self) -> None:
        # プルダウンメニューの初期設定
        self.speakers_data = {}
        self.current_speaker_id = 1
        self.speaker_menu = QMenu(self.dialog_window)
        self.speaker_button.setMenu(self.speaker_menu)
        self.rebuild_speaker_menu()

    def _setup_individual_max_length_spins(self) -> None:
        # 最大文字数スピンボックスの設定 (-1で無制限)
        for spin in [self.vv_max_length_spin, self.coe_max_length_spin, self.bc_max_length_spin, self.st_max_length_spin]:
            if spin:
                spin.setMinimum(-1)
                spin.setSpecialValueText("無制限")
                spin.setMaximum(1000)

    def _bind_popout_widgets(self) -> None:
        # UIからPiP設定ウィジェットを取得
        self.opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "opacitySlider")
        self.opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "opacitySpinBox")
        self.bg_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "bgColorButton")
        self.border_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "borderColorButton")

    def _setup_tts_engine_combo(self) -> None:
        # 音声エンジン選択のバインド
        self.tts_engine_combo: QComboBox = self.dialog_window.findChild(QComboBox, "ttsEngineComboBox")
        if self.tts_engine_combo.findText("BOUYOMICHAN") == -1:
            self.tts_engine_combo.addItem("BOUYOMICHAN")
        if self.tts_engine_combo.findText("SUPERTONIC 3") == -1:
            self.tts_engine_combo.addItem("SUPERTONIC 3")

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
            "sherpa_supertonic": {
                "url": "local://sherpa-supertonic",
                "path": "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
                "speaker_id": 0,
                "speed": 1.0,
                "volume": 1.0,
                "max_length": 50,
            }
        }
        self.current_active_engine = "voicevox"

    def _init_color_state(self) -> None:
        # カラー値の保持
        self.bg_color_hex = ""
        self.border_color_hex = ""

    def _get_engine_key(self, display_name: str) -> str:
        name_lower = display_name.lower()
        if name_lower == "supertonic 3":
            return "sherpa_supertonic"
        return name_lower

    def _get_engine_display_name(self, key: str) -> str:
        if key == "sherpa_supertonic":
            return "SUPERTONIC 3"
        return key.upper()

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
        elif self.current_active_engine == "sherpa_supertonic":
            self.tts_engine_stacked.setCurrentWidget(self.sherpa_supertonic_page)

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        self.api_key_line.setText(self.main_app.config.get("youtube_api_key", env_key))

        # 設定から各エンジン固有のパラメータをロード（旧キーからの移行も兼ねる）
        self.current_active_engine = self.main_app.config.get("tts_engine", "voicevox").lower()

        # VOICEVOX設定の読み込み
        vv_config = self.main_app.config.get("voicevox", {})
        vv = self.engine_settings["voicevox"]
        vv["url"] = vv_config.get("url", "http://127.0.0.1:50021")
        vv["path"] = vv_config.get("path", "")
        vv["speaker_id"] = int(vv_config.get("speaker_id", 1))
        vv["speed"] = float(vv_config.get("speed", 1.0))
        vv["pitch"] = float(vv_config.get("pitch", 0.0))
        vv["intonation"] = float(vv_config.get("intonation", 1.0))
        vv["volume"] = float(vv_config.get("volume", 1.0))
        vv["pause_length"] = float(vv_config.get("pause_length", 1.0))
        vv["pre_phoneme_length"] = float(vv_config.get("pre_phoneme_length", 0.1))
        vv["post_phoneme_length"] = float(vv_config.get("post_phoneme_length", 0.1))
        vv["max_length"] = int(vv_config.get("max_length", 50))

        # COEIROINK設定の読み込み
        coe_config = self.main_app.config.get("coeiroink", {})
        coe = self.engine_settings["coeiroink"]
        coe["url"] = coe_config.get("url", "http://127.0.0.1:50032")
        coe["path"] = coe_config.get("path", "")
        coe["speaker_id"] = int(coe_config.get("speaker_id", 1))
        coe["speed"] = float(coe_config.get("speed", 1.0))
        coe["pitch"] = float(coe_config.get("pitch", 0.0))
        coe["intonation"] = float(coe_config.get("intonation", 1.0))
        coe["volume"] = float(coe_config.get("volume", 1.0))
        coe["pause_length"] = float(coe_config.get("pause_length", 1.0))
        coe["pre_phoneme_length"] = float(coe_config.get("pre_phoneme_length", 0.1))
        coe["post_phoneme_length"] = float(coe_config.get("post_phoneme_length", 0.1))
        coe["max_length"] = int(coe_config.get("max_length", 50))

        # 棒読みちゃん設定の読み込み
        bouyomi_config = self.main_app.config.get("bouyomichan", {})
        bc = self.engine_settings["bouyomichan"]
        bc["url"] = bouyomi_config.get("url", "127.0.0.1:50001")
        bc["path"] = bouyomi_config.get("path", "")
        bc["speaker_id"] = int(bouyomi_config.get("speaker_id", 0))
        bc["speed"] = int(bouyomi_config.get("speed", -1))
        bc["pitch"] = int(bouyomi_config.get("pitch", -1))
        bc["volume"] = int(bouyomi_config.get("volume", -1))
        bc["max_length"] = int(bouyomi_config.get("max_length", 50))

        # Supertonic 3設定の読み込み
        st_config = self.main_app.config.get("sherpa_supertonic", {})
        st = self.engine_settings["sherpa_supertonic"]
        st["url"] = st_config.get("url", "local://sherpa-supertonic")
        st["path"] = st_config.get("path", "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11")
        st["speaker_id"] = int(st_config.get("speaker_id", 0))
        st["speed"] = float(st_config.get("speed", 1.0))
        st["volume"] = float(st_config.get("volume", 1.0))
        st["max_length"] = int(st_config.get("max_length", 50))

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

        # Supertonic 3 ウィジェットへの適用
        self.st_speed_spin.setValue(st["speed"])
        self.st_volume_spin.setValue(st["volume"])
        self.st_max_length_spin.setValue(st["max_length"])

        # 画面のコントロールへ現在アクティブなエンジンの設定値を適用
        self._update_ui_for_active_engine()

        # 音声エンジンの選択状態を復元
        display_name = self._get_engine_display_name(self.current_active_engine)
        idx = self.tts_engine_combo.findText(display_name)
        if idx >= 0:
            self.tts_engine_combo.setCurrentIndex(idx)

        self.skip_history_check.setChecked(bool(self.main_app.config.get("skip_history", True)))
        self.read_super_chat_check.setChecked(bool(self.main_app.config.get("read_super_chat", True)))
        self.check_updates_check.setChecked(bool(self.main_app.config.get("check_updates", True)))
        self.set_read_blocks(self.main_app.config.get("read_blocks"))

        # 読み替え辞書のロード
        self.word_dict = self.main_app.load_all_word_dict_data()

        # グループリストをコンボボックスへ設定
        self._block_group_change_signal = True
        self.group_combo.clear()
        self.group_combo.addItems(list(self.word_dict.keys()))
        
        active_group = self.main_app.config.get("dict_group", "デフォルト")
        if active_group not in self.word_dict:
            active_group = list(self.word_dict.keys())[0] if self.word_dict else ""
        
        self.current_active_group_name = active_group
        if active_group:
            self.group_combo.setCurrentText(active_group)
        self._block_group_change_signal = False

        self.display_words_for_group()

        opacity = int(self.main_app.config.get("comment_opacity", 0.8) * 100)
        self.opacity_slider.setValue(opacity)
        self.opacity_spin.setValue(opacity)

        self.bg_color_hex = self.main_app.config.get("comment_bg_color", "#1e1e1e")
        self.border_color_hex = self.main_app.config.get("comment_border_color", "#3c3c3c")
        self.update_color_button_style(self.bg_color_button, self.bg_color_hex)
        self.update_color_button_style(self.border_color_button, self.border_color_hex)

    def save_settings(self) -> None:
        self.main_app.config["youtube_api_key"] = self.api_key_line.text().strip()

        # 各個別の設定値を画面から取得して engine_settings バッファへ格納
        # VOICEVOX
        self.engine_settings["voicevox"].update({
            "url": self.vv_url_line.text().strip(),
            "path": self.vv_path_line.text().strip(),
            "speaker_id": self.get_current_speaker_id() if self.current_active_engine == "voicevox" else self.engine_settings["voicevox"]["speaker_id"],
            "speed": self.vv_speed_spin.value(),
            "pitch": self.vv_pitch_spin.value(),
            "intonation": self.vv_intonation_spin.value(),
            "volume": self.vv_volume_spin.value(),
            "pause_length": self.vv_pause_spin.value(),
            "pre_phoneme_length": self.vv_pre_phoneme_spin.value(),
            "post_phoneme_length": self.vv_post_phoneme_spin.value(),
            "max_length": self.vv_max_length_spin.value(),
        })
        # COEIROINK
        self.engine_settings["coeiroink"].update({
            "url": self.coe_url_line.text().strip(),
            "path": self.coe_path_line.text().strip(),
            "speaker_id": self.get_current_speaker_id() if self.current_active_engine == "coeiroink" else self.engine_settings["coeiroink"]["speaker_id"],
            "speed": self.coe_speed_spin.value(),
            "pitch": self.coe_pitch_spin.value(),
            "intonation": self.coe_intonation_spin.value(),
            "volume": self.coe_volume_spin.value(),
            "pause_length": self.coe_pause_spin.value(),
            "pre_phoneme_length": self.coe_pre_phoneme_spin.value(),
            "post_phoneme_length": self.coe_post_phoneme_spin.value(),
            "max_length": self.coe_max_length_spin.value(),
        })
        # 棒読みちゃん
        self.engine_settings["bouyomichan"].update({
            "url": self.bc_url_line.text().strip(),
            "path": self.bc_path_line.text().strip(),
            "speaker_id": self.get_current_speaker_id() if self.current_active_engine == "bouyomichan" else self.engine_settings["bouyomichan"]["speaker_id"],
            "speed": self.bc_speed_spin.value(),
            "pitch": self.bc_pitch_spin.value(),
            "volume": self.bc_volume_spin.value(),
            "max_length": self.bc_max_length_spin.value(),
        })
        # Supertonic 3
        self.engine_settings["sherpa_supertonic"].update({
            "speaker_id": self.get_current_speaker_id() if self.current_active_engine == "sherpa_supertonic" else self.engine_settings["sherpa_supertonic"]["speaker_id"],
            "speed": self.st_speed_spin.value(),
            "volume": self.st_volume_spin.value(),
            "max_length": self.st_max_length_spin.value(),
        })

        # config に保存
        self.main_app.config["voicevox"] = self.engine_settings["voicevox"]
        self.main_app.config["coeiroink"] = self.engine_settings["coeiroink"]
        self.main_app.config["bouyomichan"] = self.engine_settings["bouyomichan"]
        self.main_app.config["sherpa_supertonic"] = self.engine_settings["sherpa_supertonic"]

        self.main_app.config["skip_history"] = self.skip_history_check.isChecked()
        self.main_app.config["read_super_chat"] = self.read_super_chat_check.isChecked()
        self.main_app.config["read_blocks"] = self.get_read_blocks()
        self.main_app.config["check_updates"] = self.check_updates_check.isChecked()

        # 読み替え辞書のセーブ
        if self.current_active_group_name:
            self.update_current_group_data_for(self.current_active_group_name)
        
        active_group = self.group_combo.currentText()
        if active_group:
            self.main_app.config["dict_group"] = active_group

        self.main_app.config["comment_opacity"] = self.opacity_slider.value() / 100.0
        self.main_app.config["comment_bg_color"] = self.bg_color_hex
        self.main_app.config["comment_border_color"] = self.border_color_hex
        
        # コンボボックスからキー名を取得して tts_engine に設定
        self.main_app.config["tts_engine"] = self._get_engine_key(self.tts_engine_combo.currentText())
        self.main_app.save_config()

        try:
            dictionary.save_word_dict_data(self.word_dict)
        except Exception as exc:
            QMessageBox.critical(self.dialog_window, "エラー", f"辞書ファイルの保存に失敗しました: {exc}")

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

        # Supertonic 3
        self.st_speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_volume_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.st_max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        
        # ダウンロードボタン
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
        self.bg_color_button.clicked.connect(self.select_bg_color)
        self.border_color_button.clicked.connect(self.select_border_color)
        self.tts_engine_combo.currentTextChanged.connect(self.on_tts_engine_changed)
        self.add_author_block_button.clicked.connect(lambda: self.add_read_block("author"))
        self.add_message_block_button.clicked.connect(lambda: self.add_read_block("message"))
        self.add_text_block_button.clicked.connect(lambda: self.add_read_block("text", ""))

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
        self.read_block_scroll_area.setFixedHeight(
            height + margins.top() + margins.bottom() + frame + scrollbar
        )

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
        button.setStyleSheet(f"background-color: {hex_color}; color: {text_color}; border: 1px solid #555555; font-weight: bold;")

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
            self.dialog_window,
            "音声合成エンジン実行ファイルを選択",
            line_edit.text().strip(),
            filter_str
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
                        lambda checked=False, s_name=speaker_name, st_name=style_name, s_id=style_id: 
                        self.on_style_selected(s_name, st_name, s_id)
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
        engine_type = self._get_engine_key(self.tts_engine_combo.currentText())
        return tts_factory.get_engine_instance(engine_type, url, exe_path)

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
        elif self.current_active_engine == "sherpa_supertonic":
            url = "local://sherpa-supertonic"
        else:
            url = ""

        if not url:
            return False
        try:
            path = (
                self.engine_settings["sherpa_supertonic"]["path"]
                if self.current_active_engine == "sherpa_supertonic"
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
        elif self.current_active_engine == "sherpa_supertonic":
            url = "local://sherpa-supertonic"
            path = self.engine_settings["sherpa_supertonic"]["path"]
        else:
            url = ""
            path = ""

        if not url and self.current_active_engine != "sherpa_supertonic":
            QMessageBox.warning(self.dialog_window, "入力不足", "接続URLを入力してください。")
            return

        engine_type = self._get_engine_key(self.tts_engine_combo.currentText())
        self.main_app.ensure_tts_running(url, path, engine_type)

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
        self.word_table.setRowCount(0)
        
        group_name = self.group_combo.currentText()
        if group_name and group_name in self.word_dict:
            words = self.word_dict[group_name]
            for item in words:
                row = self.word_table.rowCount()
                self.word_table.insertRow(row)
                
                self.word_table.setItem(row, 0, QTableWidgetItem(item.get("reading", "")))
                self.word_table.setItem(row, 1, QTableWidgetItem(item.get("word", "")))
                self.word_table.setItem(row, 2, QTableWidgetItem(item.get("pos", "名詞")))
                self.word_table.setItem(row, 3, QTableWidgetItem(item.get("comment", "")))
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
                word_list.append({
                    "word": word,
                    "reading": reading,
                    "pos": pos,
                    "comment": comment
                })
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
            "JSON Files (*.json);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return
            
        try:
            imported_words = dictionary.load_import_word_list(file_path)
            self.word_table.blockSignals(True)

            for item in imported_words:
                row = self.word_table.rowCount()
                self.word_table.insertRow(row)
                self.word_table.setItem(row, 0, QTableWidgetItem(item.get("reading", "")))
                self.word_table.setItem(row, 1, QTableWidgetItem(item.get("word", "")))
                self.word_table.setItem(row, 2, QTableWidgetItem(item.get("pos", "名詞")))
                self.word_table.setItem(row, 3, QTableWidgetItem(item.get("comment", "")))
            
            self.word_table.blockSignals(False)
            imported_count = len(imported_words)
            if imported_count > 0:
                self.settings_changed.emit()
                QMessageBox.information(self.dialog_window, "インポート", f"{imported_count}件の単語をインポートしました。")
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
            self.dialog_window, "グループ名変更", "新しいグループ名を入力してください:",
            QLineEdit.EchoMode.Normal, current_group
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
            self.dialog_window, "グループ削除",
            f"グループ「{current_group}」を削除しますか？\n登録されている単語リストも削除されます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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

    def download_supertonic_model(self) -> None:
        download_url = (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            "sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2"
        )
        # アーカイブ内のモデルディレクトリを models/ 配下へ展開する
        dest_dir = EXE_DIR / "models"
        
        # 進捗ダイアログの作成
        self.progress_dialog = QProgressDialog("モデルのダウンロード準備中...", "キャンセル", 0, 100, self.dialog_window)
        self.progress_dialog.setWindowTitle("モデルのダウンロード/更新")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True)
        
        # Worker スレッドの作成と開始
        self.download_worker = ModelDownloadWorker(download_url, dest_dir)
        self.download_worker.progress.connect(self.on_download_progress)
        self.download_worker.finished.connect(self.on_download_finished)
        
        # キャンセルボタンが押された時の処理
        self.progress_dialog.canceled.connect(self.download_worker.cancel)
        
        self.download_worker.start()
        self.progress_dialog.exec()

    def on_download_progress(self, percent: int, message: str) -> None:
        if hasattr(self, "progress_dialog") and self.progress_dialog:
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)

    def on_download_finished(self, success: bool, message: str) -> None:
        if hasattr(self, "progress_dialog") and self.progress_dialog:
            self.progress_dialog.close()
            
        if success:
            QMessageBox.information(self.dialog_window, "完了", message)
            model_path_rel = "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11"
            self.engine_settings["sherpa_supertonic"]["path"] = model_path_rel
            self.settings_changed.emit()
        else:
            if "キャンセル" in message:
                QMessageBox.information(self.dialog_window, "キャンセル", message)
            else:
                QMessageBox.critical(self.dialog_window, "エラー", message)
