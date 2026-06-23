from __future__ import annotations

import os
import tempfile

from core.tts.base import BaseTTSEngine
from core.audio.playback import apply_audio_effects, play_wav
from core.comment_processing import replace_emojis, replace_words


def speak_segments_offline(
    tts_engine: BaseTTSEngine,
    segments: list[dict],
    speaker_id: int,
    speed: float,
    word_list: list[dict],
) -> None:
    for seg in segments:
        text = seg.get("text", "")
        if not text:
            continue

        text = replace_words(text, word_list)
        text = replace_emojis(text)

        target_speaker = seg.get("speaker_id") if seg.get("speaker_id") is not None else speaker_id
        target_speed = seg.get("speed") if seg.get("speed") is not None else speed
        target_volume = seg.get("volume") if seg.get("volume") is not None else 1.0

        try:
            content = tts_engine.synthesize_wav(
                text=text,
                speed=target_speed,
                pitch=seg.get("pitch"),
                volume=target_volume,
                speaker_id=target_speaker
            )
            if content:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
                    fp.write(content)
                    wav_path = fp.name

                wav_path = apply_audio_effects(
                    wav_path,
                    echo_level=seg.get("echo"),
                    yamabiko_level=seg.get("yamabiko"),
                    panning=seg.get("panning")
                )

                play_wav(wav_path)
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
        except Exception as e:
            print(f"オフラインテスト発声エラー: {e}")
