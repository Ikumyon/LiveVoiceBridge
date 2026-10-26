"""Speech contracts use immutable values, including queue contents."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


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


type SettingValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class EngineConfig:
    engine_id: str
    speaker_id: str = "0"
    max_length: int = 50
    settings: dict[str, SettingValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    active_engine: str
    engines: tuple[EngineConfig, ...]
    read_blocks: tuple[ReadBlock, ...] = (ReadBlock(ReadBlockKind.MESSAGE),)
    queue_limit: int = 100

    def engine(self, kind: str | None = None) -> EngineConfig:
        selected = kind or self.active_engine
        for engine in self.engines:
            if engine.engine_id == selected:
                return engine
        raise ValueError(f"TTSの設定がありません: {selected}")


@dataclass(frozen=True, slots=True)
class Speaker:
    identifier: str
    name: str
    style: str = "通常"


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    controls: frozenset[str]
    local_audio: bool
    completion_known: bool


@dataclass(frozen=True, slots=True)
class EngineState:
    engine_id: str
    phase: str
    message: str
    generation: int = 0
    busy: bool = False


@dataclass(frozen=True, slots=True)
class SpeechControls:
    speaker_id: str | None = None
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


type SpeechItem = Utterance | DictionaryCommand | SoundEffect


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
