"""Desktop coordinator: bind user intent to services and render core events."""

from collections import OrderedDict
from dataclasses import replace
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from livevoicebridge.core.session.models import (
    LogMessage,
    MetricCatalogUpdated,
    MetricsCollected,
    RuntimeState,
    SessionChanged,
    SettingsApplied,
    ShutdownCompleted,
    UpdateAvailable,
)
from livevoicebridge.core.session.service import SessionService
from livevoicebridge.core.settings.models import ResourceLimits
from livevoicebridge.core.telemetry.models import ApplicationIssue
from livevoicebridge.desktop.comments.avatars import AvatarCache
from livevoicebridge.desktop.comments.delegate import CommentDelegate
from livevoicebridge.desktop.comments.model import CommentListModel, CommentRow
from livevoicebridge.desktop.comments.rendering import (
    COMMENT_LIST_STYLESHEET,
)
from livevoicebridge.desktop.comments.window import CommentWindow
from livevoicebridge.desktop.events import DesktopEvents
from livevoicebridge.desktop.monitoring.popup import fixed_metric_catalog
from livevoicebridge.desktop.rendering.icons import load_svg_icon, render_svg
from livevoicebridge.desktop.resources import (
    PIP_OFF_ICON_FILE,
    PIP_ON_ICON_FILE,
    SETTINGS_ICON_FILE,
    TV_ICON_FILE,
)
from livevoicebridge.desktop.settings.presenter import SettingsPresenter
from livevoicebridge.desktop.settings.view import SettingsDialog
from livevoicebridge.desktop.shell.view import ShellView
from livevoicebridge.desktop.widgets.time import now_text


def _popup_metrics_payload(config):
    return {
        "placement": config.placement,
        "vertical_ratio": config.vertical_ratio,
        "horizontal_ratio": config.horizontal_ratio,
        "display_modes": dict(config.display_modes),
    }


