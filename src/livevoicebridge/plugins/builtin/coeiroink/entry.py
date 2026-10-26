from dataclasses import replace

from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.builtin.voicevox.engine import VoicevoxEngine
from livevoicebridge.plugins.builtin.voicevox.entry import CAPABILITIES, FIELDS, HttpProvider


def register(context: PluginContext) -> None:
    fields = tuple(
        replace(field, default="http://127.0.0.1:50032") if field.key == "url" else field for field in FIELDS
    )
    context.register(HttpProvider("coeiroink", "COEIROINK", CAPABILITIES, fields, VoicevoxEngine, "1"))
