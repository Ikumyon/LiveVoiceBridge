from __future__ import annotations

import html
import io
import os
import re
import wave
import threading
import unicodedata
from pathlib import Path

import numpy as np

from core.tts.base import BaseTTSEngine
from core.app_config import EXE_DIR


class SherpaSupertonicEngine(BaseTTSEngine):
    DISPLAY_NAME = "SUPERTONIC 3"
    DEFAULT_URL = "local://sherpa-supertonic"
    DEFAULT_MODEL_PATH = "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        """Supertonic 3 用のマイグレーション。"""
        if "sherpa_supertonic" not in config or not isinstance(config["sherpa_supertonic"], dict):
            config["sherpa_supertonic"] = {
                "url": cls.DEFAULT_URL,
                "path": cls.DEFAULT_MODEL_PATH,
                "speaker_id": 0
            }
        st = config["sherpa_supertonic"]
        st["url"] = cls.DEFAULT_URL
        st["path"] = cls.DEFAULT_MODEL_PATH
        st.setdefault("speed", loaded_config.get("speed", 1.0))
        st.setdefault("volume", 1.0)
        st.setdefault("max_length", loaded_config.get("max_length", 50))

    REQUIRED_FILES = [
        "duration_predictor.int8.onnx",
        "text_encoder.int8.onnx",
        "vector_estimator.int8.onnx",
        "vocoder.int8.onnx",
        "tts.json",
        "unicode_indexer.bin",
        "voice.bin",
    ]

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url or self.DEFAULT_URL, exe_path)
        # 指定されたモデルパス。相対パスの場合は実行ファイル（EXE_DIR）からの相対パスとして解決
        path_str = exe_path or self.DEFAULT_MODEL_PATH
        self.model_dir = Path(path_str)
        if not self.model_dir.is_absolute():
            self.model_dir = EXE_DIR / self.model_dir

        self._tts = None
        self.last_error = ""
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """TTSインスタンスの初期化が完了しているか確認する。"""
        return self._tts is not None

    def ensure_running(self) -> bool:
        """モデルファイルをチェックし、TTSインスタンスをロード（初期化）する。"""
        if not self._check_model_files():
            return False
        return self._load_tts()

    def _check_model_files(self) -> bool:
        """必要なファイルがすべて揃っているか確認。"""
        if not self.model_dir.exists() or not self.model_dir.is_dir():
            return False
        return all(
            (self.model_dir / name).exists() for name in self.REQUIRED_FILES
        )

    def _load_tts(self) -> bool:
        """sherpa_onnx の TTS インスタンスを生成して保持する。"""
        if self._tts is not None:
            return True
        try:
            import sherpa_onnx

            model_dir = self.model_dir
            try:
                model_dir = self.model_dir.relative_to(Path.cwd())
            except ValueError:
                pass

            supertonic_config = sherpa_onnx.OfflineTtsSupertonicModelConfig(
                duration_predictor=str(model_dir / "duration_predictor.int8.onnx"),
                text_encoder=str(model_dir / "text_encoder.int8.onnx"),
                vector_estimator=str(model_dir / "vector_estimator.int8.onnx"),
                vocoder=str(model_dir / "vocoder.int8.onnx"),
                tts_json=str(model_dir / "tts.json"),
                unicode_indexer=str(model_dir / "unicode_indexer.bin"),
                voice_style=str(model_dir / "voice.bin"),
            )

            # OfflineTtsConfig 組み立て
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    supertonic=supertonic_config,
                    num_threads=2,
                    provider="cpu",
                    debug=False,
                )
            )
            self._tts = sherpa_onnx.OfflineTts(config)
            self.last_error = ""
            return True
        except Exception as exc:
            self._tts = None
            self.last_error = str(exc)
            print(f"[Supertonic3] 初期化失敗: {exc}")
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
        """音声を合成して WAV のバイトデータを返す。"""
        if not text.strip():
            return None

        # デフォルト値
        target_speed = speed if speed is not None else 1.0
        target_volume = volume if volume is not None else 1.0
        target_speaker = speaker_id if speaker_id is not None else 0

        try:
            if not self.ensure_running():
                raise RuntimeError("Supertonic 3 model files are missing or libraries are not installed")

            with self._lock:
                japanese_text = self._prepare_japanese_text(text)
                print(f"[Supertonic3] TTS入力: {japanese_text}")
                import sherpa_onnx

                generation_config = sherpa_onnx.GenerationConfig()
                generation_config.sid = int(target_speaker)
                generation_config.num_steps = 8
                generation_config.speed = float(target_speed)
                generation_config.extra = {"lang": "ja"}

                audio = self._tts.generate(
                    japanese_text,
                    generation_config,
                )
                if not audio or not audio.samples:
                    raise RuntimeError("sherpa-onnx generated audio is empty")

                # float32 から int16 に変換してボリューム調整
                samples = np.asarray(audio.samples)
                samples = np.clip(samples * 32767.0 * target_volume, -32768, 32767).astype(np.int16)
                
                return self._pcm_to_wav_bytes(samples, audio.sample_rate)

        except Exception as e:
            print(f"[Supertonic3] 合成失敗: {e}")
            return None

    @staticmethod
    def _prepare_japanese_text(text: str) -> str:
        """言語タグを本文から除去し、通常の日本語テキストへ整える。"""
        normalized = html.unescape(text)
        normalized = re.sub(r"</?ja\s*>", "", normalized, flags=re.IGNORECASE)
        normalized = unicodedata.normalize("NFKC", normalized).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized:
            return ""
        if not re.search(r"[.!?;:,'\"')\]}…。」』〗〉》›»]$", normalized):
            normalized += "。"
        return normalized

    def _pcm_to_wav_bytes(self, samples: np.ndarray, sr: int) -> bytes:
        """PCMデータ(int16)をWAVバイト配列に変換。"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(samples.tobytes())
        return buf.getvalue()

    def get_speakers(self) -> list[dict] | None:
        """Supertonic 3 の話者リスト。マルチスピーカーとして 10 人の話者を定義。"""
        return [{
            "name": "Supertonic 3 Japanese",
            "styles": [{"name": f"Speaker {i}", "id": i} for i in range(10)]
        }]
