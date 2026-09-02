"""Strict application lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass

from livevoicebridge.application.models import RuntimeState


class InvalidStateTransition(RuntimeError):
    pass


@dataclass(slots=True)
class Lifecycle:
    state: RuntimeState = RuntimeState.IDLE

    def begin_start(self) -> RuntimeState:
        self._require(RuntimeState.IDLE, RuntimeState.ERROR)
        return self._set(RuntimeState.STARTING)

    def mark_running(self) -> RuntimeState:
        self._require(RuntimeState.STARTING)
        return self._set(RuntimeState.RUNNING)

    def begin_stop(self) -> RuntimeState:
        self._require(RuntimeState.STARTING, RuntimeState.RUNNING, RuntimeState.ERROR)
        return self._set(RuntimeState.STOPPING)

    def mark_stopped(self) -> RuntimeState:
        self._require(RuntimeState.STOPPING)
        return self._set(RuntimeState.IDLE)

    def fail(self) -> RuntimeState:
        self._require(RuntimeState.STARTING, RuntimeState.RUNNING, RuntimeState.STOPPING)
        return self._set(RuntimeState.ERROR)

    def _require(self, *allowed: RuntimeState) -> None:
        if self.state not in allowed:
            expected = ", ".join(state.value for state in allowed)
            raise InvalidStateTransition(f"{self.state.value} では実行できません。必要な状態: {expected}")

    def _set(self, state: RuntimeState) -> RuntimeState:
        self.state = state
        return state
