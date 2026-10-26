from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.contracts import EngineCapabilities, EngineConfig, SettingField
from livevoicebridge.plugins.provider import Provider

from .engine import VoicevoxEngine

FIELDS = (
    SettingField("url", "接続URL", default="http://127.0.0.1:50021"),
    SettingField("executable_path", "実行ファイル", "file"),
    SettingField("speed", "速度", "number", 1.0, 0.1, 4.0),
    SettingField("pitch", "音程", "number", 0.0, -0.15, 0.15),
    SettingField("volume", "音量", "number", 1.0, 0.0, 4.0),
    SettingField("intonation", "抑揚", "number", 1.0, 0.0, 2.0),
    SettingField("pause_length", "間隔", "number", 1.0, 0.0, 10.0),
    SettingField("pre_phoneme_length", "前の無音", "number", 0.1, 0.0, 5.0),
    SettingField("post_phoneme_length", "後の無音", "number", 0.1, 0.0, 5.0),
)
CAPABILITIES = EngineCapabilities(
    frozenset({"speaker_id", "speed", "pitch", "volume", "echo", "yamabiko", "panning"}),
    True,
    True,
)


class HttpProvider(Provider):
    def validate(self, config: EngineConfig) -> None:
        super().validate(config)
        if not str(config.settings["url"]).startswith(("http://", "https://")):
            raise ValueError("HTTP接続先を指定してください。")
        if int(config.speaker_id) < 0:
            raise ValueError("話者IDが不正です。")


def register(context: PluginContext) -> None:
    context.register(HttpProvider("voicevox", "VOICEVOX", CAPABILITIES, FIELDS, VoicevoxEngine, "1"))
