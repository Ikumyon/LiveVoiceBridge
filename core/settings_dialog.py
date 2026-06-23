from __future__ import annotations

import os
import platform
import requests

from PySide6.QtCore import QFile, QMimeData, QObject, QPoint, QRegularExpression, Signal, Qt
from PySide6.QtGui import QAction, QDrag, QRegularExpressionValidator, QColor
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
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
)
import json
from pykakasi import kakasi

# pykakasi初期化
_kks = kakasi()

from core.workers import SETTINGS_UI_FILE, DICT_DIR, DEFAULT_WORD_LIST, normalize_read_blocks

# 循環参照を防ぐためにTYPE_CHECKINGを使用
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import LiveVoiceBridgeApp
    from core.tts_engines import BaseTTSEngine
 
import core.dictionary as dictionary
import core.tts_factory as tts_factory


def get_speaker_group(name: str) -> str:
    if not name:
        return "その他"
    
    # 主要キャラクターの「行」を優先適用
    known_speakers = {
        "四国めたん": "さ行",
        "ずんだもん": "さ行",
        "春日部つむぎ": "か行",
        "雨晴はう": "あ行",
        "波音リツ": "は行",
        "玄野武宏": "か行",
        "白上虎太郎": "さ行",
        "青山龍星": "あ行",
        "冥鳴ひまり": "ま行",
        "九州そら": "か行",
        "もち子さん": "ま行",
        "剣崎めすの": "か行", # けんざき
    }
    
    # 漢字表記と行の簡易辞書
    if name in known_speakers:
        return known_speakers[name]

    # pykakasi でひらがなに変換
    result = _kks.convert(name)
    hira_name = "".join([item['hira'] for item in result])
    if not hira_name:
        return "その他"
        
    first_char = hira_name[0]
    
    # 五十音行の判定
    if first_char in "あいうえおぁぃぅぇぉ": return "あ行"
    if first_char in "かきくけこがぎぐげご": return "か行"
    if first_char in "さしすせそざじずぜぞ": return "さ行"
    if first_char in "たちつてとだぢづでどっ": return "た行"
    if first_char in "なにぬねの": return "な行"
    if first_char in "はひふへほばびぶべぼぱぴぷぺぽ": return "は行"
    if first_char in "まみむめも": return "ま行"
    if first_char in "やゆよゃゅょ": return "や行"
    if first_char in "らりるれろ": return "ら行"
    if first_char in "わをんゐゑ": return "わ行"
    
    return "その他"


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

        # UIファイルの読み込み
        loader = QUiLoader()
        ui_file = QFile(str(SETTINGS_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {SETTINGS_UI_FILE}")
        self.dialog_window = loader.load(ui_file)
        ui_file.close()

        # ウィジェットのバインド
        self.api_key_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "apiKeyLineEdit")
        self.tts_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "ttsUrlLineEdit")
        self.speaker_button: QPushButton = self.dialog_window.findChild(QPushButton, "speakerButton")
        self.max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "maxLengthSpinBox")
        self.speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "speedDoubleSpinBox")
        self.skip_history_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_super_chat_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.check_updates_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "checkUpdatesCheckBox")
        self.tts_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "ttsPathLineEdit")
        self.tts_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "ttsPathBrowseButton")
        self.tts_test_button: QPushButton = self.dialog_window.findChild(QPushButton, "ttsTestButton")
        self.button_box: QDialogButtonBox = self.dialog_window.findChild(QDialogButtonBox, "buttonBox")
        self.read_block_scroll_area: QScrollArea = self.dialog_window.findChild(QScrollArea, "readBlockScrollArea")
        self.read_block_container: QWidget = self.dialog_window.findChild(QWidget, "readBlockScrollContent")
        self.read_block_layout: QHBoxLayout = self.dialog_window.findChild(QHBoxLayout, "readBlockHBoxLayout")
        self.read_block_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.add_author_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addAuthorBlockButton")
        self.add_message_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addMessageBlockButton")
        self.add_text_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addTextBlockButton")
        self._read_block_next_id = 1

        # 読み替え辞書UIのバインド
        self.word_table: QTableWidget = self.dialog_window.findChild(QTableWidget, "wordTableWidget")
        self.add_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "addWordButton")
        self.delete_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteWordButton")
        self.import_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "importWordButton")
        self.group_combo: QComboBox = self.dialog_window.findChild(QComboBox, "dictionaryGroupComboBox")
        self.add_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "addGroupButton")
        self.rename_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "renameGroupButton")
        self.delete_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteGroupButton")

        # テーブル設定
        self.word_table.setColumnCount(4)
        self.word_table.setHorizontalHeaderLabels(["読み", "単語", "品詞", "コメント"])
        self.word_table.horizontalHeader().setStretchLastSection(True)
        # 読み列（0列目）をひらがな限定に制限
        self.word_table.setItemDelegateForColumn(0, HiraganaDelegate(self.word_table))

        self.word_dict = {}
        self.current_active_group_name = ""
        self._block_group_change_signal = False

        self.placeholder = PlaceholderFrame(self)
        self.placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.placeholder.setStyleSheet("QFrame { border: 2px dashed #3498db; background-color: rgba(52, 152, 219, 20); }")
        self.placeholder.hide()

        # プルダウンメニューの初期設定
        self.speakers_data = {}
        self.current_speaker_id = 1
        self.speaker_menu = QMenu(self.dialog_window)
        self.speaker_button.setMenu(self.speaker_menu)
        self.rebuild_speaker_menu()

        # 最大文字数スピンボックスの設定 (-1で無制限)
        self.max_length_spin.setMinimum(-1)
        self.max_length_spin.setSpecialValueText("無制限")
        self.max_length_spin.setMaximum(1000)

        # UIからPiP設定ウィジェットを取得
        self.opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "opacitySlider")
        self.opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "opacitySpinBox")
        self.bg_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "bgColorButton")
        self.border_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "borderColorButton")

        # 音声エンジン選択のバインド
        self.tts_engine_combo: QComboBox = self.dialog_window.findChild(QComboBox, "ttsEngineComboBox")
        if self.tts_engine_combo.findText("BOUYOMICHAN") == -1:
            self.tts_engine_combo.addItem("BOUYOMICHAN")

        # 各エンジン用の一時設定バッファ
        self.engine_settings = {
            "voicevox": {"url": "http://127.0.0.1:50021", "path": "", "speaker_id": 1},
            "coeiroink": {"url": "http://127.0.0.1:50032", "path": "", "speaker_id": 1},
            "bouyomichan": {"url": "127.0.0.1:50001", "path": "", "speaker_id": 0}
        }
        self.current_active_engine = "voicevox"

        # カラー値の保持
        self.bg_color_hex = ""
        self.border_color_hex = ""

        self.load_settings()
        self.connect_signals()

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        self.api_key_line.setText(self.main_app.config.get("youtube_api_key", env_key))

        # 設定から各エンジン固有のパラメータをロード（旧キーからの移行も兼ねる）
        self.current_active_engine = self.main_app.config.get("tts_engine", "voicevox").lower()

        # VOICEVOX設定の読み込み
        vv_config = self.main_app.config.get("voicevox", {})
        self.engine_settings["voicevox"]["url"] = vv_config.get("url", "http://127.0.0.1:50021")
        self.engine_settings["voicevox"]["path"] = vv_config.get("path", "")
        self.engine_settings["voicevox"]["speaker_id"] = int(vv_config.get("speaker_id", 1))

        # COEIROINK設定の読み込み
        coe_config = self.main_app.config.get("coeiroink", {})
        self.engine_settings["coeiroink"]["url"] = coe_config.get("url", "http://127.0.0.1:50032")
        self.engine_settings["coeiroink"]["path"] = coe_config.get("path", "")
        self.engine_settings["coeiroink"]["speaker_id"] = int(coe_config.get("speaker_id", 1))

        # 棒読みちゃん設定の読み込み
        bouyomi_config = self.main_app.config.get("bouyomichan", {})
        self.engine_settings["bouyomichan"]["url"] = bouyomi_config.get("url", "127.0.0.1:50001")
        self.engine_settings["bouyomichan"]["path"] = bouyomi_config.get("path", "")
        self.engine_settings["bouyomichan"]["speaker_id"] = int(bouyomi_config.get("speaker_id", 0))

        # 画面のコントロールへ現在アクティブなエンジンの設定値を適用
        active_config = self.engine_settings[self.current_active_engine]
        self.tts_url_line.setText(active_config["url"])
        self.tts_path_line.setText(active_config["path"])
        
        self.current_speaker_id = active_config["speaker_id"]
        self.set_speaker_button_id(self.current_speaker_id)
        self.update_speakers_from_engine()

        self.max_length_spin.setValue(int(self.main_app.config.get("max_length", 50)))
        self.speed_spin.setValue(float(self.main_app.config.get("speed", 1.0)))
        
        # 音声エンジンの選択状態を復元
        idx = self.tts_engine_combo.findText(self.current_active_engine.upper())
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

        # 現在画面に入力されている内容を、現在アクティブなエンジンのバッファへ退避
        self.engine_settings[self.current_active_engine] = {
            "url": self.tts_url_line.text().strip(),
            "path": self.tts_path_line.text().strip(),
            "speaker_id": self.get_current_speaker_id()
        }

        # 各エンジンのネストされた設定値を config に保存
        self.main_app.config["voicevox"] = self.engine_settings["voicevox"]
        self.main_app.config["coeiroink"] = self.engine_settings["coeiroink"]
        self.main_app.config["bouyomichan"] = self.engine_settings["bouyomichan"]

        self.main_app.config["max_length"] = self.max_length_spin.value()
        self.main_app.config["speed"] = self.speed_spin.value()
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
        self.main_app.config["tts_engine"] = self.tts_engine_combo.currentText().lower()
        self.main_app.save_config()

        try:
            dictionary.save_word_dict_data(self.word_dict)
        except Exception as exc:
            QMessageBox.critical(self.dialog_window, "エラー", f"辞書ファイルの保存に失敗しました: {exc}")

    def connect_signals(self) -> None:
        self.tts_path_browse_button.clicked.connect(self.browse_tts_path)
        self.tts_test_button.clicked.connect(self.test_tts_connection)

        # OK / キャンセルボタン
        self.button_box.accepted.connect(self.accept_settings)
        self.button_box.rejected.connect(self.dialog_window.reject)

        # リアルタイム反映用の変更検知
        self.skip_history_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.read_super_chat_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.check_updates_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.speed_spin.valueChanged.connect(lambda _: self.settings_changed.emit())
        self.max_length_spin.valueChanged.connect(lambda _: self.settings_changed.emit())

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
        new_engine = engine_name.lower()
        if new_engine == self.current_active_engine:
            return

        # 1. 現在画面に表示されている設定を、現在のアクティブエンジン（旧エンジン）のバッファへ退避
        self.engine_settings[self.current_active_engine] = {
            "url": self.tts_url_line.text().strip(),
            "path": self.tts_path_line.text().strip(),
            "speaker_id": self.get_current_speaker_id()
        }

        # 2. 現在アクティブなエンジンを新しいものに更新
        self.current_active_engine = new_engine

        # 3. 新しいエンジンのパラメータを画面へロードする
        active_config = self.engine_settings[new_engine]
        self.tts_url_line.setText(active_config["url"])
        self.tts_path_line.setText(active_config["path"])
        
        self.current_speaker_id = active_config["speaker_id"]
        self.set_speaker_button_id(self.current_speaker_id)
        
        # 新しいエンジンのURL/パスを基に、話者リストを自動で更新・メニュー構築する
        self.update_speakers_from_engine()

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

    def browse_tts_path(self) -> None:
        system = platform.system()
        filter_str = "Executable Files (*.exe);;All Files (*)" if system == "Windows" else "All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog_window,
            "音声合成エンジン実行ファイルを選択",
            self.tts_path_line.text().strip(),
            filter_str
        )
        if file_path:
            self.tts_path_line.setText(file_path)

    def rebuild_speaker_menu(self) -> None:
        self.speaker_menu.clear()

        # 五十音順のグループ順序
        group_order = ["あ行", "か行", "さ行", "た行", "な行", "は行", "ま行", "や行", "ら行", "わ行", "その他"]

        # キャラクターをグループごとに分類
        grouped_speakers = {g: {} for g in group_order}

        for speaker_name, styles in self.speakers_data.items():
            group = get_speaker_group(speaker_name)
            if group not in grouped_speakers:
                group = "その他"
            grouped_speakers[group][speaker_name] = styles

        # グループごとにメニューを作成
        for group_name in group_order:
            speakers_in_group = grouped_speakers[group_name]
            if not speakers_in_group:
                continue

            # 五十音グループのサブメニューを作成 (例: "あ行")
            group_menu = self.speaker_menu.addMenu(group_name)

            # キャラクター名をフリガナ順にソート
            def get_sort_key(name):
                res = _kks.convert(name)
                return "".join([x['hira'] for x in res])

            sorted_speakers = sorted(speakers_in_group.keys(), key=get_sort_key)

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
        engine_type = self.tts_engine_combo.currentText().lower()
        return tts_factory.get_engine_instance(engine_type, url, exe_path)

    def update_speakers_from_engine(self) -> bool:
        url = self.tts_url_line.text().strip().rstrip("/")
        if not url:
            return False
        try:
            engine = self.get_engine_instance(url, "")
            speakers = engine.get_speakers()
            if speakers:
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
                
                if new_data:
                    self.speakers_data = new_data
                    self.rebuild_speaker_menu()
                    self.set_speaker_button_id(self.current_speaker_id)
                    return True
        except Exception as exc:
            self.main_app.append_log(f"[情報] 話者リスト取得スキップ: {exc}")
        return False

    def test_tts_connection(self) -> None:
        url = self.tts_url_line.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self.dialog_window, "入力不足", "接続URLを入力してください。")
            return

        engine_type = self.tts_engine_combo.currentText().lower()
        self.main_app.ensure_tts_running(
            url, self.tts_path_line.text().strip(), engine_type
        )

        try:
            engine = self.get_engine_instance(url, "")
            speakers = engine.get_speakers()
            if not speakers:
                raise RuntimeError("話者情報が取得できませんでした。")

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
            
            if new_data:
                self.speakers_data = new_data
                self.rebuild_speaker_menu()
                self.set_speaker_button_id(self.current_speaker_id)
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
            imported_count = 0
            self.word_table.blockSignals(True)
            
            if file_path.endswith(".json"):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    for item in data:
                        row = self.word_table.rowCount()
                        self.word_table.insertRow(row)
                        self.word_table.setItem(row, 0, QTableWidgetItem(item.get("reading", "")))
                        self.word_table.setItem(row, 1, QTableWidgetItem(item.get("word", "")))
                        self.word_table.setItem(row, 2, QTableWidgetItem(item.get("pos", "名詞")))
                        self.word_table.setItem(row, 3, QTableWidgetItem(item.get("comment", "")))
                        imported_count += 1
                elif isinstance(data, dict):
                    for k, v in data.items():
                        row = self.word_table.rowCount()
                        self.word_table.insertRow(row)
                        self.word_table.setItem(row, 0, QTableWidgetItem(str(v)))
                        self.word_table.setItem(row, 1, QTableWidgetItem(str(k)))
                        self.word_table.setItem(row, 2, QTableWidgetItem("名詞"))
                        self.word_table.setItem(row, 3, QTableWidgetItem(""))
                        imported_count += 1
                        
            elif file_path.endswith(".csv"):
                import csv
                with open(file_path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row_data in reader:
                        if not row_data:
                            continue
                        row = self.word_table.rowCount()
                        self.word_table.insertRow(row)
                        
                        reading = row_data[0] if len(row_data) > 0 else ""
                        word = row_data[1] if len(row_data) > 1 else ""
                        pos = row_data[2] if len(row_data) > 2 else "名詞"
                        comment = row_data[3] if len(row_data) > 3 else ""
                        
                        self.word_table.setItem(row, 0, QTableWidgetItem(reading))
                        self.word_table.setItem(row, 1, QTableWidgetItem(word))
                        self.word_table.setItem(row, 2, QTableWidgetItem(pos))
                        self.word_table.setItem(row, 3, QTableWidgetItem(comment))
                        imported_count += 1

            elif file_path.endswith(".txt"):
                # IME辞書形式 (TAB区切りテキスト)。エンコードの自動判別。
                encoding = "shift_jis"
                for enc in ["shift_jis", "utf-16", "utf-8"]:
                    try:
                        with open(file_path, "r", encoding=enc) as f:
                            f.readline()
                        encoding = enc
                        break
                    except Exception:
                        continue
                
                with open(file_path, "r", encoding=encoding, errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("!") or line.startswith("#"):
                            continue
                        
                        row_data = line.split("\t")
                        if len(row_data) >= 2:
                            row = self.word_table.rowCount()
                            self.word_table.insertRow(row)
                            
                            reading = row_data[0].strip()
                            word = row_data[1].strip()
                            pos = row_data[2].strip() if len(row_data) > 2 else "名詞"
                            comment = row_data[3].strip() if len(row_data) > 3 else ""
                            
                            self.word_table.setItem(row, 0, QTableWidgetItem(reading))
                            self.word_table.setItem(row, 1, QTableWidgetItem(word))
                            self.word_table.setItem(row, 2, QTableWidgetItem(pos))
                            self.word_table.setItem(row, 3, QTableWidgetItem(comment))
                            imported_count += 1
            
            self.word_table.blockSignals(False)
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
