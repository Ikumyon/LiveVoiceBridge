from __future__ import annotations

import io
import re
import threading
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

from core.app_config import EXE_DIR
from core.tts.base import BaseTTSEngine


class SupertonicEngine(BaseTTSEngine):
    DISPLAY_NAME = "SUPERTONIC 3"
    DEFAULT_URL = "local://supertonic"
    DEFAULT_MODEL_PATH = "models/supertonic-3"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

    VOICE_NAMES = ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")

    class _OpenVinoSession:
        def __init__(self, model_path: Path, device: str):
            import openvino as ov

            core = ov.Core()
            model = core.read_model(str(model_path))
            self.compiled_model = core.compile_model(model, device)
            self.outputs = list(self.compiled_model.outputs)

        def run(self, output_names, input_feed):
            result = self.compiled_model(input_feed)
            return [np.asarray(result[output]) for output in self.outputs]

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
        supertonic.setdefault("device", "cpu")

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url or self.DEFAULT_URL, exe_path)
        path = Path(exe_path or self.DEFAULT_MODEL_PATH)
        self.model_dir = path if path.is_absolute() else EXE_DIR / path
        self._tts = None
        self.num_steps = 8
        self.device = "cpu"
        self.active_device = ""
        self.last_error = ""
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._tts is not None

    def ensure_running(self) -> bool:
        if self._tts is not None:
            return True
        try:
            from supertonic import TTS

            if self.device == "openvino_gpu":
                self._tts = self._create_openvino_tts("GPU")
                self.active_device = "OpenVINO GPU"
            else:
                self._tts = TTS(
                    model="supertonic-3",
                    model_dir=self.model_dir,
                    auto_download=True,
                )
                self.active_device = "CPU"
            print(f"[Supertonic] 実行デバイス: {self.active_device}")
            self.last_error = ""
            return True
        except Exception as exc:
            self._tts = None
            self.last_error = str(exc)
            print(f"[Supertonic] 初期化失敗: {exc}")
            return False

    def configure_device(self, device: str) -> None:
        target = device if device in {"cpu", "openvino_gpu"} else "cpu"
        if target != self.device:
            self.terminate()
            self.device = target

    @staticmethod
    def available_devices() -> list[tuple[str, str]]:
        devices = [("cpu", "CPU")]
        try:
            import openvino as ov

            if "GPU" in ov.Core().available_devices:
                devices.append(("openvino_gpu", "OpenVINO GPU"))
        except Exception:
            pass
        return devices

    def _create_openvino_tts(self, device: str):
        import onnxruntime as ort
        import supertonic.core as supertonic_core
        import supertonic.loader as supertonic_loader
        from supertonic import TTS

        model_dir = self.model_dir
        if not supertonic_loader.has_all_onnx_modules(model_dir):
            supertonic_loader.download_model(model_dir, "supertonic-3")

        sessions = tuple(
            self._OpenVinoSession(model_dir / relative_path, device)
            for relative_path in supertonic_loader.get_all_onnx_module_relative_paths()
        )

        original_loader = supertonic_loader.load_onnx_modules
        original_session_type = supertonic_core.ort.InferenceSession
        try:
            supertonic_loader.load_onnx_modules = lambda *args, **kwargs: sessions
            supertonic_core.ort.InferenceSession = (
                original_session_type,
                self._OpenVinoSession,
            )
            return TTS(
                model="supertonic-3",
                model_dir=model_dir,
                auto_download=False,
            )
        finally:
            supertonic_loader.load_onnx_modules = original_loader
            supertonic_core.ort.InferenceSession = original_session_type

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
                started_at = time.perf_counter()
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
                elapsed = time.perf_counter() - started_at
                print(f"[Supertonic] 生成時間: {elapsed:.3f}秒")

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
        self.active_device = ""
