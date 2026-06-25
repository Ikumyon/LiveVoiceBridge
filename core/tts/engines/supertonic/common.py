from __future__ import annotations

import io
import re
import unicodedata
import wave

import numpy as np


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
    samples = np.asarray(wav, dtype=np.float32).squeeze()
    samples = np.clip(samples * volume, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()
