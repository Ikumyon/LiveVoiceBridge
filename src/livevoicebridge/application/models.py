"""Typed values exchanged by application services and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

APP_NAME = "LiveVoiceBridge"


class RuntimeState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class TtsEngineKind(StrEnum):
    VOICEVOX = "voicevox"
    COEIROINK = "coeiroink"
    BOUYOMICHAN = "bouyomichan"
    SUPERTONIC_LIGHTWEIGHT = "supertonic_lightweight"
    SUPERTONIC = "supertonic"


class ReadBlockKind(StrEnum):
    AUTHOR = "author"
    MESSAGE = "message"
    TEXT = "text"


class SpeechAction(StrEnum):
    ADD_DICTIONARY = "add_dict"
    DELETE_DICTIONARY = "del_dict"


class ErrorKind(StrEnum):
    RECOVERABLE = "recoverable"
    USER_ACTION_REQUIRED = "user_action_required"
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class ReadBlock:
    kind: ReadBlockKind
    value: str = ""


@dataclass(frozen=True, slots=True)
class EngineConfig:
    kind: TtsEngineKind
    url: str = ""
    executable_path: str = ""
    model_path: str = ""
    speaker_id: int = 0
    speed: float = 1.0
    pitch: float = 0.0
    intonation: float | None = None
    volume: float = 1.0
    pause_length: float | None = None
    pre_phoneme_length: float | None = None
    post_phoneme_length: float | None = None
    max_length: int = 50
    num_steps: int | None = None
    num_threads: int | None = None
    device: str = "cpu"
    device_policy: str = "auto"
    device_priority: tuple[str, ...] = ()
    backend: str = ""


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    youtube_api_key: str = ""
    youtube_source: str = ""
    skip_history: bool = True
    read_paid_events: bool = True


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    active_engine: TtsEngineKind
    engines: tuple[EngineConfig, ...]
    read_blocks: tuple[ReadBlock, ...] = (ReadBlock(ReadBlockKind.MESSAGE),)

    def engine(self, kind: TtsEngineKind | None = None) -> EngineConfig:
        selected = kind or self.active_engine
        for engine in self.engines:
            if engine.kind is selected:
                return engine
        raise KeyError(f"TTS engine configuration is missing: {selected.value}")


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
class DictionaryConfig:
    active_group: str = "デフォルト"


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


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    word: str
    reading: str
    part_of_speech: str = "名詞"
    comment: str = ""


@dataclass(frozen=True, slots=True)
class Speaker:
    identifier: int
    name: str
    style: str = ""


@dataclass(frozen=True, slots=True)
class CommentEvent:
    author: str
    message: str
    profile_image_url: str = ""
    skip_speech: bool = False
    sound_file: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechParameters:
    speaker_id: int
    speed: float
    pitch: float
    volume: float
    intonation: float | None = None
    pause_length: float | None = None
    pre_phoneme_length: float | None = None
    post_phoneme_length: float | None = None
    echo: int | None = None
    yamabiko: int | None = None
    panning: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    text: str
    parameters: SpeechParameters
    action: SpeechAction | None = None
    word: str | None = None
    reading: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    segments: tuple[SpeechSegment, ...]
    engine: EngineConfig


@dataclass(frozen=True, slots=True)
class TtsInitializationRequest:
    engine: EngineConfig
    stream_source: str = ""
    api_key: str = ""
    debug: bool = False

    @property
    def signature(self) -> tuple[str, str, str, str]:
        path = self.engine.model_path or self.engine.executable_path
        return (self.engine.kind.value, self.engine.url, path, self.engine.device)


@dataclass(frozen=True, slots=True)
class GpuMetric:
    identifier: str
    name: str
    usage_percent: float
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    network_send_kbps: float
    network_receive_kbps: float
    gpus: tuple[GpuMetric, ...] = ()
    npu_percent: float | None = None


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    state: RuntimeState
    queued_speech: int = 0
    current_speech: str = ""
    streaming_connected: bool = False
    active_tts_engine: TtsEngineKind | None = None
    metrics: MetricsSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ApplicationIssue:
    kind: ErrorKind
    code: str
    message: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CacheLookup:
    key: str
    request_count: int
    wav_data: bytes | None
    level: str
