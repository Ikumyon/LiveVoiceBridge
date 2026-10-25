import requests

from livevoicebridge.core.speech.models import AudioData, EngineConfig, Qwen3Config, Speaker, SpeechControls
from livevoicebridge.integrations.native.audio import decode_response
from livevoicebridge.integrations.qwen.runtime import QwenManager


class Qwen3Engine:
    def __init__(self, runtime: QwenManager):
        self._runtime = runtime

    def ensure_ready(self) -> None:
        """Readiness is awaited only by the synthesis worker, never the session lane."""

    def speakers(self) -> tuple[Speaker, ...]:
        url, headers = self._runtime.connection()
        response = requests.get(f"{url}/voices", headers=headers, timeout=(2, 5))
        response.raise_for_status()
        return tuple(Speaker(int(voice["id"]), str(voice["name"])) for voice in response.json())

    def synthesize(self, text: str, controls: SpeechControls, config: EngineConfig, max_bytes: int) -> AudioData:
        if not isinstance(config, Qwen3Config):
            raise TypeError("Qwen3の設定が必要です。")
        if controls.speed is not None or controls.pitch is not None:
            raise ValueError("Qwen3は速度・音程の指定に対応していません。")
        url, headers = self._runtime.connection()
        response = requests.post(
            f"{url}/synthesize",
            headers=headers,
            json={
                "text": text,
                "voice_id": controls.speaker_id if controls.speaker_id is not None else config.speaker_id,
                "volume": controls.volume if controls.volume is not None else config.volume,
            },
            timeout=(5, 120),
            stream=True,
        )
        if not response.ok:
            status = response.status_code
            response.close()
            raise RuntimeError(f"Qwen3-TTS合成失敗 ({status})")
        return decode_response(response, controls, max_bytes)

    def close(self) -> None:
        """The dedicated service owns its model and process."""