class ShellPresenter(QObject):
    def __init__(self, view: ShellView, session: SessionService, events: DesktopEvents, executable_filter: str):
        super().__init__()
        self.view = view
        self.window = view.window
        self.session = session
        self.events = events
        self._executable_filter = executable_filter
        self._closed = False
        self.comment_window: CommentWindow | None = None
        self.settings_dialog: SettingsDialog | None = None
        self._comment_tab_layout = None
        self._socket_count: int | None = None
        self.latest_youtube_connection_count = 0
        self.metric_catalog = fixed_metric_catalog()
        self._avatar_pending: set[str] = set()
        self._avatar_failures: OrderedDict[str, float] = OrderedDict()
        self._bind_widgets()
        self._setup_comment_list()
        self._setup_toolbar_buttons()
        self.task_manager_widget = view.task_manager
        self._metrics_visibility_pending = False
        self.window.installEventFilter(self)
        self.task_manager_widget.installEventFilter(self)
        self.url_line.setText(self.config.streaming.youtube_source)
        self.set_running_ui(False)
        self.start_button.clicked.connect(lambda: self.session.start(self.url_line.text()))
        self.stop_button.clicked.connect(self.session.stop)
        self.test_comment_button.clicked.connect(self.send_test_comment)
        self.clear_log_button.clicked.connect(self.clear_all_logs)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.popout_button.toggled.connect(self.set_comment_popout)
        self.view.close_requested.connect(self.session.shutdown)
        events.received.connect(self._on_event)
        events.avatar_received.connect(self._on_avatar)
        events.comments_ready.connect(self._schedule_comments)
        events.logs_ready.connect(self._schedule_comments)
        events.progress_ready.connect(self._refresh_progress)
        self._apply_resources(self.config.resources)
        self._refresh_metrics()
        if self.config.presentation.comment_popout:
            self.set_comment_popout(True, persist=False)
        if self.config.application.check_updates:
            self.session.check_updates()
        self._schedule_metrics_request()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in {QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange}:
            self._schedule_metrics_request()
        return False

    def _schedule_metrics_request(self) -> None:
        if not self._metrics_visibility_pending and not self._closed:
            self._metrics_visibility_pending = True
            QTimer.singleShot(0, self._update_metrics_request)

    def _task_metrics_visible(self) -> bool:
        return self.task_manager_widget.isVisible() and not self.window.isMinimized()

    def _popup_metrics_visible(self) -> bool:
        window = self.comment_window
        return window is not None and window.isVisible() and not window.isMinimized()

    def _update_metrics_request(self) -> None:
        self._metrics_visibility_pending = False
        if self._closed:
            return
        if self._task_metrics_visible():
            self.session.set_metrics_request(None)
            self._refresh_metrics()
            return
        identifiers = (
            frozenset(
                key for key, mode in self.comment_window.metrics_panel.display_modes.items() if mode in {"text", "both"}
            )
            if self._popup_metrics_visible() and self.comment_window is not None
            else frozenset()
        )
        self.session.set_metrics_request(identifiers)
        self._refresh_metrics()

    def _merge_metric_catalog(self, entries: tuple[tuple[str, str], ...]) -> None:
        catalog = {item["id"]: item["title"] for item in self.metric_catalog}
        catalog.update(entries)
        updated = [{"id": key, "title": title} for key, title in catalog.items()]
        if updated != self.metric_catalog:
            self.metric_catalog = updated
            if self.settings_dialog is not None:
                self.settings_dialog.presentation.refresh_popup_metric_catalog(updated)

    @property
    def config(self):
        return self.session.settings.current

    def _on_event(self, event):
        if self._closed:
            return
        if isinstance(event, SessionChanged):
            if event.state in {RuntimeState.IDLE, RuntimeState.ERROR}:
                self.task_manager_widget.update_task_info(0, 0, "")
            self.set_running_ui(event.state in {RuntimeState.STARTING, RuntimeState.RUNNING, RuntimeState.STOPPING})
            labels = {
                RuntimeState.IDLE: "停止中",
                RuntimeState.STARTING: "準備中",
                RuntimeState.STOPPING: "終了待ち",
                RuntimeState.ERROR: "エラー",
                RuntimeState.RUNNING: "配信接続中" if event.connected else "テスト読み上げ中",
            }
            self.set_status(labels[event.state])
            self.latest_youtube_connection_count = int(event.connected)
            self.task_manager_widget.update_connection_info(
                event.connected,
                int(event.state is RuntimeState.RUNNING),
                self.config.speech.active_engine,
                self._socket_count,
            )
        elif isinstance(event, MetricsCollected):
            self._refresh_metrics()
        elif isinstance(event, MetricCatalogUpdated):
            self._merge_metric_catalog(event.entries)
        elif isinstance(event, SettingsApplied):
            self._apply_resources(event.config.resources)
            if self.settings_dialog is not None:
                self.settings_dialog.engines.apply_saved(event.config.speech)
            self.url_line.setText(event.config.streaming.youtube_source)
            self._preview_presentation(event.config.presentation)
        elif isinstance(event, ApplicationIssue):
            self.append_log(f"[エラー] {event.message}")
        elif isinstance(event, LogMessage):
            self.append_log(event.message)
        elif isinstance(event, UpdateAvailable):
            self.append_log(f"新しいバージョン {event.version} が利用可能です。")
            if (
                QMessageBox.question(self.window, "更新確認", f"{event.version} の配布ページを開きますか？")
                == QMessageBox.StandardButton.Yes
            ):
                QDesktopServices.openUrl(QUrl("https://github.com/Ikumyon/LiveVoiceBridge/releases"))
        elif isinstance(event, ShutdownCompleted):
            self._closed = True
            self._comment_timer.stop()
            if self.settings_dialog is not None:
                self.settings_dialog.dialog_window.reject()
            self.events.close()
            if self.comment_window is not None:
                self.comment_window.hide()
            self.view.complete_shutdown()

    def _on_avatar(self, url: str, content: bytes) -> None:
        if self._closed:
            return
        self._avatar_pending.discard(url)
        self.avatar_cache.receive(url, content, self.comment_list.devicePixelRatioF())
        if not self.avatar_cache.contains(url):
            self._avatar_failures[url] = monotonic() + 30
            while len(self._avatar_failures) > 256:
                self._avatar_failures.popitem(last=False)

    def _schedule_comments(self) -> None:
        if not self._closed and not self._comment_timer.isActive():
            self._comment_timer.start()

    def _flush_comments(self) -> None:
        if self._closed:
            return
        logs = self.events.take_logs()
        if logs:
            stamp = now_text()
            self.log_text.appendPlainText("\n".join(f"{stamp}  {text}" for text in logs))
        timestamp = now_text()
        rows = [
            CommentRow(
                event.comment.author,
                event.comment.message,
                timestamp,
                event.comment.profile_image_url,
                event.comment.history and self.config.streaming.skip_history,
            )
            for event in self.events.take_comments()
        ]
        self.comment_model.append_batch(rows)
        for row in rows[-self.config.resources.comment_count :]:
            key = row.avatar_key
            if (
                key
                and not self.avatar_cache.contains(key)
                and key not in self._avatar_pending
                and self._avatar_failures.get(key, 0) <= monotonic()
            ):
                self._avatar_pending.add(key)
                self.session.request_avatar(key, self.events.avatar_received.emit)

    def _apply_resources(self, limits: ResourceLimits) -> None:
        self.comment_model.set_limit(limits.comment_count)
        self.events.set_comment_limit(limits.comment_count)
        self.events.set_log_limit(limits.log_lines)
        self.log_text.setMaximumBlockCount(limits.log_lines)
        self.avatar_cache.set_limit(limits.avatar_mib)

    def _refresh_progress(self) -> None:
        progress = self.events.take_progress()
        if progress is not None and not self._closed and self.session.is_current_progress(progress):
            self.task_manager_widget.update_task_info(0, progress.queued, progress.current_text, progress.external)

    def _refresh_metrics(self) -> None:
        self.events.acknowledge_metrics()
        latest = self.session.read_metrics()
        if latest is None:
            return
        frames, sample = latest
        if self._task_metrics_visible():
            self.task_manager_widget.update_metrics(frames)
        if sample is not None and self._task_metrics_visible():
            value = sample.active_sockets.value
            self._socket_count = int(value) if value is not None else None
            self.task_manager_widget.update_connection_info(
                bool(self.latest_youtube_connection_count),
                int(self.session.state is RuntimeState.RUNNING),
                self.config.speech.active_engine,
                self._socket_count,
            )
        self._merge_metric_catalog(tuple((frame.identifier, frame.title) for frame in frames))
        if self._popup_metrics_visible() and self.comment_window is not None:
            self.comment_window.update_metrics(frames)

    def send_test_comment(self):
        text, accepted = QInputDialog.getText(self.window, "テスト送信", "コメント:")
        if accepted and text.strip():
            self.session.test_comment(text)

    def open_settings_dialog(self):
        if self.settings_dialog is not None:
            self.settings_dialog.dialog_window.raise_()
            return
        self.session.begin_settings()
        dialog = SettingsDialog(self.config, self.metric_catalog, self._executable_filter, self.session.plugins)
        SettingsPresenter(dialog, self.session)
        self.settings_dialog = dialog
        self.session.refresh_metric_catalog()
        dialog.settings_changed.connect(lambda: self._preview_dialog(dialog))
        dialog.dialog_window.finished.connect(lambda result: self._finish_settings(dialog, result))
        dialog.dialog_window.open()

    def _preview_dialog(self, dialog):
        if self.comment_window is not None:
            self._preview_presentation(dialog.presentation.read())

    def _finish_settings(self, dialog, result):
        self.settings_dialog = None
        if result != QDialog.DialogCode.Accepted:
            self._preview_presentation(self.config.presentation)
        dialog.dialog_window.deleteLater()
        dialog.deleteLater()

    def _preview_presentation(self, presentation):
        if self.comment_window is not None:
            self.comment_window.presentation = presentation
            self.comment_window.opacity = presentation.comment_opacity
            self.comment_window.header_opacity = presentation.header_opacity
            self.comment_window.border_opacity = presentation.border_opacity
            self.comment_window.apply_metrics_settings(_popup_metrics_payload(presentation.popup_metrics))
            self.comment_window.update()
            self._schedule_metrics_request()

    def _save_presentation(self, presentation):
        self.session.apply_presentation(presentation)

    def set_comment_popout(self, enabled, persist=True):
        presentation = self.config.presentation
        self.popout_button.blockSignals(True)
        self.popout_button.setChecked(enabled)
        self.popout_button.blockSignals(False)
        if enabled:
            self._enable_popout()
        else:
            if self.comment_window is not None:
                geometry = self.comment_window.geometry()
                presentation = replace(
                    presentation,
                    window_x=geometry.x(),
                    window_y=geometry.y(),
                    window_width=geometry.width(),
                    window_height=geometry.height(),
                )
            self._disable_popout()
        if persist:
            self._save_presentation(replace(presentation, comment_popout=enabled))

    def _bind_widgets(self) -> None:
        # ウィジェットのバインド
        self.url_line: QLineEdit = self.window.findChild(QLineEdit, "urlLineEdit")
        self.start_button: QPushButton = self.window.findChild(QPushButton, "startButton")
        self.stop_button: QPushButton = self.window.findChild(QPushButton, "stopButton")
        self.clear_log_button: QPushButton = self.window.findChild(QPushButton, "clearLogButton")
        self.test_comment_button: QPushButton = self.window.findChild(QPushButton, "testCommentButton")
        self.comment_list: QListView = self.window.findChild(QListView, "commentListView")
        self.log_text: QPlainTextEdit = self.window.findChild(QPlainTextEdit, "logTextEdit")
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")
        self.popout_button: QToolButton = self.window.findChild(QToolButton, "popoutButton")
        self.settings_button: QToolButton = self.window.findChild(QToolButton, "settingsButton")
        self._comment_placeholder = self.window.findChild(QWidget, "commentPopoutPlaceholder")
        self._comment_placeholder_icon: QLabel = self.window.findChild(QLabel, "commentPopoutIconLabel")

    def _setup_comment_list(self) -> None:
        self.avatar_cache = AvatarCache(self.config.resources.avatar_mib, self)
        self.comment_model = CommentListModel(self.config.resources.comment_count, self.comment_list)
        self.comment_list.setModel(self.comment_model)
        self.comment_list.setItemDelegate(CommentDelegate(self.avatar_cache, self.comment_list))
        self.avatar_cache.changed.connect(self.comment_model.avatars_changed)
        self._comment_timer = QTimer(self)
        self._comment_timer.setSingleShot(True)
        self._comment_timer.setInterval(50)
        self._comment_timer.timeout.connect(self._flush_comments)
        self.comment_list.setStyleSheet(COMMENT_LIST_STYLESHEET)
        self.comment_list.verticalScrollBar().rangeChanged.connect(self.auto_scroll_to_bottom)

    def _setup_toolbar_buttons(self) -> None:
        # PiPボタン・設定ツールボタンの取得
        if SETTINGS_ICON_FILE.exists():
            self.settings_button.setIcon(load_svg_icon(SETTINGS_ICON_FILE, self.settings_button))
            self.settings_button.setIconSize(QSize(24, 24))

        if PIP_OFF_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_OFF_ICON_FILE, self.popout_button))
            self.popout_button.setText("")
            self.popout_button.setIconSize(QSize(24, 24))

    def auto_scroll_to_bottom(self, min_val: int, max_val: int) -> None:
        bar = self.comment_list.verticalScrollBar()
        current_val = bar.value()
        page_step = bar.pageStep()
        if max_val - current_val < page_step + 100:
            bar.setValue(max_val)

    def clear_all_logs(self) -> None:
        self.log_text.clear()
        self.events.take_logs()
        self.events.take_comments()
        self.comment_model.clear()

    # ------------------------------------------------------------------ PiP --

    def _enable_popout(self) -> None:
        """コメントをPiPウィンドウに移動する。"""
        # コメントタブのレイアウトを取得して保持
        comment_tab = self.window.findChild(QWidget, "commentTab")
        if comment_tab is None:
            return
        self._comment_tab_layout = comment_tab.layout()

        # QListView をタブから取り外す
        if self._comment_tab_layout is not None:
            self._comment_tab_layout.removeWidget(self.comment_list)
            self.comment_list.setParent(None)

        if TV_ICON_FILE.exists():
            self._comment_placeholder_icon.setPixmap(render_svg(TV_ICON_FILE, self.window, 64))
        if self._comment_placeholder is not None:
            self._comment_placeholder.show()

        # PiPボタンのアイコンをオン（無印）状態に変更
        if PIP_ON_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_ON_ICON_FILE, self.popout_button))

        # PiPウィンドウを生成して QListView を渡す
        if self.comment_window is None:
            self.comment_window = CommentWindow(self.config.presentation)
            self.comment_window.installEventFilter(self)
            self.comment_window.popout_closed.connect(lambda: self.set_comment_popout(False))
            self.comment_window.presentation_changed.connect(self._save_presentation)
        presentation = self.config.presentation
        self.comment_window.opacity = presentation.comment_opacity
        self.comment_window.header_opacity = presentation.header_opacity
        self.comment_window.border_opacity = presentation.border_opacity
        self.comment_window.apply_metrics_settings(_popup_metrics_payload(presentation.popup_metrics))
        self.comment_window.attach_list_widget(self.comment_list)

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
            # QListView をウィンドウから取り外す
            self.comment_window.detach_list_widget(self.comment_list)
            self.comment_window.hide()

        # プレースホルダーを削除して QListView をタブに戻す
        if self._comment_placeholder is not None:
            self._comment_placeholder.hide()

        if self._comment_tab_layout is not None:
            self._comment_tab_layout.addWidget(self.comment_list)
            self._comment_tab_layout = None

        # PiPボタンのアイコンをオフ（2）状態に戻す
        if PIP_OFF_ICON_FILE.exists() and self.popout_button is not None:
            self.popout_button.setIcon(load_svg_icon(PIP_OFF_ICON_FILE, self.popout_button))

    def append_log(self, text: str) -> None:
        self.log_text.appendPlainText(
            f"{now_text()}  {text[:16384].encode('utf-8')[:16384].decode('utf-8', errors='ignore')}"
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.append_log(f"[状態] {text}")

    def set_running_ui(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.url_line.setEnabled(not running)
