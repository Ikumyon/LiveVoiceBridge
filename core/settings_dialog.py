from __future__ import annotations

import os
import platform
import requests

from PySide6.QtCore import QFile, QObject, QRegularExpression, Signal
from PySide6.QtGui import QAction, QRegularExpressionValidator
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QVBoxLayout,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QInputDialog,
)
import json

from core.workers import SETTINGS_UI_FILE, DICT_DIR, DEFAULT_WORD_LIST

# 循環参照を防ぐためにTYPE_CHECKINGを使用
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import LiveVoiceBridgeApp


class HiraganaDelegate(QStyledItemDelegate):
    """読み列（0列目）をひらがなのみ入力に制限するデリゲート。"""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        # ひらがな・長音符・句読点などを許可する正規表現
        pattern = QRegularExpression("[\u3040-\u309F\u30FC]*")
        validator = QRegularExpressionValidator(pattern, editor)
        editor.setValidator(validator)
        return editor





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
        self.voicevox_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxUrlLineEdit")
        self.speaker_button: QPushButton = self.dialog_window.findChild(QPushButton, "speakerButton")
        self.max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "maxLengthSpinBox")
        self.speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "speedDoubleSpinBox")
        self.skip_history_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_author_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readAuthorCheckBox")
        self.read_super_chat_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.voicevox_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxPathLineEdit")
        self.voicevox_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "voicevoxPathBrowseButton")
        self.test_voicevox_button: QPushButton = self.dialog_window.findChild(QPushButton, "testVoicevoxButton")
        self.button_box: QDialogButtonBox = self.dialog_window.findChild(QDialogButtonBox, "buttonBox")

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

        # プルダウンメニューの初期設定
        self.speakers_data = {}
        self.current_speaker_id = 1
        self.speaker_menu = QMenu(self.dialog_window)
        self.speaker_button.setMenu(self.speaker_menu)
        self.rebuild_speaker_menu()

        self.load_settings()
        self.connect_signals()

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        self.api_key_line.setText(self.main_app.config.get("youtube_api_key", env_key))
        self.voicevox_url_line.setText(self.main_app.config.get("voicevox_url", "http://127.0.0.1:50021"))
        self.voicevox_path_line.setText(self.main_app.config.get("voicevox_path", ""))
        
        speaker_id = int(self.main_app.config.get("speaker_id", 1))
        self.set_speaker_button_id(speaker_id)
        self.update_speakers_from_voicevox()

        self.max_length_spin.setValue(int(self.main_app.config.get("max_length", 50)))
        self.speed_spin.setValue(float(self.main_app.config.get("speed", 1.0)))
        self.skip_history_check.setChecked(bool(self.main_app.config.get("skip_history", True)))
        self.read_author_check.setChecked(bool(self.main_app.config.get("read_author", False)))
        self.read_super_chat_check.setChecked(bool(self.main_app.config.get("read_super_chat", True)))

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

    def save_settings(self) -> None:
        self.main_app.config["youtube_api_key"] = self.api_key_line.text().strip()
        self.main_app.config["voicevox_url"] = self.voicevox_url_line.text().strip()
        self.main_app.config["voicevox_path"] = self.voicevox_path_line.text().strip()
        self.main_app.config["speaker_id"] = self.get_current_speaker_id()
        self.main_app.config["max_length"] = self.max_length_spin.value()
        self.main_app.config["speed"] = self.speed_spin.value()
        self.main_app.config["skip_history"] = self.skip_history_check.isChecked()
        self.main_app.config["read_author"] = self.read_author_check.isChecked()
        self.main_app.config["read_super_chat"] = self.read_super_chat_check.isChecked()

        # 読み替え辞書のセーブ
        if self.current_active_group_name:
            self.update_current_group_data_for(self.current_active_group_name)
        
        active_group = self.group_combo.currentText()
        if active_group:
            self.main_app.config["dict_group"] = active_group

        self.main_app.save_config()

        try:
            DICT_DIR.mkdir(parents=True, exist_ok=True)
            # 現在のメモリ上のグループを個別のJSONファイルに書き出す
            for group_name, words in self.word_dict.items():
                dest_file = DICT_DIR / f"{group_name}.json"
                with open(dest_file, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False, indent=2)
            
            # メモリ上にない（＝削除された）辞書ファイルを物理削除
            for json_file in DICT_DIR.glob("*.json"):
                if json_file.stem not in self.word_dict:
                    try:
                        json_file.unlink()
                    except Exception:
                        pass
        except Exception as exc:
            QMessageBox.critical(self.dialog_window, "エラー", f"辞書ファイルの保存に失敗しました: {exc}")

    def connect_signals(self) -> None:
        self.voicevox_path_browse_button.clicked.connect(self.browse_voicevox_path)
        self.test_voicevox_button.clicked.connect(self.test_voicevox)

        # OK / キャンセルボタン
        self.button_box.accepted.connect(self.accept_settings)
        self.button_box.rejected.connect(self.dialog_window.reject)

        # リアルタイム反映用の変更検知
        self.skip_history_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.read_author_check.stateChanged.connect(lambda _: self.settings_changed.emit())
        self.read_super_chat_check.stateChanged.connect(lambda _: self.settings_changed.emit())
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

    def accept_settings(self) -> None:
        self.save_settings()
        self.dialog_window.accept()

    def browse_voicevox_path(self) -> None:
        system = platform.system()
        filter_str = "Executable Files (*.exe);;All Files (*)" if system == "Windows" else "All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog_window,
            "VOICEVOX 実行ファイルを選択",
            self.voicevox_path_line.text().strip(),
            filter_str
        )
        if file_path:
            self.voicevox_path_line.setText(file_path)

    def rebuild_speaker_menu(self) -> None:
        self.speaker_menu.clear()
        for speaker_name, styles in self.speakers_data.items():
            sub_menu = self.speaker_menu.addMenu(speaker_name)
            for style_name, style_id in styles:
                action = QAction(style_name, self.dialog_window)
                action.setData(style_id)
                action.triggered.connect(
                    lambda checked=False, s_name=speaker_name, st_name=style_name, s_id=style_id: 
                    self.on_style_selected(s_name, st_name, s_id)
                )
                sub_menu.addAction(action)

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

    def update_speakers_from_voicevox(self) -> bool:
        url = self.voicevox_url_line.text().strip().rstrip("/")
        if not url:
            return False
        try:
            response = requests.get(f"{url}/speakers", timeout=2)
            if response.status_code == 200:
                speakers = response.json()
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
            self.main_app.append_log(f"[情報] VOICEVOXからの話者リスト取得スキップ: {exc}")
        return False

    def test_voicevox(self) -> None:
        url = self.voicevox_url_line.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self.dialog_window, "入力不足", "VOICEVOX URLを入力してください。")
            return

        # VOICEVOX起動確認
        self.main_app.ensure_voicevox_running_with_path(
            url, self.voicevox_path_line.text().strip()
        )

        try:
            response = requests.get(f"{url}/speakers", timeout=5)
            response.raise_for_status()
            speakers = response.json()

            # 動的に話者リストを更新
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
                self.main_app.append_log("話者リストをVOICEVOXから更新しました。")

            lines: list[str] = []
            for speaker in speakers[:8]:
                name = speaker.get("name", "?")
                styles = speaker.get("styles", [])
                style_text = ", ".join(f"{s.get('name')}={s.get('id')}" for s in styles[:6])
                lines.append(f"{name}: {style_text}")
            self.main_app.append_log("VOICEVOX接続OK")
            self.main_app.append_log(" / ".join(lines) if lines else "speaker情報なし")
        except Exception as exc:
            self.main_app.show_error(f"VOICEVOXに接続できません: {exc}")

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
