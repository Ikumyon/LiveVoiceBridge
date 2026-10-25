"""Application-owned Qwen lifecycle contracts, independent of Qt and OS APIs."""

from dataclasses import dataclass
from threading import Event
from typing import Protocol

from livevoicebridge.core.speech.models import Qwen3Config


@dataclass(frozen=True, slots=True)
class QwenState:
    phase: str = "unprepared"
    message: str = "モデルを準備してください。"
    model_path: str = ""
    progress: int | None = None
    busy: bool = False
    generation: int = 0


class QwenRuntime(Protocol):
    @property
    def state(self) -> QwenState: ...
    def configure(self, config: Qwen3Config | None) -> None: ...
    def prepare(self, source: str, device: str) -> None: ...
    def cancel_preparation(self) -> None: ...
    def restart(self) -> None: ...
    def wait_ready(self, cancelled: Event) -> str: ...
    def read_log(self) -> str: ...
    def close(self) -> None: ...
