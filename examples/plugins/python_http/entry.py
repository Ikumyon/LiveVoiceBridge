"""Example endpoint: POST JSON {text, voice} -> WAV. Adapt to your TTS API."""

import requests

from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.contracts import EngineCapabilities, EngineConfig, SettingField, Speaker, SpeechControls
from livevoicebridge.plugins.provider import Provider


class HttpEngine:
    def __init__(self, context: PluginContext, config: EngineConfig):
        self.context, self.config = context, config

    def ensure_ready(self) -> None:
        pass

    def speakers(self) -> tuple[Speaker, ...]:
        return (Speaker("default", "標準話者"),)

    def synthesize(self, text: str, controls: SpeechControls, config: EngineConfig, max_bytes: int):
        with requests.post(
            str(config.settings["url"]),
            json={"text": text, "voice": controls.speaker_id or config.speaker_id},
            timeout=(5, 120),
            stream=True,
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                if len(content) + len(chunk) > max_bytes + 65536:
                    raise ValueError("音声が容量上限を超えました。")
                content.extend(chunk)
            return self.context.decode_wav(bytes(content), controls, max_bytes)

    def close(self) -> None:
        pass


def register(context: PluginContext) -> None:
    context.register(
        Provider(
            context.id,
            "HTTP WAV 作成例",
            EngineCapabilities(frozenset({"speaker_id", "echo", "yamabiko", "panning"}), True, True),
            (SettingField("url", "合成エンドポイント", default="http://127.0.0.1:8000/synthesize"),),
            lambda config: HttpEngine(context, config),
            "default",
        )
    )
