"""Conversions for released configuration schemas; no filesystem operations."""

from typing import Any


def upgrade_schema1(document: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Convert schema 1 to the official schema before any file is changed."""
    try:
        values = dict(document)
        values["schema_version"] = 2
        values.setdefault("resources", defaults["resources"])
        speech = dict(document["speech"])
        speech.setdefault("queue_limit", defaults["speech"]["queue_limit"])
        templates = {engine["kind"]: engine for engine in defaults["speech"]["engines"]}
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
            allowed = set(templates[kind])
            migrated = dict(templates[kind])
            migrated.update({key: value for key, value in engine.items() if key in allowed})
            if kind in ("voicevox", "coeiroink"):
                for key in ("intonation", "pause_length", "pre_phoneme_length", "post_phoneme_length"):
                    if migrated[key] is None:
                        migrated[key] = templates[kind][key]
            if kind == "bouyomichan":
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


def legacy_defaults(defaults: dict[str, Any]) -> dict[str, Any]:
    """Schema 2 templates exist only for converting released settings."""
    common = dict(
        url="http://127.0.0.1:50021",
        executable_path="",
        speaker_id=1,
        max_length=50,
        speed=1.0,
        pitch=0.0,
        volume=1.0,
        intonation=1.0,
        pause_length=1.0,
        pre_phoneme_length=0.1,
        post_phoneme_length=0.1,
    )
    return {
        **defaults,
        "schema_version": 2,
        "speech": {
            **defaults["speech"],
            "engines": [
                dict(common, kind="voicevox"),
                dict(common, kind="coeiroink", url="http://127.0.0.1:50032"),
                dict(
                    kind="bouyomichan",
                    url="127.0.0.1:50001",
                    executable_path="",
                    speaker_id=0,
                    max_length=50,
                    speed=-1,
                    pitch=-1,
                    volume=-1,
                ),
                dict(kind="qwen3", model_path="", device="GPU", speaker_id=0, max_length=50, volume=1.0),
            ],
        },
    }


def upgrade_schema2(document: dict[str, Any]) -> dict[str, Any]:
    values = dict(document)
    speech = dict(document["speech"])
    engines = []
    for item in speech["engines"]:
        engine = dict(item)
        kind = engine.pop("kind")
        speaker = engine.pop("speaker_id")
        if type(speaker) is not int or speaker < 0:
            raise ValueError("旧設定の話者IDが不正です。")
        engines.append(
            dict(engine_id=kind, speaker_id=str(speaker), max_length=engine.pop("max_length"), settings=engine)
        )
    speech["engines"] = engines
    application = dict(values["application"])
    application.setdefault("plugin_enabled", [])
    values.update(schema_version=3, speech=speech, application=application)
    return values
