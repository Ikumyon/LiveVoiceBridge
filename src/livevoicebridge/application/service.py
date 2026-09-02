"""Application command facade independent from Qt widgets and workers."""

from __future__ import annotations

from collections.abc import Callable

from livevoicebridge.application.models import RuntimeState
from livevoicebridge.application.state import Lifecycle


class ApplicationService:
    def __init__(self, on_state_changed: Callable[[RuntimeState], None] | None = None) -> None:
        self.lifecycle = Lifecycle()
        self._on_state_changed = on_state_changed or (lambda _state: None)

    @property
    def state(self) -> RuntimeState:
        return self.lifecycle.state

    def connect_stream(self, start_action: Callable[[], None]) -> None:
        self._notify(self.lifecycle.begin_start())
        try:
            start_action()
        except Exception:
            self._notify(self.lifecycle.fail())
            raise

    def mark_running(self) -> None:
        self._notify(self.lifecycle.mark_running())

    def disconnect_stream(self, stop_action: Callable[[], None]) -> None:
        if self.state is RuntimeState.IDLE:
            return
        self._notify(self.lifecycle.begin_stop())
        try:
            stop_action()
        except Exception:
            self._notify(self.lifecycle.fail())
            raise
        self._notify(self.lifecycle.mark_stopped())

    def mark_failed(self) -> None:
        if self.state is not RuntimeState.ERROR:
            self._notify(self.lifecycle.fail())

    def shutdown(self, stop_action: Callable[[], None]) -> None:
        self.disconnect_stream(stop_action)

    def _notify(self, state: RuntimeState) -> None:
        self._on_state_changed(state)
