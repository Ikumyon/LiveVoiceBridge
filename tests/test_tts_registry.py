from __future__ import annotations

from livevoicebridge.application.models import TtsEngineKind
from livevoicebridge.infrastructure.config_repository import default_config
from livevoicebridge.infrastructure.tts.registry import backend_config, config_from_backend


def test_backend_mapping_preserves_remote_executable_path() -> None:
    existing = default_config().speech.engine(TtsEngineKind.VOICEVOX)

    updated = config_from_backend(
        TtsEngineKind.VOICEVOX,
        {"url": "http://localhost:50021", "path": "voicevox.exe", "speaker_id": 7},
        existing,
    )

    assert updated.executable_path == "voicevox.exe"
    assert updated.model_path == ""
    assert backend_config(updated)["path"] == "voicevox.exe"


def test_backend_mapping_preserves_local_model_path() -> None:
    existing = default_config().speech.engine(TtsEngineKind.SUPERTONIC)

    updated = config_from_backend(
        TtsEngineKind.SUPERTONIC,
        {"path": "models/replaced", "device": "gpu", "num_steps": 16},
        existing,
    )

    assert updated.executable_path == ""
    assert updated.model_path == "models/replaced"
    assert backend_config(updated)["path"] == "models/replaced"
