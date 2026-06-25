from __future__ import annotations

import threading
import time
from pathlib import Path

from core.app_config import EXE_DIR
from core.tts.base import BaseTTSEngine
from core.tts.engines.supertonic import (
    backend_cpu,
    backend_directml,
    backend_openvino_npu,
    backend_openvino,
)
from core.tts.engines.supertonic.common import (
    VOICE_NAMES,
    float_audio_to_wav_bytes,
    prepare_japanese_text,
    voice_name,
)


BACKENDS = {
    backend_cpu.DEVICE_ID: backend_cpu,
    backend_openvino.DEVICE_ID: backend_openvino,
    backend_directml.DEVICE_ID: backend_directml,
    backend_openvino_npu.DEVICE_ID: backend_openvino_npu,
}


class SupertonicEngine(BaseTTSEngine):
    DISPLAY_NAME = "SUPERTONIC 3"
    DEFAULT_URL = "local://supertonic"
    DEFAULT_MODEL_PATH = "models/supertonic-3"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        if "supertonic" not in config or not isinstance(config["supertonic"], dict):
            config["supertonic"] = {}

        supertonic = config["supertonic"]
        supertonic["url"] = cls.DEFAULT_URL
        supertonic["path"] = cls.DEFAULT_MODEL_PATH
        supertonic.setdefault("speaker_id", 0)
        supertonic.setdefault("speed", 1.0)
        supertonic.setdefault("volume", 1.0)
        supertonic.setdefault("max_length", 50)
        supertonic.setdefault("num_steps", 8)
        supertonic.setdefault("device", backend_cpu.DEVICE_ID)

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url or self.DEFAULT_URL, exe_path)
        path = Path(exe_path or self.DEFAULT_MODEL_PATH)
        self.model_dir = path if path.is_absolute() else EXE_DIR / path
        self._tts = None
        self.num_steps = 8
        self.device = backend_cpu.DEVICE_ID
        self.active_device = ""
        self.last_error = ""
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._tts is not None

    def ensure_running(self) -> bool:
        if self._tts is not None:
            return True
        try:
            backend = BACKENDS[self.device]
            self._tts = backend.create_tts(self.model_dir)
            self.active_device = backend.DISPLAY_NAME
            print(f"[Supertonic] 実行デバイス: {self.active_device}")
            self.last_error = ""
            return True
        except Exception as exc:
            self._tts = None
            self.last_error = str(exc)
            print(f"[Supertonic] 初期化失敗: {exc}")
            return False

    def configure_device(self, device: str) -> None:
        target = device if device in BACKENDS and BACKENDS[device].is_available() else backend_cpu.DEVICE_ID
        if target != self.device:
            self.terminate()
            self.device = target

    @staticmethod
    def available_devices() -> list[tuple[str, str]]:
        return [
            (device_id, backend.DISPLAY_NAME)
            for device_id, backend in BACKENDS.items()
            if backend.is_available()
        ]

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

            normalized_text = prepare_japanese_text(text)
            selected_voice = voice_name(target_speaker)
            total_steps = int(getattr(self, "num_steps", 8))

            with self._lock:
                started_at = time.perf_counter()
                print(
                    f"[Supertonic] TTS入力: {normalized_text} "
                    f"(voice={selected_voice}, lang=ja, steps={total_steps})"
                )
                voice_style = self._tts.get_voice_style(voice_name=selected_voice)
                wav, _ = self._tts.synthesize(
                    text=normalized_text,
                    voice_style=voice_style,
                    lang="ja",
                    total_steps=total_steps,
                    speed=target_speed,
                    verbose=False,
                )
                elapsed = time.perf_counter() - started_at
                print(f"[Supertonic] 生成時間: {elapsed:.3f}秒")

            return float_audio_to_wav_bytes(
                wav,
                int(self._tts.sample_rate),
                target_volume,
            )
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[Supertonic] 合成失敗: {exc}")
            return None

    def get_speakers(self) -> list[dict] | None:
        return [{
            "name": "Supertonic 3",
            "styles": [
                {"name": name, "id": index}
                for index, name in enumerate(VOICE_NAMES)
            ],
        }]

    def terminate(self) -> None:
        self._tts = None
        self.active_device = ""
