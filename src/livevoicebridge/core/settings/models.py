from dataclasses import dataclass, field

from livevoicebridge.core.chat.models import StreamingConfig
from livevoicebridge.core.dictionary.models import DictionaryConfig
from livevoicebridge.core.speech.models import SpeechConfig

SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    comment_count: int = 1000
    log_lines: int = 2000
    audio_mib: int = 32
    avatar_mib: int = 8


@dataclass(frozen=True, slots=True)
class PopupMetricsConfig:
    placement: str = "top"
    vertical_ratio: float = 0.35
    horizontal_ratio: float = 0.35
    display_modes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PresentationConfig:
    comment_popout: bool = False
    comment_opacity: float = 0.8
    header_opacity: float = 0.8
    border_opacity: float = 0.8
    background_color: str = "#1e1e1e"
    border_color: str = "#3c3c3c"
    popup_metrics: PopupMetricsConfig = field(default_factory=PopupMetricsConfig)
    window_x: int | None = None
    window_y: int | None = None
    window_width: int = 360
    window_height: int = 500


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    check_updates: bool = True
    use_ime: bool = False


@dataclass(frozen=True, slots=True)
class AppConfig:
    schema_version: int
    streaming: StreamingConfig
    speech: SpeechConfig
    presentation: PresentationConfig
    dictionary: DictionaryConfig = field(default_factory=DictionaryConfig)
    application: ApplicationConfig = field(default_factory=ApplicationConfig)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
