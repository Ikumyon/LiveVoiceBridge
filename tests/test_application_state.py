from __future__ import annotations

import pytest

from livevoicebridge.application.models import RuntimeState
from livevoicebridge.application.service import ApplicationService
from livevoicebridge.application.state import InvalidStateTransition, Lifecycle


def test_lifecycle_happy_path() -> None:
    lifecycle = Lifecycle()

    assert lifecycle.begin_start() is RuntimeState.STARTING
    assert lifecycle.mark_running() is RuntimeState.RUNNING
    assert lifecycle.begin_stop() is RuntimeState.STOPPING
    assert lifecycle.mark_stopped() is RuntimeState.IDLE


def test_lifecycle_rejects_duplicate_start_and_stop() -> None:
    lifecycle = Lifecycle()
    lifecycle.begin_start()

    with pytest.raises(InvalidStateTransition):
        lifecycle.begin_start()
    with pytest.raises(InvalidStateTransition):
        lifecycle.mark_stopped()


def test_failed_start_can_be_retried() -> None:
    lifecycle = Lifecycle()
    lifecycle.begin_start()
    assert lifecycle.fail() is RuntimeState.ERROR
    assert lifecycle.begin_start() is RuntimeState.STARTING


def test_service_notifies_and_runs_commands_in_order() -> None:
    events: list[str] = []
    service = ApplicationService(lambda state: events.append(state.value))

    service.connect_stream(lambda: events.append("start-action"))
    service.mark_running()
    service.disconnect_stream(lambda: events.append("stop-action"))

    assert events == ["starting", "start-action", "running", "stopping", "stop-action", "idle"]


def test_service_moves_to_error_when_command_fails() -> None:
    service = ApplicationService()

    with pytest.raises(RuntimeError, match="boom"):
        service.connect_stream(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert service.state is RuntimeState.ERROR
