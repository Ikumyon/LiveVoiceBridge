from __future__ import annotations

import os
import platform
import queue
import sys
from pathlib import Path

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

import json
from PySide6.QtCore import QFile, QObject, QSize, Qt, QUrl, QByteArray
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
    QWidget,
    QHBoxLayout,
    QInputDialog,
)
from PySide6.QtGui import QIcon, QPainter, QPixmap, QPalette, QDesktopServices
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply



from core.app_config import (
    APP_VERSION,
    MAIN_UI_FILE,
    ICON_FILE,
    SETTINGS_ICON_FILE,
    PIP_ICON_FILE,
    PIP_OFF_ICON_FILE,
    PIP_ON_ICON_FILE,
    TV_ICON_FILE,
    CONFIG_FILE,
    DEFAULT_CONFIG,
)
from core.comment_processing import (
    build_read_text,
    normalize_read_blocks,
    parse_comment_into_segments,
)
from core.time_utils import now_text
from core.streaming.youtube.worker import YouTubeChatStreamWorker
from core.workers.speech import SpeechWorker
from core.settings_dialog import SettingsDialog
from core.comment_window import CommentWindow
from core.tts.base import BaseTTSEngine
from core.tts.tools.debug_speech import speak_segments_offline
from core.tts.runtime import ensure_tts_running as ensure_tts_engine_running
from core.ui.helpers import (
    COMMENT_LIST_STYLESHEET,
    clip_to_circle,
    create_comment_item,
    load_svg_icon,
)
import core.tts.factory as tts_factory
import core.dictionary as dictionary


