"""Current application runtime, hosted inside the application package."""

from __future__ import annotations

import os
import platform
import queue
import sys
from dataclasses import replace
from pathlib import Path

import psutil

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

import json

from PySide6.QtCore import QByteArray, QFile, QObject, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolButton,
    QWidget,
)

import livevoicebridge.infrastructure.dictionary_repository as dictionary
from livevoicebridge.application.comment_processing import (
    build_read_text,
    parse_comment_into_segments,
)
from livevoicebridge.application.models import (
    AppConfig,
    EngineConfig,
    PopupMetricsConfig,
    ReadBlock,
    ReadBlockKind,
    RuntimeState,
    TtsEngineKind,
    TtsInitializationRequest,
)
from livevoicebridge.application.service import ApplicationService
from livevoicebridge.infrastructure.config_repository import JsonConfigRepository
from livevoicebridge.infrastructure.metrics import MetricsWorker
from livevoicebridge.infrastructure.streaming.youtube import YouTubeChatStreamWorker
from livevoicebridge.infrastructure.tts.base import BaseTTSEngine
from livevoicebridge.infrastructure.tts.debug_speech import speak_segments_offline
from livevoicebridge.infrastructure.tts.registry import (
    TtsEngineRegistry,
    backend_config,
    config_from_backend,
)
from livevoicebridge.paths import (
    APP_VERSION,
    CONFIG_FILE,
    ICON_FILE,
    MAIN_UI_FILE,
    PIP_ICON_FILE,
    PIP_OFF_ICON_FILE,
    PIP_ON_ICON_FILE,
    SETTINGS_ICON_FILE,
    TV_ICON_FILE,
)
from livevoicebridge.presentation.comment_window import CommentWindow
from livevoicebridge.presentation.helpers import (
    COMMENT_LIST_STYLESHEET,
    clip_to_circle,
    create_comment_item,
    load_svg_icon,
)
from livevoicebridge.presentation.popup_metrics import fixed_metric_catalog, metric_catalog_from_data
from livevoicebridge.presentation.settings_dialog import SettingsDialog
from livevoicebridge.presentation.task_manager_widget import TaskManagerWidget
from livevoicebridge.presentation.time_utils import now_text
from livevoicebridge.workers.speech import SpeechWorker


def _read_blocks_payload(blocks: tuple[ReadBlock, ...]) -> list[dict[str, str]]:
    return [
        {"type": block.kind.value, **({"value": block.value} if block.kind is ReadBlockKind.TEXT else {})}
        for block in blocks
    ]


def _popup_metrics_payload(config: PopupMetricsConfig) -> dict[str, object]:
    return {
        "placement": config.placement,
        "vertical_ratio": config.vertical_ratio,
        "horizontal_ratio": config.horizontal_ratio,
        "display_modes": dict(config.display_modes),
    }


class TtsInitializationWorker(QThread):
    def __init__(
        self,
        registry: TtsEngineRegistry,
        config: EngineConfig,
    ):
        super().__init__()
        self.registry = registry
        self.config = config
        self.engine: BaseTTSEngine | None = None
        self.success = False
        self.error = ""

    def run(self) -> None:
        try:
            engine_class = self.registry.engine_class(self.config.kind)
            self.engine = self.registry.create(self.config)

            if self.engine.is_running():
                self.success = True
                return

            if engine_class.REQUIRES_URL and (
                not self.config.executable_path or not os.path.exists(self.config.executable_path)
            ):
                self.error = "実行ファイルのパスが設定されていません。"
                return

            self.success = self.engine.ensure_running()
            self.error = getattr(self.engine, "last_error", "")
        except Exception as exc:
            self.error = str(exc)


