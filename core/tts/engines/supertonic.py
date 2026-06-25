from __future__ import annotations

import io
import re
import threading
import unicodedata
import wave

import numpy as np

from core.tts.base import BaseTTSEngine


class SupertonicEngine(BaseTTSEngine):
    DISPLAY_NAME = "SUPERTONIC 3"
    DEFAULT_URL = "local://supertonic"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

    VOICE_NAMES = ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")
    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        if "supertonic" not in config or not isinstance(config["supertonic"], dict):
            config["supertonic"] = {}

        supertonic = config["supertonic"]
        supertonic["url"] = cls.DEFAULT_URL
        supertonic["path"] = ""
        supertonic.setdefault("speaker_id", 0)
        supertonic.setdefault("speed", 1.0)
        supertonic.setdefault("volume", 1.0)
        supertonic.setdefault("max_length", 50)
        supertonic.setdefault("num_steps", 8)

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url or self.DEFAULT_URL, exe_path)
        self._tts = None
        self.num_steps = 8
        self.last_error = ""
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._tts is not None

    def ensure_running(self) -> bool:
        if self._tts is not None:
            return True
        try:
            from supertonic import TTS

            self._tts = TTS(auto_download=True)
            self.last_error = ""
            return True
        except Exception as exc:
            self._tts = None
            self.last_error = str(exc)
            print(f"[Supertonic] 初期化失敗: {exc}")
            return False

    def synthesize_wav(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        intonation: float = None,
        volume: float = None,
        pause_length: float = None,
        pre_phoneme_length: float = None,
        post_phoneme_length: float = None,
        speaker_id: int = None,
    ) -> bytes | None:
        if not text.strip():
            return None

        target_speed = float(speed if speed is not None else 1.0)
        target_volume = float(volume if volume is not None else 1.0)
        target_speaker = int(speaker_id if speaker_id is not None else 0)

        try:
            if not self.ensure_running():
                raise RuntimeError(self.last_error or "公式Supertonic SDKを初期化できません。")

            normalized_text = self._prepare_japanese_text(text)
            voice_name = self._voice_name(target_speaker)
            total_steps = int(getattr(self, "num_steps", 8))

            with self._lock:
                print(
                    f"[Supertonic] TTS入力: {normalized_text} "
                    f"(voice={voice_name}, lang=ja, steps={total_steps})"
                )
                voice_style = self._tts.get_voice_style(voice_name=voice_name)
                wav, _ = self._tts.synthesize(
                    text=normalized_text,
                    voice_style=voice_style,
                    lang="ja",
                    total_steps=total_steps,
                    speed=target_speed,
                    verbose=False,
                )

            samples = np.asarray(wav, dtype=np.float32).squeeze()
            samples = np.clip(samples * target_volume, -1.0, 1.0)
            pcm = (samples * 32767.0).astype(np.int16)
            return self._pcm_to_wav_bytes(pcm, int(self._tts.sample_rate))
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[Supertonic] 合成失敗: {exc}")
            return None

    @staticmethod
    def _prepare_japanese_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if normalized and not re.search(r"[.!?…。」』〗〉》›»]$", normalized):
            normalized += "。"
        return normalized

    @classmethod
    def _voice_name(cls, speaker_id: int) -> str:
        if 0 <= speaker_id < len(cls.VOICE_NAMES):
            return cls.VOICE_NAMES[speaker_id]
        return cls.VOICE_NAMES[0]

    @staticmethod
    def _pcm_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(samples.tobytes())
        return buffer.getvalue()

    def get_speakers(self) -> list[dict] | None:
        return [{
            "name": "Supertonic 3",
            "styles": [
                {"name": voice_name, "id": index}
                for index, voice_name in enumerate(self.VOICE_NAMES)
            ],
        }]

    def terminate(self) -> None:
        self._tts = None
