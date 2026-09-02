from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from livevoicebridge.application.models import TtsEngineKind
from livevoicebridge.infrastructure.config_repository import (
    ConfigError,
    JsonConfigRepository,
    default_config,
)


def test_missing_config_creates_official_schema(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    repository = JsonConfigRepository(path)

    config = repository.load()
    document = json.loads(path.read_text(encoding="utf-8"))

    assert config == default_config()
    assert document["schema_version"] == 1
    assert set(document) == {
        "schema_version",
        "streaming",
        "speech",
        "presentation",
        "dictionary",
        "application",
    }


def test_round_trip_preserves_all_typed_sections(tmp_path: Path) -> None:
    repository = JsonConfigRepository(tmp_path / "config.json")
    original = default_config()
    changed = replace(
        original,
        streaming=replace(original.streaming, youtube_source="abcdefghijk"),
        speech=replace(original.speech, active_engine=TtsEngineKind.SUPERTONIC),
        presentation=replace(original.presentation, comment_popout=True, window_x=12),
    )

    repository.save(changed)

    assert repository.load() == changed


def test_legacy_config_is_backed_up_and_migrated_once(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    legacy = {
        "youtube_api_key": "secret",
        "youtube_url": "abcdefghijk",
        "tts_engine": "supertonic",
        "supertonic": {
            "path": "models/custom",
            "speaker_id": 2,
            "speed": 1.2,
            "volume": 0.9,
            "max_length": 80,
            "num_steps": 12,
            "device": "gpu",
        },
        "read_blocks": [{"type": "author"}, {"type": "text", "value": "さん。"}],
        "comment_popout": True,
        "comment_win_x": 100,
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    repository = JsonConfigRepository(path)

    migrated = repository.load()

    assert migrated.schema_version == 1
    assert migrated.streaming.youtube_api_key == "secret"
    assert migrated.speech.active_engine is TtsEngineKind.SUPERTONIC
    assert migrated.speech.engine().model_path == "models/custom"
    assert migrated.presentation.comment_popout
    assert migrated.presentation.window_x == 100
    assert json.loads((tmp_path / "config.legacy.json").read_text(encoding="utf-8")) == legacy
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_invalid_or_unknown_schema_fails_without_default_fallback(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        JsonConfigRepository(invalid).load()

    unknown = tmp_path / "unknown.json"
    unknown.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ConfigError, match="未対応"):
        JsonConfigRepository(unknown).load()


def test_official_schema_requires_every_supported_engine(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    repository = JsonConfigRepository(path)
    repository.save(default_config())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["speech"]["engines"].pop()
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match="対応エンジン"):
        repository.load()