# Windows環境における日本語パスの pyopenjtalk 文字化け/初期化エラー問題を回避するセットアップ
if platform.system() == "Windows":
    try:
        import shutil
        import site
        import tempfile

        # pyopenjtalkのアセットがsite-packages内にあるか探す
        site_dirs = site.getsitepackages()
        dict_src = None
        voice_src = None
        for d in site_dirs:
            p_dict = os.path.join(d, "pyopenjtalk", "open_jtalk_dic_utf_8-1.11")
            p_voice = os.path.join(d, "pyopenjtalk", "htsvoice", "mei_normal.htsvoice")
            if os.path.exists(p_dict) and os.path.exists(p_voice):
                dict_src = p_dict
                voice_src = p_voice
                break
        if dict_src and voice_src:
            temp_dir = tempfile.gettempdir()
            dest_dict_dir = os.path.join(temp_dir, "open_jtalk_dic_utf_8-1.11")
            dest_voice_file = os.path.join(temp_dir, "mei_normal.htsvoice")

            if not os.path.exists(dest_dict_dir):
                shutil.copytree(dict_src, dest_dict_dir)
            if not os.path.exists(dest_voice_file):
                shutil.copy2(voice_src, dest_voice_file)

            # 環境変数に設定。これ以降 pyopenjtalk をインポートしたモジュールは、
            # 自動的にこの一時フォルダの辞書を参照するようになります。
            os.environ["OPEN_JTALK_DICT_DIR"] = dest_dict_dir
    except Exception as e:
        print(f"[警告] pyopenjtalkの日本語パス回避設定に失敗しました: {e}")


