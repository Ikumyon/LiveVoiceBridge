from __future__ import annotations

import io
import os
import wave
import threading
from pathlib import Path

import numpy as np

from core.tts.base import BaseTTSEngine
from core.app_config import EXE_DIR


class SherpaSupertonicEngine(BaseTTSEngine):
    DISPLAY_NAME = "SUPERTONIC 3"
    DEFAULT_URL = "local://sherpa-supertonic"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

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
        path_str = exe_path or "models/sherpa-onnx-supertonic-3-ja-int8"
        self.model_dir = Path(path_str)
        if not self.model_dir.is_absolute():
            self.model_dir = EXE_DIR / self.model_dir

        self._tts = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """モデルディレクトリおよび必要なファイルが存在し、かつライブラリがインポート可能か確認する。"""
        return self._check_model_files()

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
            # CPU実行時のスレッド数はデフォルトで2とする
            num_threads = 2
            
            # OfflineTtsConfig 組み立て
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                        model_dir=str(self.model_dir),
                        num_threads=num_threads,
                    ),
                    provider="cpu",
                    debug=False,
                )
            )
            self._tts = sherpa_onnx.OfflineTts(config)
            return True
        except Exception:
            self._tts = None
            return False

    def synthesize_wav(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        volume: float = None,
        speaker_id: int = None,
    ) -> bytes | None:
        """音声を合成して WAV のバイトデータを返す。失敗時は pyopenjtalk フォールバックを行う。"""
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
                import sherpa_onnx
                
                # 音声合成用設定
                gen_config = sherpa_onnx.OfflineTtsGenerateConfig(
                    speaker_id=target_speaker,
                    speed=target_speed,
                )
                
                audio = self._tts.generate(text, gen_config)
                if not audio or not audio.samples:
                    raise RuntimeError("sherpa-onnx generated audio is empty")

                # float32 から int16 に変換してボリューム調整
                samples = np.asarray(audio.samples)
                samples = np.clip(samples * 32767.0 * target_volume, -32768, 32767).astype(np.int16)
                
                return self._pcm_to_wav_bytes(samples, audio.sample_rate)

        except Exception as e:
            print(f"[Supertonic3] 合成失敗: {e}. pyopenjtalk fallback を実行します。")
            return self._fallback_pyopenjtalk(text, speed=target_speed, volume=target_volume)

    def _fallback_pyopenjtalk(self, text: str, speed: float = 1.0, volume: float = 1.0) -> bytes | None:
        """pyopenjtalk によるフォールバック音声合成（日本語パス/文字化け問題を回避する実装）。"""
        try:
            import pyopenjtalk
            import site
            import shutil
            import tempfile
            
            # 日本語パス問題（MecabおよびHTS_Engineのロードエラー）を回避するため、
            # 辞書ファイルとボイスモデルファイルを一時フォルダ（Temp）にコピーして使用する
            temp_dir = tempfile.gettempdir()
            dest_dict_dir = os.path.join(temp_dir, "open_jtalk_dic_utf_8-1.11")
            dest_voice_file = os.path.join(temp_dir, "mei_normal.htsvoice")
            
            # まだ一時フォルダにファイルが存在しない場合のみコピーを実行
            if not os.path.exists(dest_dict_dir) or not os.path.exists(dest_voice_file):
                site_dirs = site.getsitepackages()
                dict_src = None
                voice_src = None
                for d in site_dirs:
                    p_dict = os.path.join(d, "pyopenjtalk", "open_jtalk_dic_utf_8-1.11")
                    p_voice = os.path.join(d, "pyopenjtalk", "htsvoice", "mei_normal.htsvoice")
                    if os.path.exists(p_dict) and os.path.exists(p_voice):
                        dict_src = p_dict
                        voice_src = p_voice
                        break
                
                if dict_src and voice_src:
                    if not os.path.exists(dest_dict_dir):
                        shutil.copytree(dict_src, dest_dict_dir)
                    if not os.path.exists(dest_voice_file):
                        shutil.copy2(voice_src, dest_voice_file)
                else:
                    raise RuntimeError("Could not find pyopenjtalk assets in site-packages.")

            # 環境変数 OPEN_JTALK_DICT_DIR を一時フォルダのパスに設定（これで Mecab_load 成功する）
            os.environ["OPEN_JTALK_DICT_DIR"] = dest_dict_dir

            # ラベルの抽出（Temp辞書を用いるため成功）
            labels = pyopenjtalk.extract_fullcontext(text)
            if not labels:
                return None

            # HTSEngine を Temp のボイスファイルでインスタンス化（これで HTS_fopen 成功する）
            engine = pyopenjtalk.HTSEngine(dest_voice_file.encode("utf-8"))
            engine.set_speed(speed)
            
            # 音声合成を実行し、サンプルレートを取得
            waveform = engine.synthesize(labels)
            sr = engine.get_sampling_frequency()
            
            samples = np.asarray(waveform)
            # 音量調整とクリッピング、キャスト
            samples = np.clip(samples * volume, -32768, 32767).astype(np.int16)

            return self._pcm_to_wav_bytes(samples, sr)
        except Exception as e:
            print(f"[Supertonic3] pyopenjtalk fallback も失敗しました: {e}")
            return None

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
