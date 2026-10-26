from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.contracts import EngineCapabilities, EngineConfig, SettingField
from livevoicebridge.plugins.provider import Provider

from .engine import BouyomiChanEngine


class BouyomiProvider(Provider):
    def validate(self, config: EngineConfig) -> None:
        super().validate(config)
        if not 0 <= int(config.speaker_id) <= 32767:
            raise ValueError("話者IDが範囲外です。")


def register(context: PluginContext) -> None:
    context.register(
        BouyomiProvider(
            "bouyomichan",
            "棒読みちゃん",
            EngineCapabilities(frozenset({"speaker_id", "speed", "pitch", "volume"}), False, False),
            (
                SettingField("url", "接続先", default="127.0.0.1:50001"),
                SettingField("executable_path", "実行ファイル", "file"),
                SettingField("speed", "速度", "integer", -1, -1, 32767),
                SettingField("pitch", "音程", "integer", -1, -1, 32767),
                SettingField("volume", "音量", "integer", -1, -1, 32767),
            ),
            BouyomiChanEngine,
        )
    )
