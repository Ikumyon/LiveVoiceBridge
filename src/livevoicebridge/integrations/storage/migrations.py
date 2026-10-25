"""Conversions for released configuration schemas; no filesystem operations."""

from dataclasses import fields
from typing import Any

from livevoicebridge.core.speech.models import (
    BouyomiConfig,
    CoeiroinkConfig,
    Qwen3Config,
    TtsEngineKind,
    VoicevoxConfig,
)


def upgrade_schema1(document: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Convert schema 1 to the official schema before any file is changed."""
    try:
        values = dict(document)
        values["schema_version"] = 2
        values.setdefault("resources", defaults["resources"])
        speech = dict(document["speech"])
        speech.setdefault("queue_limit", defaults["speech"]["queue_limit"])
        templates = {engine["kind"]: engine for engine in defaults["speech"]["engines"]}
        engine_types = {
            TtsEngineKind.VOICEVOX: VoicevoxConfig,
            TtsEngineKind.COEIROINK: CoeiroinkConfig,
            TtsEngineKind.BOUYOMICHAN: BouyomiConfig,
            TtsEngineKind.QWEN3: Qwen3Config,
        }
        retired = {"supertonic", "supertonic_lightweight"}
        converted: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for engine in speech["engines"]:
            if not isinstance(engine, dict) or not isinstance(engine.get("kind"), str):
                raise ValueError("エンジン設定の形式が不正です。")
            kind = engine["kind"]
            if kind in seen:
                raise ValueError(f"エンジン設定が重複しています: {kind}")
            seen.add(kind)
            if kind in retired:
                continue
            engine_type = engine_types[TtsEngineKind(kind)]
            allowed = {item.name for item in fields(engine_type)}
            migrated = dict(templates[kind])
            migrated.update({key: value for key, value in engine.items() if key in allowed})
            if kind in (TtsEngineKind.VOICEVOX, TtsEngineKind.COEIROINK):
                for key in ("intonation", "pause_length", "pre_phoneme_length", "post_phoneme_length"):
                    if migrated[key] is None:
                        migrated[key] = templates[kind][key]
            if kind == TtsEngineKind.BOUYOMICHAN:
                for key in ("speed", "pitch", "volume"):
                    value = migrated[key]
                    if type(value) is float:
                        if not value.is_integer():
                            raise ValueError(f"棒読みちゃんの{key}を整数へ変換できません。")
                        migrated[key] = int(value)
            converted[kind] = migrated
        speech["engines"] = [converted.get(kind, template) for kind, template in templates.items()]
        if speech["active_engine"] in retired:
            speech["active_engine"] = defaults["speech"]["active_engine"]
        values["speech"] = speech
        return values
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"スキーマ1の設定を2へ変換できません: {exc}") from exc
