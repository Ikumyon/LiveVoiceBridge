from livevoicebridge.core.chat.models import StreamingConfig
from livevoicebridge.core.settings.models import SCHEMA_VERSION, AppConfig, PresentationConfig
from livevoicebridge.core.speech.models import (
    BouyomiConfig,
    CoeiroinkConfig,
    Qwen3Config,
    SpeechConfig,
    TtsEngineKind,
    VoicevoxConfig,
)


def default_config() -> AppConfig:
    return AppConfig(
        schema_version=SCHEMA_VERSION,
        streaming=StreamingConfig(),
        speech=SpeechConfig(
            active_engine=TtsEngineKind.VOICEVOX,
            engines=(
                VoicevoxConfig(url="http://127.0.0.1:50021", speaker_id=1),
                CoeiroinkConfig(url="http://127.0.0.1:50032", speaker_id=1),
                BouyomiConfig(url="127.0.0.1:50001"),
                Qwen3Config(),
            ),
        ),
        presentation=PresentationConfig(),
    )
