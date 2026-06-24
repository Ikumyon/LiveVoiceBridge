import requests
from core.tts.base import BaseTTSEngine

class CoeiroinkEngine(BaseTTSEngine):
    """COEIROINK 用の音声合成エンジン。
    
    COEIROINK v2 (HTTP API) は VOICEVOX と互換性のあるエンドポイントを持ちます。
    """
    DISPLAY_NAME = "COEIROINK"
    DEFAULT_URL = "http://127.0.0.1:50032"

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        """COEIROINK 用のマイグレーション。"""
        if "coeiroink" not in config or not isinstance(config["coeiroink"], dict):
            config["coeiroink"] = {
                "url": cls.DEFAULT_URL,
                "path": "",
                "speaker_id": 1
            }
        coe = config["coeiroink"]
        
        # 新しい固有設定値のマイグレーション
        coe.setdefault("speed", loaded_config.get("speed", 1.0))
        coe.setdefault("pitch", 0.0)
        coe.setdefault("intonation", 1.0)
        coe.setdefault("volume", 1.0)
        coe.setdefault("pause_length", 1.0)
        coe.setdefault("pre_phoneme_length", 0.1)
        coe.setdefault("post_phoneme_length", 0.1)
        coe.setdefault("max_length", loaded_config.get("max_length", 50))
    
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
        try:
            query_response = requests.post(
                f"{self.url}/audio_query",
                params={"text": text, "speaker": speaker_id},
                timeout=10,
            )
            query_response.raise_for_status()
            audio_query = query_response.json()
            
            if speed is not None:
                audio_query["speedScale"] = speed
            if pitch is not None:
                audio_query["pitchScale"] = pitch
            if intonation is not None:
                audio_query["intonationScale"] = intonation
            if volume is not None:
                audio_query["volumeScale"] = volume
            if pause_length is not None:
                audio_query["pauseLengthScale"] = pause_length
            if pre_phoneme_length is not None:
                audio_query["prePhonemeLength"] = pre_phoneme_length
            if post_phoneme_length is not None:
                audio_query["postPhonemeLength"] = post_phoneme_length

            synthesis_response = requests.post(
                f"{self.url}/synthesis",
                params={"speaker": speaker_id},
                json=audio_query,
                timeout=30,
            )
            synthesis_response.raise_for_status()
            return synthesis_response.content
        except Exception:
            return None

    def get_speakers(self) -> list[dict] | None:
        try:
            response = requests.get(f"{self.url}/speakers", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None
