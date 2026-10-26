"""Public TTS contracts. Importing this module needs neither Qt nor native code."""

from dataclasses import dataclass
from threading import Event
from typing import Protocol

from livevoicebridge.core.speech.models import (
    AudioData,
    EngineCapabilities,
    EngineConfig,
    EngineState,
    SettingValue,
    Speaker,
    SpeechControls,
)
from livevoicebridge.core.speech.ports import AudioSynthesizer, ExternalSpeechOutput

API_VERSION = 1

__all__ = [
    "API_VERSION",
    "AudioData",
    "AudioSynthesizer",
    "EngineCapabilities",
    "EngineConfig",
    "EngineState",
    "ExternalSpeechOutput",
    "SettingField",
    "SettingValue",
    "Speaker",
    "SpeechControls",
    "TtsProvider",
]


@dataclass(frozen=True, slots=True)
class SettingField:
    key: str
    title: str
    kind: str = "text"
    default: SettingValue = ""
    minimum: float = -1000000
    maximum: float = 1000000
    choices: tuple[str, ...] = ()


class TtsProvider(Protocol):
    id: str
    name: str
    capabilities: EngineCapabilities
    fields: tuple[SettingField, ...]

    def defaults(self) -> EngineConfig: ...
    def validate(self, config: EngineConfig) -> None: ...
    def create(self, config: EngineConfig) -> AudioSynthesizer | ExternalSpeechOutput: ...
    def configure(self, config: EngineConfig | None) -> None: ...
    def wait_ready(self, cancelled: Event) -> object: ...
    def close(self) -> None: ...
