import requests
from core.tts_engines import BaseTTSEngine

class VoicevoxEngine(BaseTTSEngine):
    """VOICEVOX 用の音声合成エンジン。"""
    DEFAULT_URL = "http://127.0.0.1:50021"

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        """旧フラット構造の設定を VOICEVOX 用のネスト構造にマイグレーションし、旧キーを削除する。"""
        if "voicevox" not in config or not isinstance(config["voicevox"], dict):
            config["voicevox"] = {
                "url": cls.DEFAULT_URL,
                "path": "",
                "speaker_id": 1
            }
        
        if "voicevox_url" in loaded_config:
            config["voicevox"]["url"] = loaded_config["voicevox_url"]
        if "voicevox_path" in loaded_config:
            config["voicevox"]["path"] = loaded_config["voicevox_path"]
        if "speaker_id" in loaded_config:
            config["voicevox"]["speaker_id"] = loaded_config["speaker_id"]

        # 旧仕様のフラットキーを削除
        config.pop("voicevox_url", None)
        config.pop("voicevox_path", None)
        config.pop("speaker_id", None)
    
    def synthesize_wav(self, text: str, speed: float = None, pitch: float = None, volume: float = None, speaker_id: int = None) -> bytes | None:
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
            if volume is not None:
                audio_query["volumeScale"] = volume
                
            audio_query["intonationScale"] = 1.05

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
