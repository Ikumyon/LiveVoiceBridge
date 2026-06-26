from __future__ import annotations

from pathlib import Path


DEVICE_ID = "cpu"
DISPLAY_NAME = "CPU"


def is_available() -> bool:
    return True


def create_tts(model_dir: Path):
    from supertonic import TTS

    return TTS(
        model="supertonic-3",
        model_dir=model_dir,
        auto_download=False,
    )
