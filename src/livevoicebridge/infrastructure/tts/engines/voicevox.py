import requests

from livevoicebridge.infrastructure.tts.base import BaseTTSEngine


class VoicevoxEngine(BaseTTSEngine):
    """VOICEVOX 用の音声合成エンジン。"""

    DISPLAY_NAME = "VOICEVOX"
    DEFAULT_URL = "http://127.0.0.1:50021"

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
