from __future__ import annotations

from core.app_config import DEFAULT_CONFIG, MAIN_UI_FILE, SETTINGS_UI_FILE


def test_default_config_contains_every_supported_engine_section() -> None:
    engine_names = {
        "voicevox",
        "coeiroink",
        "bouyomichan",
        "supertonic_lightweight",
        "supertonic",
    }

    assert DEFAULT_CONFIG["tts_engine"] in engine_names
    for engine_name in engine_names:
        engine = DEFAULT_CONFIG[engine_name]
        assert isinstance(engine, dict)
        assert "speaker_id" in engine
        assert "speed" in engine
        assert "volume" in engine
        assert "max_length" in engine


def test_default_read_format_is_message_only() -> None:
    assert DEFAULT_CONFIG["read_blocks"] == [{"type": "message"}]


def test_required_designer_files_exist() -> None:
    assert MAIN_UI_FILE.is_file()
    assert SETTINGS_UI_FILE.is_file()
