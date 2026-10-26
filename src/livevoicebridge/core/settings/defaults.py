from livevoicebridge.core.chat.models import StreamingConfig
from livevoicebridge.core.settings.models import SCHEMA_VERSION, AppConfig, PresentationConfig
from livevoicebridge.core.speech.models import EngineConfig, SpeechConfig


def default_config() -> AppConfig:
    return AppConfig(
        schema_version=SCHEMA_VERSION,
        streaming=StreamingConfig(),
        speech=SpeechConfig(active_engine="voicevox", engines=(EngineConfig("voicevox", "1"),)),
        presentation=PresentationConfig(),
    )
