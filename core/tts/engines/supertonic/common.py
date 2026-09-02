from __future__ import annotations

import re
import unicodedata

import numpy as np
from livevoicebridge_native import float_audio_to_wav_bytes as native_float_audio_to_wav_bytes


VOICE_NAMES = ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")


def prepare_japanese_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized and not re.search(r"[.!?…。」』〗〉》›»]$", normalized):
        normalized += "。"
    return normalized


def voice_name(speaker_id: int) -> str:
    if 0 <= speaker_id < len(VOICE_NAMES):
        return VOICE_NAMES[speaker_id]
    return VOICE_NAMES[0]


def float_audio_to_wav_bytes(
    wav: np.ndarray,
    sample_rate: int,
    volume: float,
) -> bytes:
    samples = np.ascontiguousarray(np.asarray(wav, dtype=np.float32).squeeze())
    return native_float_audio_to_wav_bytes(memoryview(samples), sample_rate, volume)
