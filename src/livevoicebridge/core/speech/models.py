"""Speech contracts use immutable values, including queue contents."""

from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Protocol, TypeAlias


class TtsEngineKind(StrEnum):
    VOICEVOX = "voicevox"
    COEIROINK = "coeiroink"
    BOUYOMICHAN = "bouyomichan"
    QWEN3 = "qwen3"


class ReadBlockKind(StrEnum):
    AUTHOR = "author"
    MESSAGE = "message"
    TEXT = "text"


class SpeechAction(StrEnum):
    ADD_DICTIONARY = "add_dict"
    DELETE_DICTIONARY = "del_dict"


@dataclass(frozen=True, slots=True)
class ReadBlock:
    kind: ReadBlockKind
    value: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class EngineConnection:
    url: str
    executable_path: str = ""
    speaker_id: int = 0
    max_length: int = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class VoicevoxConfig(EngineConnection):
    kind: TtsEngineKind = TtsEngineKind.VOICEVOX
    speed: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0
    intonation: float = 1.0
    pause_length: float = 1.0
    pre_phoneme_length: float = 0.1
    post_phoneme_length: float = 0.1


@dataclass(frozen=True, slots=True, kw_only=True)
class CoeiroinkConfig(VoicevoxConfig):
    kind: TtsEngineKind = TtsEngineKind.COEIROINK


@dataclass(frozen=True, slots=True, kw_only=True)
class BouyomiConfig(EngineConnection):
    kind: TtsEngineKind = TtsEngineKind.BOUYOMICHAN
    speed: int = -1
    pitch: int = -1
    volume: int = -1


@dataclass(frozen=True, slots=True, kw_only=True)
class Qwen3Config(EngineConnection):
    kind: TtsEngineKind = TtsEngineKind.QWEN3
    volume: float = 1.0


EngineConfig: TypeAlias = VoicevoxConfig | CoeiroinkConfig | BouyomiConfig | Qwen3Config


def update_engine(config: EngineConfig, values: dict) -> EngineConfig:
    """Convert a form draft; only fields owned by this engine are accepted."""
    allowed = {item.name for item in fields(config)} - {"kind"}
    return replace(config, **{key: value for key, value in values.items() if key in allowed})


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    active_engine: TtsEngineKind
    engines: tuple[EngineConfig, ...]
    read_blocks: tuple[ReadBlock, ...] = (ReadBlock(ReadBlockKind.MESSAGE),)
    queue_limit: int = 100

    def engine(self, kind: TtsEngineKind | None = None) -> EngineConfig:
        selected = kind or self.active_engine
        return next(engine for engine in self.engines if engine.kind == selected)


@dataclass(frozen=True, slots=True)
class Speaker:
    identifier: int
    name: str
    style: str = "通常"


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    controls: frozenset[str]
    local_audio: bool
    completion_known: bool


def capabilities(kind: TtsEngineKind) -> EngineCapabilities:
    common = {"speaker_id", "volume"}
    if kind is TtsEngineKind.QWEN3:
        return EngineCapabilities(frozenset(common | {"echo", "yamabiko", "panning"}), True, True)
    if kind is TtsEngineKind.BOUYOMICHAN:
        return EngineCapabilities(frozenset(common | {"speed", "pitch"}), False, False)
    return EngineCapabilities(frozenset(common | {"speed", "pitch", "echo", "yamabiko", "panning"}), True, True)


@dataclass(frozen=True, slots=True)
class SpeechControls:
    speaker_id: int | None = None
    speed: float | None = None
    pitch: float | None = None
    volume: float | None = None
    echo: int | None = None
    yamabiko: int | None = None
    panning: str | None = None


@dataclass(frozen=True, slots=True)
class Utterance:
    text: str
    controls: SpeechControls = SpeechControls()


@dataclass(frozen=True, slots=True)
class DictionaryCommand:
    action: SpeechAction
    word: str
    reading: str = ""


@dataclass(frozen=True, slots=True)
class SoundEffect:
    filename: str
    overlap: bool = True


SpeechItem: TypeAlias = Utterance | DictionaryCommand | SoundEffect


@dataclass(frozen=True, slots=True)
class SpeechPlan:
    items: tuple[SpeechItem, ...]


@dataclass(frozen=True, slots=True)
class SpeechProgress:
    session: int
    revision: int
    queued: int = 0
    current_text: str = ""
    rejected: int = 0
    external: bool = False


class PcmBuffer(Protocol):
    @property
    def byte_length(self) -> int: ...


@dataclass(frozen=True, slots=True)
class AudioData:
    buffer: PcmBuffer

    @property
    def byte_length(self) -> int:
        return self.buffer.byte_length
