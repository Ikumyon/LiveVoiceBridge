from __future__ import annotations
from core.tts.base import BaseTTSEngine
from core.tts.engines.voicevox import VoicevoxEngine
from core.tts.engines.coeiroink import CoeiroinkEngine
from core.tts.engines.bouyomichan import BouyomiChanEngine
from core.tts.engines.sherpa_supertonic import SherpaSupertonicEngine

ENGINE_CLASSES: dict[str, type[BaseTTSEngine]] = {
    "voicevox": VoicevoxEngine,
    "coeiroink": CoeiroinkEngine,
    "bouyomichan": BouyomiChanEngine,
    "sherpa_supertonic": SherpaSupertonicEngine,
}

def get_engine_class(engine_type: str) -> type[BaseTTSEngine]:
    """指定された名前のエンジンクラスを返す。見つからない場合は VoicevoxEngine をデフォルトとする。"""
    return ENGINE_CLASSES.get(engine_type.lower(), VoicevoxEngine)

def get_engine_instance(engine_type: str, url: str, exe_path: str = "") -> BaseTTSEngine:
    """指定された名前のエンジンインスタンスを生成して返す。"""
    engine_class = get_engine_class(engine_type)
    return engine_class(url, exe_path)

def migrate_all_configs(config: dict, loaded_config: dict) -> None:
    """登録されているすべてのエンジン固有のマイグレーション処理を実行する。"""
    for engine_class in ENGINE_CLASSES.values():
        engine_class.migrate_config(config, loaded_config)