class LiveVoiceBridgeApp(QObject):
    metric_catalog_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.window = self._load_main_window()

        self.config_repository = JsonConfigRepository(CONFIG_FILE)
        self.tts_registry = TtsEngineRegistry()
        self.config: AppConfig
        self.load_config()
        self.application_service = ApplicationService(self._on_runtime_state_changed)
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
        self._setup_task_manager()
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
        self._stopping_workers: list[QThread] = []
        self.tts_engine: BaseTTSEngine | None = None
        self.tts_init_worker: TtsInitializationWorker | None = None
        self._tts_init_signature: tuple[str, str, str, str] | None = None
        self._tts_ready_signature: tuple[str, str, str, str] | None = None
        self._desired_tts_request: TtsInitializationRequest | None = None
        self._pending_start_request: TtsInitializationRequest | None = None
        self._pending_tts_test_callback = None
        self.comment_window: CommentWindow | None = None
        self._comment_tab_layout = None
        self._comment_placeholder: QLabel | None = None
        self.latest_metrics: dict = {}
        self.latest_youtube_connection_count = 0
        self.metric_catalog = fixed_metric_catalog()

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
        self.test_comment_button: QPushButton = self.window.findChild(QPushButton, "testCommentButton")
        self.comment_list: QListWidget = self.window.findChild(QListWidget, "commentListWidget")
        self.log_text: QTextEdit = self.window.findChild(QTextEdit, "logTextEdit")
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")
        self.popout_button: QToolButton = self.window.findChild(QToolButton, "popoutButton")
        self.settings_button: QToolButton = self.window.findChild(QToolButton, "settingsButton")
        self._comment_placeholder = self.window.findChild(QWidget, "commentPopoutPlaceholder")
        self._comment_placeholder_icon: QLabel = self.window.findChild(QLabel, "commentPopoutIconLabel")

    def _setup_comment_list(self) -> None:
        self.comment_list.setStyleSheet(COMMENT_LIST_STYLESHEET)
        self.comment_list.verticalScrollBar().rangeChanged.connect(self.auto_scroll_to_bottom)

    def _setup_network(self) -> None:
        self.avatar_network_manager = QNetworkAccessManager(self)
        self.avatar_network_manager.finished.connect(self.on_image_downloaded)
        self.update_network_manager = QNetworkAccessManager(self)

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
        self.test_comment_button.clicked.connect(self.send_test_comment)

    def _setup_task_manager(self) -> None:
        """タスクマネージャータブのセットアップとタイマー開始"""
        self.task_manager_tab = self.window.findChild(QWidget, "taskManagerTab")
        if self.task_manager_tab is not None:
            layout = self.task_manager_tab.layout()
            if layout is not None:
                self.task_manager_widget = TaskManagerWidget(self.task_manager_tab)
                layout.addWidget(self.task_manager_widget)

                # バックグラウンド並列スレッドでメトリクス収集
                self.metrics_worker = MetricsWorker(interval_sec=1.0, parent=self)
                self.metrics_worker.metrics_collected.connect(self._on_metrics_collected)
                self.metrics_worker.start()

                # その他の軽量情報更新タイマー (1秒)
                self.task_mgr_timer = QTimer(self)
                self.task_mgr_timer.timeout.connect(self._on_task_mgr_tick)
                self.task_mgr_timer.start(1000)

    def _on_metrics_collected(self, metrics_data: dict) -> None:
        """バックグラウンドスレッドからのメトリクス通知の受領"""
        self.latest_metrics = metrics_data
        catalog = metric_catalog_from_data(metrics_data)
        if catalog != self.metric_catalog:
            self.metric_catalog = catalog
            self.metric_catalog_changed.emit(catalog)
        if hasattr(self, "task_manager_widget") and self.task_manager_widget is not None:
            try:
                self.task_manager_widget.update_metrics(metrics_data)
            except Exception:
                pass
        if self.comment_window is not None:
            self.comment_window.update_metrics(metrics_data)

    def _on_task_mgr_tick(self) -> None:
        """1秒間隔で軽量な接続・タスク情報を更新"""
        if not hasattr(self, "task_manager_widget"):
            return

        # 2. タスクキュー情報更新
        try:
            tts_queue_len = self.speech_queue.qsize() if hasattr(self, "speech_queue") else 0
            comment_queue_len = 0
            current_text = ""
            if hasattr(self, "speech_worker") and self.speech_worker is not None:
                current_text = getattr(self.speech_worker, "current_speech_text", "")

            self.task_manager_widget.update_task_info(comment_queue_len, tts_queue_len, current_text)
        except Exception:
            pass

        # 3. 同時接続数・通信状態更新
        try:
            is_yt_connected = (
                hasattr(self, "chat_worker") and self.chat_worker is not None and self.chat_worker.isRunning()
            )
            tts_engine_name = self.config.speech.active_engine.value

            socket_count = 0
            try:
                proc = psutil.Process()
                socket_count = len(proc.net_connections())
            except Exception:
                socket_count = 0

            active_tts_conn = 1 if (hasattr(self, "tts_engine") and self.tts_engine is not None) else 0

            self.task_manager_widget.update_connection_info(
                is_yt_connected, active_tts_conn, tts_engine_name, socket_count
            )
            self.latest_youtube_connection_count = 1 if is_yt_connected else 0
            if self.comment_window is not None:
                self.comment_window.update_youtube_connections(self.latest_youtube_connection_count)
        except Exception:
            pass

    def _restore_startup_state(self) -> None:
        # PiP状態を復元
        if self.config.presentation.comment_popout:
            self.set_comment_popout(True)

        if self.config.application.check_updates:
            self.check_updates()

        QTimer.singleShot(0, self.prewarm_selected_tts)

    def check_updates(self) -> None:
        self.append_log("アップデートを確認中...")
        url = QUrl("https://api.github.com/repos/Ikumyon/LiveVoiceBridge/releases/latest")
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"LiveVoiceBridge")
        reply = self.update_network_manager.get(request)
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
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
        self.config = self.config_repository.load()

    def save_config(self) -> None:
        self.config_repository.save(self.config)

    def replace_config(self, config: AppConfig) -> None:
        self.config = config
        self.save_config()

    def load_settings(self) -> None:
        self.url_line.setText(self.config.streaming.youtube_source)

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
            reply = self.avatar_network_manager.get(request)
            reply.setProperty("avatar_label", avatar_label)

        # SE再生コマンドの処理
        play_file = data.get("play_file")
        if play_file and not is_skip:
            self.play_sound_file(play_file)

    def play_sound_file(self, filename: str) -> None:
        if not self.player:
            self.append_log("[音声再生エラー] QMediaPlayerが初期化されていません。")
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

        self.config = replace(
            self.config,
            presentation=replace(self.config.presentation, comment_popout=enabled),
        )
        self.save_config()

    def _enable_popout(self) -> None:
        """コメントをPiPウィンドウに移動する。"""
        # コメントタブのレイアウトを取得して保持
        comment_tab = self.window.findChild(QWidget, "commentTab")
        if comment_tab is None:
            return
        self._comment_tab_layout = comment_tab.layout()

        # QListWidget をタブから取り外す
        if self._comment_tab_layout is not None:
            self._comment_tab_layout.removeWidget(self.comment_list)
            self.comment_list.setParent(None)

        if TV_ICON_FILE.exists():
            try:
                with open(TV_ICON_FILE, encoding="utf-8") as f:
                    svg_content = f.read()
                text_color = self.window.palette().color(QPalette.ColorRole.Text).name()
                modified_svg = svg_content.replace("currentColor", text_color)
                renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
                pixmap = QPixmap(64, 64)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                self._comment_placeholder_icon.setPixmap(pixmap)
            except Exception:
                pass
        if self._comment_placeholder is not None:
            self._comment_placeholder.show()

        # PiPボタンのアイコンをオン（無印）状態に変更
        if PIP_ON_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_ON_ICON_FILE, self.popout_button))

        # PiPウィンドウを生成して QListWidget を渡す
        if self.comment_window is None:
            self.comment_window = CommentWindow(self)
        presentation = self.config.presentation
        self.comment_window.opacity = presentation.comment_opacity
        self.comment_window.header_opacity = presentation.header_opacity
        self.comment_window.border_opacity = presentation.border_opacity
        self.comment_window.apply_metrics_settings(_popup_metrics_payload(presentation.popup_metrics))
        self.comment_window.attach_list_widget(self.comment_list)
        if self.latest_metrics:
            self.comment_window.update_metrics(self.latest_metrics)
        self.comment_window.update_youtube_connections(self.latest_youtube_connection_count)

        # 保存済みの位置・サイズがあれば復元
        x = presentation.window_x
        y = presentation.window_y
        w = presentation.window_width
        h = presentation.window_height
        self.comment_window.resize(w, h)
        if x is not None and y is not None:
            self.comment_window.move(x, y)
        self.comment_window.show()

    def _disable_popout(self) -> None:
        """コメントをPiPウィンドウからタブに戻す。"""
        if self.comment_window is not None:
            # ウィンドウの位置・サイズを保存
            geo = self.comment_window.geometry()
            self.config = replace(
                self.config,
                presentation=replace(
                    self.config.presentation,
                    window_x=geo.x(),
                    window_y=geo.y(),
                    window_width=geo.width(),
                    window_height=geo.height(),
                ),
            )

            # QListWidget をウィンドウから取り外す
            self.comment_window.detach_list_widget(self.comment_list)
            self.comment_window.hide()

        # プレースホルダーを削除して QListWidget をタブに戻す
        if self._comment_placeholder is not None:
            self._comment_placeholder.hide()

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

    def _on_runtime_state_changed(self, state: RuntimeState) -> None:
        self.set_running_ui(state in {RuntimeState.STARTING, RuntimeState.RUNNING, RuntimeState.STOPPING})

    def show_error(self, text: str) -> None:
        self.append_log(f"[エラー] {text}")
        QMessageBox.warning(self.window, "LiveVoiceBridge エラー", text)

    def load_all_word_dict_data(self) -> dict[str, list[dict]]:
        return dictionary.load_all_word_dict_data()

    def load_raw_word_dict_data(self) -> dict:
        return dictionary.load_all_word_dict_data()

    def open_settings_dialog(self) -> None:
        backup_config = self.config
        backup_word_dict_data = self.load_raw_word_dict_data()

        dialog = SettingsDialog(self)
        # リアルタイム反映の接続
        dialog.settings_changed.connect(lambda: self.update_live_settings_from_dialog(dialog))

        result = dialog.dialog_window.exec()
        if result == QDialog.Rejected:
            # キャンセルされた場合は設定値をロールバック
            self.config = backup_config

            # 辞書データのロールバック（ファイルの書き戻し）
            try:
                dictionary.restore_word_dict_data(backup_word_dict_data)
            except Exception as exc:
                print(f"辞書ファイルのロールバック失敗: {exc}")

            self.append_log("設定変更がキャンセルされました。元の設定に戻します。")
            self.restore_settings_to_threads(backup_config, backup_word_dict_data)

        if self.speech_worker is None or not self.speech_worker.isRunning():
            self.prewarm_selected_tts()

    def update_live_settings_from_dialog(self, dialog: SettingsDialog) -> None:
        settings = dialog.get_live_settings()
        engine_kind = TtsEngineKind(settings["engine_type"])
        engine = config_from_backend(
            engine_kind,
            settings["engine_config"],
            self.config.speech.engine(engine_kind),
        )
        current_config = backend_config(engine)

        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.reconfigure(
                skip_history=settings["skip_history"],
                read_paid_events=settings["read_super_chat"],
                max_length=engine.max_length,
                read_blocks=settings["read_blocks"],
            )

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.word_list = settings["word_list"]
            signature = TtsInitializationRequest(engine).signature

            if self._tts_ready_signature == signature and self.tts_engine is not None and self.tts_engine.is_running():
                self.speech_worker.reconfigure(
                    self.tts_engine,
                    engine_kind.value,
                    current_config,
                    settings["word_list"],
                )
            else:
                self._request_tts_initialization(
                    TtsInitializationRequest(engine),
                    for_start=False,
                )

        if self.comment_window is not None:
            self.comment_window.opacity = settings["comment_opacity"]
            self.comment_window.header_opacity = settings["comment_header_opacity"]
            self.comment_window.border_opacity = settings["comment_border_opacity"]
            self.comment_window.apply_metrics_settings(settings["popup_metrics"])
            self.comment_window.update()

    def restore_settings_to_threads(self, backup_config: AppConfig, backup_word_dict_data: dict) -> None:
        # スレッドのパラメータをバックアップした元の値に復元
        engine = backup_config.speech.engine()
        engine_config = backend_config(engine)

        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.reconfigure(
                skip_history=backup_config.streaming.skip_history,
                read_paid_events=backup_config.streaming.read_paid_events,
                max_length=engine.max_length,
                read_blocks=_read_blocks_payload(backup_config.speech.read_blocks),
            )

        if self.speech_worker is not None and self.speech_worker.isRunning():
            if self.tts_engine is None:
                raise RuntimeError("稼働中の音声ワーカーに対応するTTSエンジンがありません。")
            self.speech_worker.reconfigure(
                self.tts_engine,
                engine.kind.value,
                engine_config,
                dictionary.merge_word_dict_data(backup_word_dict_data),
            )

        if self.comment_window is not None:
            self.comment_window.opacity = backup_config.presentation.comment_opacity
            self.comment_window.header_opacity = backup_config.presentation.header_opacity
            self.comment_window.border_opacity = backup_config.presentation.border_opacity
            self.comment_window.apply_metrics_settings(_popup_metrics_payload(backup_config.presentation.popup_metrics))
            self.comment_window.update()

    def ensure_tts_running(self, engine: EngineConfig | None = None) -> bool:
        selected = engine or self.config.speech.engine()
        self.tts_engine, success = self.tts_registry.ensure_ready(
            self.tts_engine,
            selected,
            self.set_status,
            self.show_error,
            QApplication.processEvents,
        )
        return success

    def _selected_tts_request(self) -> TtsInitializationRequest:
        return TtsInitializationRequest(self.config.speech.engine())

    def prewarm_selected_tts(self) -> None:
        request = self._selected_tts_request()
        self._request_tts_initialization(request, for_start=False)

    def test_tts_configuration(self, request: dict, callback) -> None:
        self._pending_tts_test_callback = callback
        kind = TtsEngineKind(request["engine_type"])
        engine = config_from_backend(kind, request["engine_config"], self.config.speech.engine(kind))
        self._request_tts_initialization(TtsInitializationRequest(engine), for_start=False)

    def _request_tts_initialization(
        self,
        request: TtsInitializationRequest,
        *,
        for_start: bool,
    ) -> None:
        signature = request.signature
        self._desired_tts_request = request
        if for_start:
            self._pending_start_request = request

        if self.tts_engine is not None and self._tts_ready_signature == signature and self.tts_engine.is_running():
            callback = self._pending_tts_test_callback
            self._pending_tts_test_callback = None
            if callback is not None:
                callback(True, "")
            if for_start:
                self._pending_start_request = None
                self._start_after_tts_ready(request)
            return

        if self.tts_init_worker is not None and self.tts_init_worker.isRunning():
            if for_start:
                self.set_status("音声合成エンジンの準備を待っています...")
                self.set_running_ui(True)
            return

        worker = TtsInitializationWorker(
            self.tts_registry,
            request.engine,
        )
        self.tts_init_worker = worker
        self._tts_init_signature = signature
        worker.finished.connect(self._on_tts_initialization_finished)
        self.append_log(
            f"[情報] {self.tts_registry.display_name(request.engine.kind)}をバックグラウンドで準備しています。"
        )
        if for_start:
            self.set_status("音声合成エンジンを準備しています...")
            self.set_running_ui(True)
        worker.start()

    def _on_tts_initialization_finished(self) -> None:
        worker = self.tts_init_worker
        signature = self._tts_init_signature
        self.tts_init_worker = None
        self._tts_init_signature = None
        if worker is None or signature is None:
            return

        desired = self._desired_tts_request
        if desired is not None and desired.signature != signature:
            if worker.engine is not None:
                worker.engine.terminate()
            self._request_tts_initialization(
                desired,
                for_start=self._pending_start_request is not None,
            )
            return

        if worker.success and worker.engine is not None:
            previous_engine = self.tts_engine
            self.tts_engine = worker.engine
            if self.speech_worker is not None and self.speech_worker.isRunning():
                active_request = self._desired_tts_request
                if active_request is not None and active_request.signature == signature:
                    self.speech_worker.reconfigure(
                        worker.engine,
                        active_request.engine.kind.value,
                        backend_config(active_request.engine),
                        self.speech_worker.word_list,
                    )
            if previous_engine is not None and previous_engine is not worker.engine:
                previous_engine.terminate()
            self._tts_ready_signature = signature
            active_device = getattr(worker.engine, "active_device", "")
            self.append_log(
                f"[情報] {worker.engine.DISPLAY_NAME}の準備が完了しました"
                f"{f' ({active_device})' if active_device else ''}。"
            )

            pending = self._pending_start_request
            callback = self._pending_tts_test_callback
            self._pending_tts_test_callback = None
            if callback is not None:
                callback(True, "")
            if pending is not None and pending.signature == signature:
                self._pending_start_request = None
                self._start_after_tts_ready(pending)
            return

        if worker.engine is not None:
            worker.engine.terminate()
        self._tts_ready_signature = None
        message = (
            f"{self.tts_registry.display_name(TtsEngineKind(request_type))}の初期化に失敗しました。"
            if (request_type := signature[0])
            else "音声合成エンジンの初期化に失敗しました。"
        )
        if worker.error:
            message += f"\n\n詳細: {worker.error}"

        callback = self._pending_tts_test_callback
        self._pending_tts_test_callback = None
        if callback is not None:
            callback(False, worker.error)

        if self._pending_start_request is not None:
            self._pending_start_request = None
            self.application_service.mark_failed()
            self.set_running_ui(False)
            self.set_status("音声合成エンジンの初期化に失敗しました。")
            self.show_error(message)
        else:
            self.append_log(f"[警告] {message}")

    def start(self) -> None:
        url_or_id = self.url_line.text().strip()
        is_debug = url_or_id.lower() == "debug"
        api_key = self.config.streaming.youtube_api_key

        if not url_or_id:
            QMessageBox.warning(self.window, "入力不足", "YouTube URLまたはVideo IDを入力してください。")
            return
        if not is_debug and not api_key:
            QMessageBox.warning(
                self.window,
                "設定不足",
                "YouTube Data API Keyが設定されていません。メニューの ツール->設定 から入力してください。",
            )
            return

        def begin_start() -> None:
            self.config = replace(
                self.config,
                streaming=replace(self.config.streaming, youtube_source=url_or_id),
            )
            self.save_config()
            request = TtsInitializationRequest(
                self.config.speech.engine(),
                stream_source=url_or_id,
                api_key=api_key,
                debug=is_debug,
            )
            self._request_tts_initialization(request, for_start=True)

        self.application_service.connect_stream(begin_start)

    def _start_after_tts_ready(self, request: TtsInitializationRequest) -> None:
        if self.tts_engine is None:
            self.application_service.mark_failed()
            return

        engine = request.engine
        engine_config = backend_config(engine)

        # すべての辞書ファイルの読み込み・統合
        word_list = []
        try:
            word_list = dictionary.load_merged_word_list()
        except Exception as exc:
            self.append_log(f"[警告] 辞書ファイルの読み込みに失敗しました: {exc}")

        # 固有の設定オブジェクト
        self.speech_queue = queue.Queue()
        self.speech_worker = SpeechWorker(
            speech_queue=self.speech_queue,
            tts_engine=self.tts_engine,
            engine_type=engine.kind.value,
            engine_config=engine_config,
            word_list=word_list,
        )
        self.speech_worker.error.connect(self.show_error)
        self.speech_worker.log.connect(self.append_log)
        self.speech_worker.dict_add_requested.connect(self.on_dict_add_requested)
        self.speech_worker.dict_del_requested.connect(self.on_dict_del_requested)
        self.speech_worker.start()

        if request.debug:
            self.test_comment_button.show()
            self.append_log("デバッグモードで起動しました。")
            self.set_status("デバッグモード稼働中")
            self.application_service.mark_running()
            return

        self.chat_worker = YouTubeChatStreamWorker(
            speech_queue=self.speech_queue,
            youtube_url_or_id=request.stream_source,
            api_key=request.api_key,
            skip_history=self.config.streaming.skip_history,
            read_super_chat=self.config.streaming.read_paid_events,
            max_length=engine.max_length,
            read_blocks=_read_blocks_payload(self.config.speech.read_blocks),
        )
        self.chat_worker.comment_received.connect(self.add_comment_item)
        self.chat_worker.status.connect(self.set_status)
        self.chat_worker.error.connect(self.show_error)
        self.chat_worker.finished.connect(self.on_chat_finished)
        self.chat_worker.start()

        self.append_log("開始しました。")
        self.application_service.mark_running()

    def _hold_stopping_worker(self, worker: QThread) -> None:
        if worker.isFinished():
            worker.deleteLater()
            return
        self._stopping_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._release_stopping_worker(w))

    def _release_stopping_worker(self, worker: QThread) -> None:
        if worker in self._stopping_workers:
            self._stopping_workers.remove(worker)
        worker.deleteLater()

    def _stop_worker(self, attr_name: str, wait: bool) -> None:
        worker = getattr(self, attr_name)
        if worker is None:
            return
        setattr(self, attr_name, None)
        worker.stop()
        if wait:
            if not worker.wait(3000):
                worker.terminate()
                worker.wait()
            worker.deleteLater()
        else:
            self._hold_stopping_worker(worker)

    def _stop_components(self, wait: bool = False) -> None:
        self._pending_start_request = None

        self._stop_worker("chat_worker", wait)
        self._stop_worker("speech_worker", wait)

        # ローカルTTSは次回接続に備えてロードしたままにする
        if self.tts_engine is not None and not self.tts_engine.IS_LOCAL_ENGINE:
            self.set_status("音声合成エンジンを終了中...")
            QApplication.processEvents()
            self.tts_engine.terminate()
            self.tts_engine = None
            self._tts_ready_signature = None

        self.status_label.setText("停止中")
        self.test_comment_button.hide()

    def stop_all(self, wait: bool = False) -> None:
        self.application_service.disconnect_stream(lambda: self._stop_components(wait))

    def shutdown(self) -> None:
        self.application_service.shutdown(lambda: self._stop_components(wait=True))
        if self.tts_init_worker is not None and self.tts_init_worker.isRunning():
            self.tts_init_worker.wait()
        if self.tts_engine is not None:
            self.tts_engine.terminate()
            self.tts_engine = None
            self._tts_ready_signature = None
        self.save_config()
        if hasattr(self, "metrics_worker") and self.metrics_worker is not None:
            self.metrics_worker.stop()

    def on_chat_finished(self) -> None:
        self.append_log("コメント受信を停止しました。")
        self.stop_all()

    def send_test_comment(self) -> None:
        text, ok = QInputDialog.getText(
            self.window, "テスト送信", "読み上げるテキストを入力してください:", text="テストコメントです。"
        )
        if not ok or not text.strip():
            return

        dummy_comment = {"author": "テストユーザー", "message": text.strip(), "profile_image_url": "", "is_skip": False}
        self.add_comment_item(dummy_comment)

        # 読み上げ文章の組み立て
        read_text = build_read_text(
            _read_blocks_payload(self.config.speech.read_blocks),
            "テストユーザー",
            text.strip(),
        )
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
            engine = self.config.speech.engine()

            # メインスレッドで安全に接続確認/起動を行う
            self.ensure_tts_running(engine)

            # 一時読み込みに必要なパラメータを取得
            speaker_id = engine.speaker_id
            speed = engine.speed

            word_list = []
            try:
                word_list = dictionary.load_merged_word_list()
            except Exception:
                pass

            from concurrent.futures import ThreadPoolExecutor

            executor = ThreadPoolExecutor(max_workers=1)
            executor.submit(self._speak_test_comment_offline, segments, speaker_id, speed, word_list)

    def _speak_test_comment_offline(
        self, segments: list[dict], speaker_id: int, speed: float, word_list: list[dict]
    ) -> None:
        if self.tts_engine is None:
            return
        speak_segments_offline(self.tts_engine, segments, speaker_id, speed, word_list)
        self.stop_all()

    def show(self) -> None:
        self.window.show()
        # PiPウィンドウが存在すれば一緒に表示
        if self.comment_window is not None and self.config.presentation.comment_popout:
            self.comment_window.show()


def run_application() -> None:
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
    app.aboutToQuit.connect(controller.shutdown)
    controller.show()
    sys.exit(app.exec())
