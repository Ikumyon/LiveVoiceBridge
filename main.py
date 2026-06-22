from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import time
from pathlib import Path

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

import requests
import json
from PySide6.QtCore import QFile, QObject, QSize, Qt, QUrl
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolButton,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
)
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QBrush, QColor, QFont, QPalette
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply



# core.workers から必要なものをインポート
from core.workers import (
    MAIN_UI_FILE,
    SETTINGS_UI_FILE,
    ICON_FILE,
    SETTINGS_ICON_FILE,
    PIP_ICON_FILE,
    SpeechWorker,
    ChatStreamWorker,
    now_text,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    DICT_DIR,
    DEFAULT_WORD_LIST,
)
from core.settings_dialog import SettingsDialog
from core.comment_window import CommentWindow



class LiveVoiceBridgeApp(QObject):
    def __init__(self):
        super().__init__()
        loader = QUiLoader()
        ui_file = QFile(str(MAIN_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {MAIN_UI_FILE}")
        self.window = loader.load(ui_file)
        ui_file.close()
        if self.window is None:
            raise RuntimeError("UIファイルの読み込みに失敗しました。")

        self.config: dict = {}
        self.load_config()
        self.speech_queue: queue.Queue = queue.Queue()
        self.chat_worker: ChatStreamWorker | None = None
        self.speech_worker: SpeechWorker | None = None
        self.voicevox_process: subprocess.Popen | None = None
        self.comment_window: CommentWindow | None = None
        self._comment_tab_layout = None
        self._comment_placeholder: QLabel | None = None

        # soundsディレクトリの自動生成
        self.sounds_dir = Path("sounds")
        self.sounds_dir.mkdir(exist_ok=True)

        # QMediaPlayerの初期化
        self.player = None
        self.audio_output = None
        if HAS_MULTIMEDIA:
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_output)

        # ウィジェットのバインド
        self.url_line: QLineEdit = self.window.findChild(QLineEdit, "urlLineEdit")
        self.start_button: QPushButton = self.window.findChild(QPushButton, "startButton")
        self.stop_button: QPushButton = self.window.findChild(QPushButton, "stopButton")
        self.clear_log_button: QPushButton = self.window.findChild(QPushButton, "clearLogButton")
        self.comment_list: QListWidget = self.window.findChild(QListWidget, "commentListWidget")
        self.comment_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(128, 128, 128, 100);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(128, 128, 128, 180);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: transparent;
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        self.comment_list.verticalScrollBar().rangeChanged.connect(self.auto_scroll_to_bottom)
        
        self.log_text: QTextEdit = self.window.findChild(QTextEdit, "logTextEdit")
        
        # 非同期画像ロード用のマネージャ
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self.on_image_downloaded)
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")

        # PiPボタン・設定ツールボタンの取得
        self.popout_button: QToolButton = self.window.findChild(QToolButton, "popoutButton")
        self.settings_button: QToolButton = self.window.findChild(QToolButton, "settingsButton")

        from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
        from PySide6.QtCore import QSize, QByteArray, Qt

        def _load_svg_icon(svg_path, ref_widget) -> QIcon | None:
            """SVG をテーマカラーに合わせて読み込む。失敗時は None を返す。"""
            try:
                with open(svg_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()
                text_color = ref_widget.palette().color(QPalette.Text).name()
                modified_svg = svg_content.replace("currentColor", text_color)
                renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
                pixmap = QPixmap(24, 24)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                return QIcon(pixmap)
            except Exception:
                return QIcon(str(svg_path))

        if SETTINGS_ICON_FILE.exists():
            self.settings_button.setIcon(_load_svg_icon(SETTINGS_ICON_FILE, self.settings_button))
            self.settings_button.setIconSize(QSize(24, 24))

        if PIP_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(_load_svg_icon(PIP_ICON_FILE, self.popout_button))
            self.popout_button.setText("")
            self.popout_button.setIconSize(QSize(24, 24))

        # 起動時に辞書ファイルとディレクトリを自動生成
        try:
            DICT_DIR.mkdir(parents=True, exist_ok=True)
            json_files = list(DICT_DIR.glob("*.json"))
            if not json_files:
                default_file = DICT_DIR / "デフォルト.json"
                with open(default_file, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_WORD_LIST, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"辞書の初期化失敗: {exc}")

        self.load_settings()
        self.connect_signals()
        self.window.destroyed.connect(self.stop_all)

        # PiP状態を復元
        if self.config.get("comment_popout", False):
            self.set_comment_popout(True)

    def load_config(self) -> None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.config = DEFAULT_CONFIG.copy()
                    self.config.update(loaded)
            else:
                self.config = DEFAULT_CONFIG.copy()
                self.save_config()
        except Exception as exc:
            print(f"設定ファイルのロード失敗: {exc}")
            self.config = DEFAULT_CONFIG.copy()

    def save_config(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"設定ファイルのセーブ失敗: {exc}")

    def load_settings(self) -> None:
        self.url_line.setText(self.config.get("youtube_url", ""))

    def connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop_all)
        self.clear_log_button.clicked.connect(self.clear_all_logs)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        if self.popout_button is not None:
            self.popout_button.toggled.connect(self.set_comment_popout)

    def create_placeholder_avatar(self, initial: str) -> QPixmap:
        pixmap = QPixmap(36, 36)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        palette = self.comment_list.palette()
        bg_color = palette.color(QPalette.Link)
        
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 36, 36)
        
        painter.setPen(QColor(Qt.white))
        font = QFont()
        font.setBold(True)
        font.setPointSize(14)
        painter.setFont(font)
        
        painter.drawText(0, 0, 36, 36, Qt.AlignCenter, initial)
        painter.end()
        return pixmap

    def clip_to_circle(self, pixmap: QPixmap, size: int) -> QPixmap:
        target = QPixmap(size, size)
        target.fill(Qt.transparent)
        
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        scaled_pixmap = pixmap.scaled(
            size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        
        x_offset = (scaled_pixmap.width() - size) // 2
        y_offset = (scaled_pixmap.height() - size) // 2
        cropped_pixmap = scaled_pixmap.copy(x_offset, y_offset, size, size)
        
        brush = QBrush(cropped_pixmap)
        painter.setBrush(brush)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        
        return target

    def on_image_downloaded(self, reply: QNetworkReply) -> None:
        avatar_label = reply.property("avatar_label")
        if not avatar_label:
            reply.deleteLater()
            return
            
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                clipped_pixmap = self.clip_to_circle(pixmap, 36)
                avatar_label.setPixmap(clipped_pixmap)
        reply.deleteLater()

    def add_comment_item(self, data: dict) -> None:
        author = data.get("author", "")
        message = data.get("message", "")
        profile_image_url = data.get("profile_image_url", "")
        is_skip = data.get("is_skip", False)

        item = QListWidgetItem(self.comment_list)
        widget = QWidget()
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        
        avatar_label = QLabel()
        avatar_label.setFixedSize(36, 36)
        initial = author[0] if author else "Anonymous"[0]
        placeholder_pixmap = self.create_placeholder_avatar(initial)
        avatar_label.setPixmap(placeholder_pixmap)
        layout.addWidget(avatar_label)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        
        palette = self.comment_list.palette()
        time_color = palette.color(QPalette.PlaceholderText).name()
        
        time_label = QLabel(f"[{now_text()}]")
        time_label.setStyleSheet(f"color: {time_color}; font-size: 11px;")
        meta_layout.addWidget(time_label)
        
        if is_skip:
            name_color = "#e74c3c"
            name_text = f"[履歴スキップ] {author}"
        else:
            name_color = palette.color(QPalette.Link).name()
            name_text = author

        name_label = QLabel(name_text)
        name_label.setStyleSheet(f"color: {name_color}; font-weight: bold; font-size: 12px;")
        meta_layout.addWidget(name_label)
        meta_layout.addStretch()
        
        text_layout.addLayout(meta_layout)
        
        msg_color = palette.color(QPalette.Text).name() if not is_skip else palette.color(QPalette.PlaceholderText).name()
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"color: {msg_color}; font-size: 12px;")
        text_layout.addWidget(msg_label)
        
        layout.addLayout(text_layout)
        widget.setLayout(layout)
        
        item.setSizeHint(widget.sizeHint())
        self.comment_list.addItem(item)
        self.comment_list.setItemWidget(item, widget)
        
        if profile_image_url:
            request = QNetworkRequest(QUrl(profile_image_url))
            reply = self.network_manager.get(request)
            reply.setProperty("avatar_label", avatar_label)

        # SE再生コマンドの処理
        play_file = data.get("play_file")
        if play_file and not is_skip:
            self.play_sound_file(play_file)

    def play_sound_file(self, filename: str) -> None:
        if not self.player:
            self.append_log(f"[音声再生エラー] QMediaPlayerが初期化されていません。")
            return
        
        safe_name = os.path.basename(filename)
        sound_path = self.sounds_dir / safe_name
        if sound_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(sound_path.absolute())))
            self.player.play()
            self.append_log(f"[音声再生] {safe_name} を再生します。")
        else:
            self.append_log(f"[音声再生警告] {safe_name} が sounds ディレクトリに見つかりません。")

    def on_dict_add_requested(self, word: str, reading: str) -> None:
        try:
            DICT_DIR.mkdir(parents=True, exist_ok=True)
            dict_file = DICT_DIR / "配信コメント.json"
            
            if dict_file.exists():
                with open(dict_file, "r", encoding="utf-8") as f:
                    words = json.load(f)
            else:
                words = []
                
            # 重複防止：既に同じ単語があれば削除
            words = [w for w in words if w.get("word") != word]
            words.append({
                "word": word,
                "reading": reading,
                "pos": "名詞",
                "comment": "コメント追加"
            })
            
            with open(dict_file, "w", encoding="utf-8") as f:
                json.dump(words, f, ensure_ascii=False, indent=2)
                
            self.append_log(f"[辞書登録完了] 「{word}」を「{reading}」として登録しました（配信コメントグループ）。")
            
            # メイン設定画面のメモリ上にある辞書辞書も更新
            if hasattr(self, "word_dict") and isinstance(self.word_dict, dict):
                self.word_dict["配信コメント"] = words

            # 全辞書データのロードと統合
            all_dict = self.load_all_word_dict_data()
            merged_list = []
            for group_words in all_dict.values():
                merged_list.extend(group_words)
                
            if self.speech_worker is not None and self.speech_worker.isRunning():
                self.speech_worker.word_list = merged_list
                
        except Exception as exc:
            self.append_log(f"[辞書登録エラー] 辞書の保存または反映に失敗しました: {exc}")

    def on_dict_del_requested(self, word: str) -> None:
        try:
            DICT_DIR.mkdir(parents=True, exist_ok=True)
            dict_file = DICT_DIR / "配信コメント.json"
            
            if dict_file.exists():
                with open(dict_file, "r", encoding="utf-8") as f:
                    words = json.load(f)
            else:
                words = []
                
            # 単語を削除
            new_words = [w for w in words if w.get("word") != word]
            
            if len(new_words) == len(words):
                self.append_log(f"[辞書削除警告] 「{word}」は配信コメントグループに見つかりませんでした。")
                return
                
            with open(dict_file, "w", encoding="utf-8") as f:
                json.dump(new_words, f, ensure_ascii=False, indent=2)
                
            self.append_log(f"[辞書削除完了] 「{word}」を辞書から削除しました（配信コメントグループ）。")
            
            # メイン設定画面のメモリ上にある辞書も更新
            if hasattr(self, "word_dict") and isinstance(self.word_dict, dict):
                self.word_dict["配信コメント"] = new_words

            # 全辞書データのロードと統合
            all_dict = self.load_all_word_dict_data()
            merged_list = []
            for group_words in all_dict.values():
                merged_list.extend(group_words)
                
            if self.speech_worker is not None and self.speech_worker.isRunning():
                self.speech_worker.word_list = merged_list
                
        except Exception as exc:
            self.append_log(f"[辞書削除エラー] 辞書の保存または反映に失敗しました: {exc}")

    def auto_scroll_to_bottom(self, min_val: int, max_val: int) -> None:
        bar = self.comment_list.verticalScrollBar()
        current_val = bar.value()
        page_step = bar.pageStep()
        if max_val - current_val < page_step + 100:
            bar.setValue(max_val)

    def clear_all_logs(self) -> None:
        self.log_text.clear()
        self.comment_list.clear()

    # ------------------------------------------------------------------ PiP --
    def set_comment_popout(self, enabled: bool) -> None:
        """コメント表示のPiP切り替え。"""
        # ボタンのチェック状態を同期（シグナルの二重発火を防ぐ）
        if self.popout_button is not None:
            self.popout_button.blockSignals(True)
            self.popout_button.setChecked(enabled)
            self.popout_button.blockSignals(False)

        if enabled:
            self._enable_popout()
        else:
            self._disable_popout()

        self.config["comment_popout"] = enabled
        self.save_config()

    def _enable_popout(self) -> None:
        """コメントをPiPウィンドウに移動する。"""
        from PySide6.QtWidgets import QVBoxLayout

        # コメントタブのレイアウトを取得して保持
        comment_tab = self.window.findChild(QWidget, "commentTab")
        if comment_tab is None:
            return
        self._comment_tab_layout = comment_tab.layout()

        # QListWidget をタブから取り外す
        if self._comment_tab_layout is not None:
            self._comment_tab_layout.removeWidget(self.comment_list)
            self.comment_list.setParent(None)

        # プレースホルダーを表示
        self._comment_placeholder = QLabel("📺  別ウィンドウで表示中")
        self._comment_placeholder.setAlignment(Qt.AlignCenter)
        if self._comment_tab_layout is not None:
            self._comment_tab_layout.addWidget(self._comment_placeholder)

        # PiPウィンドウを生成して QListWidget を渡す
        if self.comment_window is None:
            self.comment_window = CommentWindow(self)
        self.comment_window.attach_list_widget(self.comment_list)

        # 保存済みの位置・サイズがあれば復元
        x = self.config.get("comment_win_x")
        y = self.config.get("comment_win_y")
        w = self.config.get("comment_win_w", 360)
        h = self.config.get("comment_win_h", 500)
        self.comment_window.resize(w, h)
        if x is not None and y is not None:
            self.comment_window.move(x, y)
        self.comment_window.show()

    def _disable_popout(self) -> None:
        """コメントをPiPウィンドウからタブに戻す。"""
        if self.comment_window is not None:
            # ウィンドウの位置・サイズを保存
            geo = self.comment_window.geometry()
            self.config["comment_win_x"] = geo.x()
            self.config["comment_win_y"] = geo.y()
            self.config["comment_win_w"] = geo.width()
            self.config["comment_win_h"] = geo.height()

            # QListWidget をウィンドウから取り外す
            self.comment_window.detach_list_widget(self.comment_list)
            self.comment_window.hide()

        # プレースホルダーを削除して QListWidget をタブに戻す
        if self._comment_placeholder is not None:
            if self._comment_tab_layout is not None:
                self._comment_tab_layout.removeWidget(self._comment_placeholder)
            self._comment_placeholder.deleteLater()
            self._comment_placeholder = None

        if self._comment_tab_layout is not None:
            self._comment_tab_layout.addWidget(self.comment_list)
            self._comment_tab_layout = None

    def append_log(self, text: str) -> None:
        self.log_text.append(f"{now_text()}  {text}")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.append_log(f"[状態] {text}")

    def set_running_ui(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.url_line.setEnabled(not running)

    def show_error(self, text: str) -> None:
        self.append_log(f"[エラー] {text}")
        QMessageBox.warning(self.window, "LiveVoiceBridge エラー", text)

    def load_all_word_dict_data(self) -> dict[str, list[dict]]:
        data = {}
        try:
            if DICT_DIR.exists():
                for json_file in DICT_DIR.glob("*.json"):
                    group_name = json_file.stem
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data[group_name] = json.load(f)
                    except Exception as e:
                        print(f"辞書ファイル {json_file.name} のロード失敗: {e}")
        except Exception as e:
            print(f"辞書ディレクトリ走査失敗: {e}")
        
        if not data:
            data["デフォルト"] = DEFAULT_WORD_LIST.copy()
        return data

    def load_raw_word_dict_data(self) -> dict:
        return self.load_all_word_dict_data()

    def open_settings_dialog(self) -> None:
        # ロールバック用に現在の設定をバックアップ
        backup_config = self.config.copy()
        backup_word_dict_data = self.load_raw_word_dict_data()

        dialog = SettingsDialog(self)
        # リアルタイム反映の接続
        dialog.settings_changed.connect(lambda: self.update_live_settings_from_dialog(dialog))

        result = dialog.dialog_window.exec()
        if result == QDialog.Rejected:
            # キャンセルされた場合は設定値をロールバック
            self.config = backup_config
            self.save_config()
            
            # 辞書データのロールバック（ファイルの書き戻し）
            try:
                if DICT_DIR.exists():
                    for json_file in DICT_DIR.glob("*.json"):
                        try:
                            json_file.unlink()
                        except Exception:
                            pass
                for group_name, words in backup_word_dict_data.items():
                    dest_file = DICT_DIR / f"{group_name}.json"
                    with open(dest_file, "w", encoding="utf-8") as f:
                        json.dump(words, f, ensure_ascii=False, indent=2)
            except Exception as exc:
                print(f"辞書ファイルのロールバック失敗: {exc}")

            self.append_log("設定変更がキャンセルされました。元の設定に戻します。")
            self.restore_settings_to_threads(backup_config, backup_word_dict_data)

    def update_live_settings_from_dialog(self, dialog: SettingsDialog) -> None:
        # ダイアログで操作された最新値をスレッドへ即時反映
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = dialog.skip_history_check.isChecked()
            self.chat_worker.read_author = dialog.read_author_check.isChecked()
            self.chat_worker.read_super_chat = dialog.read_super_chat_check.isChecked()
            self.chat_worker.max_length = dialog.max_length_spin.value()

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = dialog.get_current_speaker_id()
            self.speech_worker.speed = dialog.speed_spin.value()
            self.speech_worker.word_list = dialog.get_all_merged_word_list()

    def restore_settings_to_threads(self, backup_config: dict, backup_word_dict_data: dict) -> None:
        # スレッドのパラメータをバックアップした元の値に復元
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = backup_config.get("skip_history", True)
            self.chat_worker.read_author = backup_config.get("read_author", False)
            self.chat_worker.read_super_chat = backup_config.get("read_super_chat", True)
            self.chat_worker.max_length = backup_config.get("max_length", 50)

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = int(backup_config.get("speaker_id", 1))
            self.speech_worker.speed = float(backup_config.get("speed", 1.0))
            # 全グループの単語をマージして適用
            merged_list = []
            for words in backup_word_dict_data.values():
                merged_list.extend(words)
            self.speech_worker.word_list = merged_list

    def ensure_voicevox_running_with_path(self, url: str, path: str) -> bool:
        if not url:
            return False

        # 既に起動しているか確認
        try:
            response = requests.get(f"{url}/speakers", timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass

        # 起動していない場合、パスが指定されていれば起動を試みる
        if not path or not os.path.exists(path):
            return False

        self.set_status("VOICEVOXを起動中...")
        QApplication.processEvents()

        try:
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            
            self.voicevox_process = subprocess.Popen(
                [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
        except Exception as exc:
            self.show_error(f"VOICEVOXの起動に失敗しました: {exc}")
            return False

        # 起動を待つ（最大20秒）
        for _ in range(20):
            if self.voicevox_process.poll() is not None:
                self.show_error("VOICEVOXプロセスが起動直後に終了しました。")
                self.voicevox_process = None
                return False

            try:
                response = requests.get(f"{url}/speakers", timeout=1)
                if response.status_code == 200:
                    self.set_status("VOICEVOXの起動を確認しました。")
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)
            QApplication.processEvents()

        self.show_error("VOICEVOXの起動を確認できませんでした。手動で起動してください。")
        return False

    def start(self) -> None:
        url_or_id = self.url_line.text().strip()
        api_key = self.config.get("youtube_api_key", "")
        voicevox_url = self.config.get("voicevox_url", "http://127.0.0.1:50021")
        voicevox_path = self.config.get("voicevox_path", "")

        if not url_or_id:
            QMessageBox.warning(self.window, "入力不足", "YouTube URLまたはVideo IDを入力してください。")
            return
        if not api_key:
            QMessageBox.warning(self.window, "設定不足", "YouTube Data API Keyが設定されていません。メニューの ツール->設定 から入力してください。")
            return

        # 起動前にURLを保存
        self.config["youtube_url"] = url_or_id
        self.save_config()

        # VOICEVOXの自動起動
        self.ensure_voicevox_running_with_path(voicevox_url, voicevox_path)

        # すべての辞書ファイルの読み込み・統合
        word_list = []
        try:
            all_dict = self.load_all_word_dict_data()
            for words in all_dict.values():
                word_list.extend(words)
        except Exception as exc:
            self.append_log(f"[警告] 辞書ファイルの読み込みに失敗しました: {exc}")

        self.speech_queue = queue.Queue()
        self.speech_worker = SpeechWorker(
            speech_queue=self.speech_queue,
            voicevox_url=voicevox_url,
            speaker_id=int(self.config.get("speaker_id", 1)),
            speed=float(self.config.get("speed", 1.0)),
            word_list=word_list,
        )
        self.speech_worker.error.connect(self.show_error)
        self.speech_worker.dict_add_requested.connect(self.on_dict_add_requested)
        self.speech_worker.dict_del_requested.connect(self.on_dict_del_requested)
        self.speech_worker.start()

        self.chat_worker = ChatStreamWorker(
            speech_queue=self.speech_queue,
            youtube_url_or_id=url_or_id,
            api_key=api_key,
            skip_history=bool(self.config.get("skip_history", True)),
            read_author=bool(self.config.get("read_author", False)),
            read_super_chat=bool(self.config.get("read_super_chat", True)),
            max_length=int(self.config.get("max_length", 50)),
        )
        self.chat_worker.comment_received.connect(self.add_comment_item)
        self.chat_worker.status.connect(self.set_status)
        self.chat_worker.error.connect(self.show_error)
        self.chat_worker.finished.connect(self.on_chat_finished)
        self.chat_worker.start()

        self.append_log("開始しました。")
        self.set_running_ui(True)

    def stop_all(self) -> None:
        if self.chat_worker is not None:
            self.chat_worker.stop()
            # 3秒待機し、終了しなければ強制終了
            if not self.chat_worker.wait(3000):
                self.chat_worker.terminate()
                self.chat_worker.wait()
            self.chat_worker = None

        if self.speech_worker is not None:
            self.speech_worker.stop()
            # 3秒待機し、終了しなければ強制終了
            if not self.speech_worker.wait(3000):
                self.speech_worker.terminate()
                self.speech_worker.wait()
            self.speech_worker = None

        # 自動起動したVOICEVOXプロセスがあれば終了
        if getattr(self, "voicevox_process", None) is not None:
            if self.voicevox_process.poll() is None:
                self.set_status("VOICEVOXを終了中...")
                QApplication.processEvents()
                self.voicevox_process.terminate()
                try:
                    self.voicevox_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.voicevox_process.kill()
            self.voicevox_process = None

        self.status_label.setText("停止中")
        self.set_running_ui(False)

    def on_chat_finished(self) -> None:
        self.append_log("コメント受信を停止しました。")
        self.stop_all()

    def show(self) -> None:
        self.window.show()
        # PiPウィンドウが存在すれば一緒に表示
        if self.comment_window is not None and self.config.get("comment_popout", False):
            self.comment_window.show()


def main() -> None:
    # Windowsのタスクバーでカスタムアイコンを正しく表示させるための設定
    if platform.system() == "Windows":
        import ctypes
        myappid = "Ikumyon.LiveVoiceBridge.App.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QApplication(sys.argv)

    # アプリのアイコンを設定
    if ICON_FILE.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    controller = LiveVoiceBridgeApp()
    controller.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
