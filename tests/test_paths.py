from __future__ import annotations

from livevoicebridge.application.models import ReadBlock, ReadBlockKind, TtsEngineKind
from livevoicebridge.infrastructure.config_repository import default_config
from livevoicebridge.paths import (
    COMMENT_WINDOW_UI_FILE,
    MAIN_UI_FILE,
    PROTO_FILE,
    SETTINGS_UI_FILE,
    TASK_MANAGER_UI_FILE,
)


def test_default_config_contains_every_supported_engine() -> None:
    config = default_config()

    assert {engine.kind for engine in config.speech.engines} == set(TtsEngineKind)
    assert config.speech.read_blocks == (ReadBlock(ReadBlockKind.MESSAGE),)


def test_required_resource_files_exist() -> None:
    assert MAIN_UI_FILE.is_file()
    assert SETTINGS_UI_FILE.is_file()
    assert COMMENT_WINDOW_UI_FILE.is_file()
    assert TASK_MANAGER_UI_FILE.is_file()
    assert PROTO_FILE.is_file()