class LiveVoiceBridgeApp(QObject):
    def __init__(self):
        super().__init__()
        self.window = self._load_main_window()

        self.config: dict = {}
        self.load_config()
        self._init_runtime_state()
        self._init_audio_player()
        self._bind_widgets()
        self._setup_comment_list()
        self._setup_network()
        self._setup_toolbar_buttons()
        self._ensure_default_dictionary()
        self._setup_test_comment_button()

        self.load_settings()
        self.connect_signals()
        self.window.destroyed.connect(self.stop_all)
        self._restore_startup_state()

    def _load_main_window(self) -> QWidget:
        loader = QUiLoader()
        ui_file = QFile(str(MAIN_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {MAIN_UI_FILE}")
        self.window = loader.load(ui_file)
        ui_file.close()
        if self.window is None:
            raise RuntimeError("UIファイルの読み込みに失敗しました。")
        return self.window

    def _init_runtime_state(self) -> None:
        self.speech_queue: queue.Queue = queue.Queue()
        self.chat_worker: YouTubeChatStreamWorker | None = None
        self.speech_worker: SpeechWorker | None = None
        self.tts_engine: BaseTTSEngine | None = None
        self.comment_window: CommentWindow | None = None
        self._comment_tab_layout = None
        self._comment_placeholder: QLabel | None = None

        # soundsディレクトリの自動生成
        self.sounds_dir = Path("sounds")
        self.sounds_dir.mkdir(exist_ok=True)

    def _init_audio_player(self) -> None:
        # QMediaPlayerの初期化
        self.player = None
        self.audio_output = None
        if HAS_MULTIMEDIA:
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_output)

    def _bind_widgets(self) -> None:
        # ウィジェットのバインド
        self.url_line: QLineEdit = self.window.findChild(QLineEdit, "urlLineEdit")
        self.start_button: QPushButton = self.window.findChild(QPushButton, "startButton")
        self.stop_button: QPushButton = self.window.findChild(QPushButton, "stopButton")
        self.clear_log_button: QPushButton = self.window.findChild(QPushButton, "clearLogButton")
        self.comment_list: QListWidget = self.window.findChild(QListWidget, "commentListWidget")
        self.log_text: QTextEdit = self.window.findChild(QTextEdit, "logTextEdit")
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")
        self.popout_button: QToolButton = self.window.findChild(QToolButton, "popoutButton")
        self.settings_button: QToolButton = self.window.findChild(QToolButton, "settingsButton")

    def _setup_comment_list(self) -> None:
        self.comment_list.setStyleSheet(COMMENT_LIST_STYLESHEET)
        self.comment_list.verticalScrollBar().rangeChanged.connect(self.auto_scroll_to_bottom)

    def _setup_network(self) -> None:
        # 非同期画像ロード用のマネージャ
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self.on_image_downloaded)

    def _setup_toolbar_buttons(self) -> None:
        # PiPボタン・設定ツールボタンの取得
        if SETTINGS_ICON_FILE.exists():
            self.settings_button.setIcon(load_svg_icon(SETTINGS_ICON_FILE, self.settings_button))
            self.settings_button.setIconSize(QSize(24, 24))

        if PIP_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_ICON_FILE, self.popout_button))
            self.popout_button.setText("")
            self.popout_button.setIconSize(QSize(24, 24))

    def _ensure_default_dictionary(self) -> None:
        # 起動時に辞書ファイルとディレクトリを自動生成
        try:
            dictionary.ensure_default_dictionary()
        except Exception as exc:
            print(f"辞書の初期化失敗: {exc}")

    def _setup_test_comment_button(self) -> None:
        # テスト送信ボタンの動的生成
        self.test_comment_button = QPushButton("テスト送信")
        self.test_comment_button.clicked.connect(self.send_test_comment)
        self.test_comment_button.hide()

        button_layout = self.window.findChild(QHBoxLayout, "buttonLayout")
        if button_layout is not None:
            clear_btn_idx = button_layout.indexOf(self.clear_log_button)
            if clear_btn_idx != -1:
                button_layout.insertWidget(clear_btn_idx + 1, self.test_comment_button)
            else:
                button_layout.addWidget(self.test_comment_button)

    def _restore_startup_state(self) -> None:
        # PiP状態を復元
        if self.config.get("comment_popout", False):
            self.set_comment_popout(True)

        if self.config.get("check_updates", True):
            self.check_updates()

    def check_updates(self) -> None:
        self.append_log("アップデートを確認中...")
        url = QUrl("https://api.github.com/repos/Ikumyon/LiveVoiceBridge/releases/latest")
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"LiveVoiceBridge")
        reply = self.network_manager.get(request)
        reply.finished.connect(lambda: self.on_update_check_finished(reply))

    def on_update_check_finished(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.NoError:
            try:
                data = json.loads(reply.readAll().data().decode("utf-8"))
                latest_version_str = data.get("tag_name", "")
                if not latest_version_str:
                    self.append_log("[情報] アップデートチェック：タグ名が空です。")
                    return
                
                latest_clean = latest_version_str.lstrip("v").strip()
                current_clean = APP_VERSION.lstrip("v").strip()
                
                def parse_ver(v_str: str) -> tuple[int, ...]:
                    try:
                        return tuple(map(int, v_str.split(".")))
                    except ValueError:
                        return (0,)
                
                if parse_ver(latest_clean) > parse_ver(current_clean):
                    self.append_log(f"[情報] 新しいバージョン {latest_version_str} が利用可能です。")
                    reply_btn = QMessageBox.question(
                        self.window,
                        "アップデート確認",
                        f"新しいバージョン ({latest_version_str}) が利用可能です。\nダウンロードページを開きますか？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply_btn == QMessageBox.StandardButton.Yes:
                        QDesktopServices.openUrl(QUrl("https://github.com/Ikumyon/LiveVoiceBridge/releases"))
                else:
                    self.append_log("アプリは最新バージョンです。")
            except Exception as e:
                self.append_log(f"[警告] アップデート情報の解析に失敗しました: {e}")
        else:
            self.append_log(f"[警告] アップデート情報の取得に失敗しました: {reply.errorString()}")
        reply.deleteLater()

    def load_config(self) -> None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.config = DEFAULT_CONFIG.copy()
                    self.config.update(loaded)

                    # 各エンジン固有のマイグレーションを実行
                    tts_factory.migrate_all_configs(self.config, loaded)
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

    def on_image_downloaded(self, reply: QNetworkReply) -> None:
        avatar_label = reply.property("avatar_label")
        if not avatar_label:
            reply.deleteLater()
            return
            
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                clipped_pixmap = clip_to_circle(pixmap, 36)
                avatar_label.setPixmap(clipped_pixmap)
        reply.deleteLater()

    def add_comment_item(self, data: dict) -> None:
        profile_image_url = data.get("profile_image_url", "")
        is_skip = data.get("is_skip", False)

        _, avatar_label = create_comment_item(self.comment_list, data, now_text())
        
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
            words = dictionary.add_word_to_group("配信コメント", word, reading, pos="名詞", comment="コメント追加")
            self.append_log(f"[辞書登録完了] 「{word}」を「{reading}」として登録しました（配信コメントグループ）。")
            
            # メイン設定画面のメモリ上にある辞書も更新
            if hasattr(self, "word_dict") and isinstance(self.word_dict, dict):
                self.word_dict["配信コメント"] = words
 
            # 全辞書データのロードと統合
            merged_list = dictionary.load_merged_word_list()
                
            if self.speech_worker is not None and self.speech_worker.isRunning():
                self.speech_worker.word_list = merged_list
                
        except Exception as exc:
            self.append_log(f"[辞書登録エラー] 辞書の保存または反映に失敗しました: {exc}")
 
    def on_dict_del_requested(self, word: str) -> None:
        try:
            new_words = dictionary.delete_word_from_group("配信コメント", word)
            if new_words is None:
                self.append_log(f"[辞書削除警告] 「{word}」は配信コメントグループに見つかりませんでした。")
                return
                
            self.append_log(f"[辞書削除完了] 「{word}」を辞書から削除しました（配信コメントグループ）。")
            
            # メイン設定画面のメモリ上にある辞書も更新
            if hasattr(self, "word_dict") and isinstance(self.word_dict, dict):
                self.word_dict["配信コメント"] = new_words
 
            # 全辞書データのロードと統合
            merged_list = dictionary.load_merged_word_list()
                
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

        # プレースホルダーを表示 (tv.svg のグラフィック)
        placeholder_widget = QWidget()
        placeholder_layout = QVBoxLayout(placeholder_widget)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel()
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if TV_ICON_FILE.exists():
            try:
                with open(TV_ICON_FILE, "r", encoding="utf-8") as f:
                    svg_content = f.read()
                text_color = self.window.palette().color(QPalette.ColorRole.Text).name()
                modified_svg = svg_content.replace("currentColor", text_color)
                renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
                pixmap = QPixmap(64, 64)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                icon_label.setPixmap(pixmap)
            except Exception:
                icon_label.setText("📺")
        else:
            icon_label.setText("📺")

        text_label = QLabel("別ウィンドウで表示中")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label.setStyleSheet("color: palette(text); font-size: 13px; font-weight: bold; margin-top: 10px;")

        placeholder_layout.addWidget(icon_label)
        placeholder_layout.addWidget(text_label)

        self._comment_placeholder = placeholder_widget
        if self._comment_tab_layout is not None:
            self._comment_tab_layout.addWidget(self._comment_placeholder)

        # PiPボタンのアイコンをオン（無印）状態に変更
        if PIP_ON_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_ON_ICON_FILE, self.popout_button))

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

        # PiPボタンのアイコンをオフ（2）状態に戻す
        if PIP_OFF_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_OFF_ICON_FILE, self.popout_button))

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
        return dictionary.load_all_word_dict_data()
 
    def load_raw_word_dict_data(self) -> dict:
        return dictionary.load_all_word_dict_data()

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
                dictionary.restore_word_dict_data(backup_word_dict_data)
            except Exception as exc:
                print(f"辞書ファイルのロールバック失敗: {exc}")

            self.append_log("設定変更がキャンセルされました。元の設定に戻します。")
            self.restore_settings_to_threads(backup_config, backup_word_dict_data)

    def update_live_settings_from_dialog(self, dialog: SettingsDialog) -> None:
        # ダイアログで操作された最新値をスレッドへ即時反映
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = dialog.skip_history_check.isChecked()
            self.chat_worker.read_super_chat = dialog.read_super_chat_check.isChecked()
            self.chat_worker.max_length = dialog.max_length_spin.value()
            self.chat_worker.read_blocks = dialog.get_read_blocks()

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = dialog.get_current_speaker_id()
            self.speech_worker.speed = dialog.speed_spin.value()
            self.speech_worker.word_list = dialog.get_all_merged_word_list()

        if self.comment_window is not None:
            self.comment_window.opacity = dialog.opacity_slider.value() / 100.0
            self.config["comment_bg_color"] = dialog.bg_color_hex
            self.config["comment_border_color"] = dialog.border_color_hex
            self.comment_window.update()

    def restore_settings_to_threads(self, backup_config: dict, backup_word_dict_data: dict) -> None:
        # スレッドのパラメータをバックアップした元の値に復元
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = backup_config.get("skip_history", True)
            self.chat_worker.read_super_chat = backup_config.get("read_super_chat", True)
            self.chat_worker.max_length = backup_config.get("max_length", 50)
            self.chat_worker.read_blocks = normalize_read_blocks(backup_config.get("read_blocks"))

        if self.speech_worker is not None and self.speech_worker.isRunning():
            engine_type = backup_config.get("tts_engine", "voicevox")
            engine_config = backup_config.get(engine_type, {})
            speaker_id = int(engine_config.get("speaker_id", 1))
            self.speech_worker.speaker_id = speaker_id
            self.speech_worker.speed = float(backup_config.get("speed", 1.0))
            # 全グループの単語をマージして適用
            self.speech_worker.word_list = dictionary.merge_word_dict_data(backup_word_dict_data)

        if self.comment_window is not None:
            self.comment_window.opacity = backup_config.get("comment_opacity", 0.8)
            self.config["comment_bg_color"] = backup_config.get("comment_bg_color", "#1e1e1e")
            self.config["comment_border_color"] = backup_config.get("comment_border_color", "#3c3c3c")
            self.comment_window.update()

    def ensure_tts_running(self, url: str, path: str, engine_type: str | None = None) -> bool:
        if engine_type is None:
            engine_type = self.config.get("tts_engine", "voicevox")

        self.tts_engine, success = ensure_tts_engine_running(
            self.tts_engine,
            url,
            path,
            engine_type,
            self.set_status,
            self.show_error,
            QApplication.processEvents,
        )
        return success

    def start(self) -> None:
        url_or_id = self.url_line.text().strip()
        is_debug = (url_or_id.lower() == "debug")
        api_key = self.config.get("youtube_api_key", "")

        engine_type = self.config.get("tts_engine", "voicevox")
        engine_config = self.config.get(engine_type, {})
        
        engine_class = tts_factory.get_engine_class(engine_type)
        tts_url = engine_config.get("url", engine_class.DEFAULT_URL)
        tts_path = engine_config.get("path", "")
        speaker_id = int(engine_config.get("speaker_id", 1))

        if not url_or_id:
            QMessageBox.warning(self.window, "入力不足", "YouTube URLまたはVideo IDを入力してください。")
            return
        if not is_debug and not api_key:
            QMessageBox.warning(self.window, "設定不足", "YouTube Data API Keyが設定されていません。メニューの ツール->設定 から入力してください。")
            return

        # 起動前にURLを保存
        self.config["youtube_url"] = url_or_id
        self.save_config()

        # 音声合成エンジンの自動起動
        self.ensure_tts_running(tts_url, tts_path, engine_type)

        # すべての辞書ファイルの読み込み・統合
        word_list = []
        try:
            word_list = dictionary.load_merged_word_list()
        except Exception as exc:
            self.append_log(f"[警告] 辞書ファイルの読み込みに失敗しました: {exc}")

        self.speech_queue = queue.Queue()
        self.speech_worker = SpeechWorker(
            speech_queue=self.speech_queue,
            tts_engine=self.tts_engine,
            speaker_id=speaker_id,
            speed=float(self.config.get("speed", 1.0)),
            word_list=word_list,
        )
        self.speech_worker.error.connect(self.show_error)
        self.speech_worker.log.connect(self.append_log)
        self.speech_worker.dict_add_requested.connect(self.on_dict_add_requested)
        self.speech_worker.dict_del_requested.connect(self.on_dict_del_requested)
        self.speech_worker.start()

        if is_debug:
            self.test_comment_button.show()
            self.append_log("デバッグモードで起動しました。")
            self.set_status("デバッグモード稼働中")
            self.set_running_ui(True)
            return

        self.chat_worker = YouTubeChatStreamWorker(
            speech_queue=self.speech_queue,
            youtube_url_or_id=url_or_id,
            api_key=api_key,
            skip_history=bool(self.config.get("skip_history", True)),
            read_super_chat=bool(self.config.get("read_super_chat", True)),
            max_length=int(self.config.get("max_length", 50)),
            read_blocks=self.config.get("read_blocks"),
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

        # 自動起動したTTSプロセスがあれば終了
        if self.tts_engine is not None:
            self.set_status("音声合成エンジンを終了中...")
            QApplication.processEvents()
            self.tts_engine.terminate()

        self.status_label.setText("停止中")
        self.set_running_ui(False)
        self.test_comment_button.hide()

    def on_chat_finished(self) -> None:
        self.append_log("コメント受信を停止しました。")
        self.stop_all()

    def send_test_comment(self) -> None:
        text, ok = QInputDialog.getText(
            self.window, "テスト送信", "読み上げるテキストを入力してください:", text="テストコメントです。"
        )
        if not ok or not text.strip():
            return
            
        dummy_comment = {
            "author": "テストユーザー",
            "message": text.strip(),
            "profile_image_url": "",
            "is_skip": False
        }
        self.add_comment_item(dummy_comment)
        
        # 読み上げ文章の組み立て
        read_text = build_read_text(self.config.get("read_blocks"), "テストユーザー", text.strip())
        segments, play_files = parse_comment_into_segments(read_text)
        if not segments:
            return
            
        if play_files:
            segments[0]["play_file"] = play_files[0]
            
        # 稼働中であれば speech_queue に入れる
        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_queue.put(segments)
        else:
            # 停止中の場合は、必要ならエンジンを立ち上げて一時スレッドで喋らせる
            engine_type = self.config.get("tts_engine", "voicevox").lower()
            engine_config = self.config.get(engine_type, {})
            engine_class = tts_factory.get_engine_class(engine_type)
            tts_url = engine_config.get("url", engine_class.DEFAULT_URL)
            tts_path = engine_config.get("path", "")
            
            # メインスレッドで安全に接続確認/起動を行う
            self.ensure_tts_running(tts_url, tts_path, engine_type)
            
            # 一時読み込みに必要なパラメータを取得
            speaker_id = int(engine_config.get("speaker_id", 1))
            speed = float(self.config.get("speed", 1.0))
            
            word_list = []
            try:
                word_list = dictionary.load_merged_word_list()
            except Exception:
                pass
                
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)
            executor.submit(self._speak_test_comment_offline, segments, speaker_id, speed, word_list)

    def _speak_test_comment_offline(self, segments: list[dict], speaker_id: int, speed: float, word_list: list[dict]) -> None:
        if self.tts_engine is None:
            return
        speak_segments_offline(self.tts_engine, segments, speaker_id, speed, word_list)
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
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    controller = LiveVoiceBridgeApp()
    controller.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
