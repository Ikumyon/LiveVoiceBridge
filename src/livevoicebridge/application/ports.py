"""Dependency-inversion ports used by LiveVoiceBridge application services."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from livevoicebridge.application.models import (
    AppConfig,
    CacheLookup,
    CommentEvent,
    DictionaryEntry,
    EngineConfig,
    MetricsSnapshot,
    Speaker,
    SpeechParameters,
)


@runtime_checkable
class StreamingSource(Protocol):
    def start(
        self,
        on_comment: Callable[[CommentEvent], None],
        on_error: Callable[[Exception], None],
    ) -> None: ...

    def stop(self) -> None: ...

    @property
    def is_running(self) -> bool: ...


@runtime_checkable
class TtsEngine(Protocol):
    @property
    def config(self) -> EngineConfig: ...

    def ensure_ready(self) -> bool: ...

    def synthesize(self, text: str, parameters: SpeechParameters) -> bytes: ...

    def speakers(self) -> Sequence[Speaker]: ...

    def close(self) -> None: ...


@runtime_checkable
class AudioOutput(Protocol):
    def play(self, wav_path: Path) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class ConfigRepository(Protocol):
    def load(self) -> AppConfig: ...

    def save(self, config: AppConfig) -> None: ...


@runtime_checkable
class DictionaryRepository(Protocol):
    def groups(self) -> Sequence[str]: ...

    def load_group(self, group: str) -> Sequence[DictionaryEntry]: ...

    def save_group(self, group: str, entries: Iterable[DictionaryEntry]) -> None: ...

    def delete_group(self, group: str) -> None: ...


@runtime_checkable
class SpeechCache(Protocol):
    def lookup(self, text: str, engine: EngineConfig, parameters: SpeechParameters) -> CacheLookup: ...

    def store(self, lookup: CacheLookup, wav_data: bytes) -> None: ...

    def record_failure(self, key: str) -> None: ...

    def cleanup(self) -> None: ...


@runtime_checkable
class MetricsProvider(Protocol):
    def collect(self) -> MetricsSnapshot: ...
