from dataclasses import dataclass
from enum import StrEnum

from livevoicebridge.core.chat.models import CommentEvent
from livevoicebridge.core.settings.models import AppConfig
from livevoicebridge.core.speech.models import SpeechProgress
from livevoicebridge.core.telemetry.models import ApplicationIssue


class RuntimeState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SessionChanged:
    state: RuntimeState
    connected: bool = False


@dataclass(frozen=True, slots=True)
class CommentReceived:
    comment: CommentEvent


@dataclass(frozen=True, slots=True)
class SettingsApplied:
    config: AppConfig
    revision: int


@dataclass(frozen=True, slots=True)
class LogMessage:
    message: str


@dataclass(frozen=True, slots=True)
class MetricsCollected:
    pass


@dataclass(frozen=True, slots=True)
class MetricCatalogUpdated:
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class UpdateAvailable:
    version: str


@dataclass(frozen=True, slots=True)
class ShutdownCompleted:
    pass


ApplicationEvent = (
    SessionChanged
    | CommentReceived
    | SettingsApplied
    | LogMessage
    | MetricsCollected
    | MetricCatalogUpdated
    | UpdateAvailable
    | ShutdownCompleted
    | ApplicationIssue
    | SpeechProgress
)
