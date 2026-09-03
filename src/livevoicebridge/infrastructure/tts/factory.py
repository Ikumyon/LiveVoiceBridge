from __future__ import annotations

from livevoicebridge.infrastructure.tts.base import BaseTTSEngine
from livevoicebridge.infrastructure.tts.engines.bouyomichan import BouyomiChanEngine
from livevoicebridge.infrastructure.tts.engines.coeiroink import CoeiroinkEngine
from livevoicebridge.infrastructure.tts.engines.supertonic import SupertonicEngine
from livevoicebridge.infrastructure.tts.engines.supertonic_lightweight import SupertonicLightweightEngine
from livevoicebridge.infrastructure.tts.engines.voicevox import VoicevoxEngine

ENGINE_CLASSES: dict[str, type[BaseTTSEngine]] = {
    "voicevox": VoicevoxEngine,
    "coeiroink": CoeiroinkEngine,
    "bouyomichan": BouyomiChanEngine,
    "supertonic": SupertonicEngine,
    "supertonic_lightweight": SupertonicLightweightEngine,
}


def get_engine_class(engine_type: str) -> type[BaseTTSEngine]:
    """Return the explicitly selected engine class."""
    try:
        return ENGINE_CLASSES[engine_type.lower()]
    except KeyError as exc:
        raise ValueError(f"未対応のTTSエンジンです: {engine_type}") from exc


def get_engine_instance(engine_type: str, url: str, exe_path: str = "") -> BaseTTSEngine:
    """指定された名前のエンジンインスタンスを生成して返す。"""
    engine_class = get_engine_class(engine_type)
    return engine_class(url, exe_path)
