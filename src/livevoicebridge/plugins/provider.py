"""Shared validation and default lifecycle for stateless TTS providers."""

import math
from collections.abc import Callable
from threading import Event

from livevoicebridge.plugins.contracts import (
    AudioSynthesizer,
    EngineCapabilities,
    EngineConfig,
    ExternalSpeechOutput,
    SettingField,
)


class Provider:
    def __init__(
        self,
        identifier: str,
        name: str,
        capabilities: EngineCapabilities,
        fields: tuple[SettingField, ...],
        factory: Callable[[EngineConfig], AudioSynthesizer | ExternalSpeechOutput],
        speaker: str = "0",
    ):
        self.id, self.name = identifier, name
        self.capabilities, self.fields = capabilities, fields
        self._factory, self._speaker = factory, speaker

    def defaults(self) -> EngineConfig:
        return EngineConfig(self.id, self._speaker, settings={item.key: item.default for item in self.fields})

    def validate(self, config: EngineConfig) -> None:
        if config.engine_id != self.id:
            raise ValueError("エンジンIDが一致しません。")
        for field in self.fields:
            value = config.settings.get(field.key, field.default)
            valid = {
                "text": isinstance(value, str),
                "secret": isinstance(value, str),
                "file": isinstance(value, str),
                "directory": isinstance(value, str),
                "choice": isinstance(value, str) and value in field.choices,
                "bool": type(value) is bool,
                "integer": type(value) is int,
                "number": type(value) in (int, float),
            }
            if not valid.get(field.kind, False):
                raise ValueError(f"{field.title}の値が不正です。")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(value) or not field.minimum <= value <= field.maximum:
                    raise ValueError(f"{field.title}が範囲外です。")

    def create(self, config: EngineConfig) -> AudioSynthesizer | ExternalSpeechOutput:
        self.validate(config)
        return self._factory(config)

    def configure(self, config: EngineConfig | None) -> None:
        pass

    def wait_ready(self, cancelled: Event) -> object:
        return None

    def close(self) -> None:
        pass
