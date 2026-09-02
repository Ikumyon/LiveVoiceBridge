from __future__ import annotations

import importlib
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType

import pytest

from livevoicebridge import APP_NAME, bootstrap
from livevoicebridge.application.models import (
    AppConfig,
    EngineConfig,
    PresentationConfig,
    ReadBlock,
    ReadBlockKind,
    RuntimeState,
    SpeechConfig,
    StreamingConfig,
    TtsEngineKind,
)
from livevoicebridge.application.ports import ConfigRepository
from livevoicebridge.bootstrap import project_root


class _MemoryConfigRepository:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def load(self) -> AppConfig:
        return self.config

    def save(self, config: AppConfig) -> None:
        self.config = config


def _config() -> AppConfig:
    return AppConfig(
        schema_version=1,
        streaming=StreamingConfig(),
        speech=SpeechConfig(
            active_engine=TtsEngineKind.VOICEVOX,
            engines=(EngineConfig(kind=TtsEngineKind.VOICEVOX),),
        ),
        presentation=PresentationConfig(),
    )


def test_application_models_are_immutable_typed_values() -> None:
    config = _config()

    assert APP_NAME == "LiveVoiceBridge"
    assert config.speech.read_blocks == (ReadBlock(ReadBlockKind.MESSAGE),)
    assert config.speech.engine().kind is TtsEngineKind.VOICEVOX
    with pytest.raises(FrozenInstanceError):
        config.schema_version = 2  # type: ignore[misc]


def test_repository_port_accepts_structural_implementation() -> None:
    repository = _MemoryConfigRepository(_config())

    assert isinstance(repository, ConfigRepository)
    assert repository.load().schema_version == 1


def test_runtime_state_values_are_stable() -> None:
    assert [state.value for state in RuntimeState] == [
        "idle",
        "starting",
        "running",
        "stopping",
        "error",
    ]


def test_bootstrap_resolves_checkout_root() -> None:
    assert project_root() == Path(__file__).resolve().parents[1]


def test_root_entry_point_imports_without_eager_runtime_import() -> None:
    sys.modules.pop("livevoicebridge.application.runtime", None)
    entry_point = importlib.import_module("main")

    assert callable(entry_point.main)
    assert "livevoicebridge.application.runtime" not in sys.modules


def test_bootstrap_delegates_to_packaged_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def run_application() -> None:
        nonlocal called
        called = True

    runtime = ModuleType("livevoicebridge.application.runtime")
    runtime.run_application = run_application  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)

    bootstrap.main()

    assert called


def test_packaged_runtime_remains_importable() -> None:
    sys.modules.pop("livevoicebridge.application.runtime", None)
    runtime = importlib.import_module("livevoicebridge.application.runtime")

    assert callable(runtime.run_application)
    assert runtime.LiveVoiceBridgeApp.__name__ == "LiveVoiceBridgeApp"
