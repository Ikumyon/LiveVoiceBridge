from collections import deque
from threading import Lock

from PySide6.QtCore import QObject, Signal

from livevoicebridge.core.session.models import ApplicationEvent, CommentReceived, LogMessage, MetricsCollected
from livevoicebridge.core.speech.models import SpeechProgress
from livevoicebridge.core.telemetry.models import ApplicationIssue


class DesktopEvents(QObject):
    received = Signal(object)
    comments_ready = Signal()
    logs_ready = Signal()
    progress_ready = Signal()
    avatar_received = Signal(str, bytes)

    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._metrics_pending = False
        self._comments: deque[CommentReceived] = deque(maxlen=1000)
        self._comments_pending = False
        self._logs: deque[str] = deque(maxlen=2000)
        self._logs_pending = False
        self._progress: SpeechProgress | None = None
        self._closed = False

    def publish(self, event: ApplicationEvent) -> None:
        if self._closed:
            return
        if isinstance(event, (LogMessage, ApplicationIssue)):
            text = ("[エラー] " if isinstance(event, ApplicationIssue) else "") + event.message
            text = text[:16384].encode("utf-8")[:16384].decode("utf-8", errors="ignore")
            with self._lock:
                self._logs.append(text)
                notify = not self._logs_pending
                self._logs_pending = True
            if notify:
                self.logs_ready.emit()
            return
        if isinstance(event, SpeechProgress):
            with self._lock:
                notify = self._progress is None
                self._progress = event
            if notify:
                self.progress_ready.emit()
            return
        if isinstance(event, CommentReceived):
            with self._lock:
                self._comments.append(event)
                notify = not self._comments_pending
                self._comments_pending = True
            if notify:
                self.comments_ready.emit()
            return
        if isinstance(event, MetricsCollected):
            with self._lock:
                if self._metrics_pending:
                    return
                self._metrics_pending = True
        self.received.emit(event)

    def acknowledge_metrics(self) -> None:
        with self._lock:
            self._metrics_pending = False

    def take_comments(self) -> tuple[CommentReceived, ...]:
        with self._lock:
            rows = tuple(self._comments)
            self._comments.clear()
            self._comments_pending = False
            return rows

    def set_comment_limit(self, count: int) -> None:
        with self._lock:
            self._comments = deque(self._comments, maxlen=count)

    def take_logs(self) -> tuple[str, ...]:
        with self._lock:
            logs = tuple(self._logs)
            self._logs.clear()
            self._logs_pending = False
            return logs

    def take_progress(self) -> SpeechProgress | None:
        with self._lock:
            progress, self._progress = self._progress, None
            return progress

    def set_log_limit(self, count: int) -> None:
        with self._lock:
            self._logs = deque(self._logs, maxlen=count)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._comments.clear()
            self._logs.clear()
            self._progress = None
