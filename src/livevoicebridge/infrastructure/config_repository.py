"""Versioned, atomic JSON configuration persistence."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from livevoicebridge.application.models import (
    AppConfig,
    ApplicationConfig,
    DictionaryConfig,
    EngineConfig,
    PopupMetricsConfig,
    PresentationConfig,
    ReadBlock,
    ReadBlockKind,
    SpeechConfig,
    StreamingConfig,
    TtsEngineKind,
)

SCHEMA_VERSION = 1


class ConfigError(RuntimeError):
    """Raised when the official configuration cannot be read or validated."""


def default_config() -> AppConfig:
    engines = (
        EngineConfig(
            kind=TtsEngineKind.VOICEVOX,
            url="http://127.0.0.1:50021",
            speaker_id=1,
            intonation=1.0,
            pause_length=1.0,
            pre_phoneme_length=0.1,
            post_phoneme_length=0.1,
        ),
        EngineConfig(
            kind=TtsEngineKind.COEIROINK,
            url="http://127.0.0.1:50032",
            speaker_id=1,
            intonation=1.0,
            pause_length=1.0,
            pre_phoneme_length=0.1,
            post_phoneme_length=0.1,
        ),
        EngineConfig(
            kind=TtsEngineKind.BOUYOMICHAN,
            url="127.0.0.1:50001",
            speed=-1,
            pitch=-1,
            volume=-1,
        ),
        EngineConfig(
            kind=TtsEngineKind.SUPERTONIC_LIGHTWEIGHT,
            url="local://supertonic-lightweight",
            model_path="models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
            num_steps=8,
            num_threads=2,
            device="auto",
            device_policy="auto",
            device_priority=("NPU", "GPU", "CPU"),
            backend="sherpa_onnx",
        ),
        EngineConfig(
            kind=TtsEngineKind.SUPERTONIC,
            url="local://supertonic",
            model_path="models/supertonic-3",
            num_steps=8,
            backend="supertonic_sdk",
        ),
    )
    return AppConfig(
        schema_version=SCHEMA_VERSION,
        streaming=StreamingConfig(),
        speech=SpeechConfig(active_engine=TtsEngineKind.VOICEVOX, engines=engines),
        presentation=PresentationConfig(),
    )


class JsonConfigRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = default_config()
            self.save(config)
            return config

        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"設定ファイルを読み込めません: {self.path}") from exc
        if not isinstance(document, dict):
            raise ConfigError("設定ファイルのルートはJSONオブジェクトである必要があります。")

        if "schema_version" not in document:
            config = self._migrate_legacy(document)
            self._backup_legacy()
            self.save(config)
            return config
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ConfigError(f"未対応の設定スキーマです: {document.get('schema_version')}")
        return self._decode(document)

    def save(self, config: AppConfig) -> None:
        document = self._encode(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ConfigError(f"設定ファイルを保存できません: {self.path}") from exc

    def _backup_legacy(self) -> None:
        backup = self.path.with_name(f"{self.path.stem}.legacy{self.path.suffix}")
        if not backup.exists():
            shutil.copy2(self.path, backup)

    @staticmethod
    def _encode(config: AppConfig) -> dict[str, Any]:
        document = asdict(config)
        document["speech"]["active_engine"] = config.speech.active_engine.value
        for index, engine in enumerate(config.speech.engines):
            document["speech"]["engines"][index]["kind"] = engine.kind.value
        for index, block in enumerate(config.speech.read_blocks):
            document["speech"]["read_blocks"][index]["kind"] = block.kind.value
        document["presentation"]["popup_metrics"]["display_modes"] = dict(
            config.presentation.popup_metrics.display_modes
        )
        return document

    @staticmethod
    def _decode(document: dict[str, Any]) -> AppConfig:
        try:
            streaming_data = document["streaming"]
            speech_data = document["speech"]
            presentation_data = document["presentation"]
            engines = tuple(JsonConfigRepository._decode_engine(item) for item in speech_data["engines"])
            engine_kinds = tuple(engine.kind for engine in engines)
            if len(engine_kinds) != len(set(engine_kinds)) or set(engine_kinds) != set(TtsEngineKind):
                raise ValueError("TTSエンジン設定は対応エンジンを重複なくすべて含める必要があります")
            read_blocks = tuple(JsonConfigRepository._decode_read_block(item) for item in speech_data["read_blocks"])
            popup_data = presentation_data.get("popup_metrics", {})
            popup = PopupMetricsConfig(
                placement=str(popup_data.get("placement", "top")),
                vertical_ratio=float(popup_data.get("vertical_ratio", 0.35)),
                horizontal_ratio=float(popup_data.get("horizontal_ratio", 0.35)),
                display_modes=tuple(sorted(dict(popup_data.get("display_modes", {})).items())),
            )
            presentation = PresentationConfig(
                comment_popout=bool(presentation_data.get("comment_popout", False)),
                comment_opacity=float(presentation_data.get("comment_opacity", 0.8)),
                header_opacity=float(presentation_data.get("header_opacity", 0.8)),
                border_opacity=float(presentation_data.get("border_opacity", 0.8)),
                background_color=str(presentation_data.get("background_color", "#1e1e1e")),
                border_color=str(presentation_data.get("border_color", "#3c3c3c")),
                popup_metrics=popup,
                window_x=_optional_int(presentation_data.get("window_x")),
                window_y=_optional_int(presentation_data.get("window_y")),
                window_width=int(presentation_data.get("window_width", 360)),
                window_height=int(presentation_data.get("window_height", 500)),
            )
            dictionary_data = document.get("dictionary", {})
            application_data = document.get("application", {})
            config = AppConfig(
                schema_version=int(document["schema_version"]),
                streaming=StreamingConfig(
                    youtube_api_key=str(streaming_data.get("youtube_api_key", "")),
                    youtube_source=str(streaming_data.get("youtube_source", "")),
                    skip_history=bool(streaming_data.get("skip_history", True)),
                    read_paid_events=bool(streaming_data.get("read_paid_events", True)),
                ),
                speech=SpeechConfig(
                    active_engine=TtsEngineKind(speech_data["active_engine"]),
                    engines=engines,
                    read_blocks=read_blocks or (ReadBlock(ReadBlockKind.MESSAGE),),
                ),
                presentation=presentation,
                dictionary=DictionaryConfig(active_group=str(dictionary_data.get("active_group", "デフォルト"))),
                application=ApplicationConfig(
                    check_updates=bool(application_data.get("check_updates", True)),
                    use_ime=bool(application_data.get("use_ime", False)),
                ),
            )
            config.speech.engine()
            return config
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"設定値が不正です: {exc}") from exc

    @staticmethod
    def _decode_engine(data: dict[str, Any]) -> EngineConfig:
        return EngineConfig(
            kind=TtsEngineKind(data["kind"]),
            url=str(data.get("url", "")),
            executable_path=str(data.get("executable_path", "")),
            model_path=str(data.get("model_path", "")),
            speaker_id=int(data.get("speaker_id", 0)),
            speed=float(data.get("speed", 1.0)),
            pitch=float(data.get("pitch", 0.0)),
            intonation=_optional_float(data.get("intonation")),
            volume=float(data.get("volume", 1.0)),
            pause_length=_optional_float(data.get("pause_length")),
            pre_phoneme_length=_optional_float(data.get("pre_phoneme_length")),
            post_phoneme_length=_optional_float(data.get("post_phoneme_length")),
            max_length=int(data.get("max_length", 50)),
            num_steps=_optional_int(data.get("num_steps")),
            num_threads=_optional_int(data.get("num_threads")),
            device=str(data.get("device", "cpu")),
            device_policy=str(data.get("device_policy", "auto")),
            device_priority=tuple(str(value) for value in data.get("device_priority", ())),
            backend=str(data.get("backend", "")),
        )

    @staticmethod
    def _decode_read_block(data: dict[str, Any]) -> ReadBlock:
        return ReadBlock(ReadBlockKind(data["kind"]), str(data.get("value", "")))

    @staticmethod
    def _migrate_legacy(document: dict[str, Any]) -> AppConfig:
        base = default_config()
        engines = tuple(_migrate_engine(document.get(engine.kind.value, {}), engine) for engine in base.speech.engines)
        popup_data = document.get("popup_metrics", {})
        display_modes = popup_data.get("display_modes", {}) if isinstance(popup_data, dict) else {}
        read_blocks = _migrate_read_blocks(document.get("read_blocks"))
        return AppConfig(
            schema_version=SCHEMA_VERSION,
            streaming=StreamingConfig(
                youtube_api_key=str(document.get("youtube_api_key", "")),
                youtube_source=str(document.get("youtube_url", "")),
                skip_history=bool(document.get("skip_history", True)),
                read_paid_events=bool(document.get("read_super_chat", True)),
            ),
            speech=SpeechConfig(
                active_engine=TtsEngineKind(str(document.get("tts_engine", "voicevox"))),
                engines=engines,
                read_blocks=read_blocks,
            ),
            presentation=PresentationConfig(
                comment_popout=bool(document.get("comment_popout", False)),
                comment_opacity=float(document.get("comment_opacity", 0.8)),
                header_opacity=float(document.get("comment_header_opacity", 0.8)),
                border_opacity=float(document.get("comment_border_opacity", 0.8)),
                background_color=str(document.get("comment_bg_color", "#1e1e1e")),
                border_color=str(document.get("comment_border_color", "#3c3c3c")),
                popup_metrics=PopupMetricsConfig(
                    placement=str(popup_data.get("placement", "top")),
                    vertical_ratio=float(popup_data.get("vertical_ratio", 0.35)),
                    horizontal_ratio=float(popup_data.get("horizontal_ratio", 0.35)),
                    display_modes=tuple(sorted(dict(display_modes).items())),
                ),
                window_x=_optional_int(document.get("comment_win_x")),
                window_y=_optional_int(document.get("comment_win_y")),
                window_width=int(document.get("comment_win_w", 360)),
                window_height=int(document.get("comment_win_h", 500)),
            ),
            dictionary=DictionaryConfig(active_group=str(document.get("dict_group", "デフォルト"))),
            application=ApplicationConfig(
                check_updates=bool(document.get("check_updates", True)),
                use_ime=bool(document.get("use_ime", False)),
            ),
        )


def _migrate_engine(data: object, default: EngineConfig) -> EngineConfig:
    values = data if isinstance(data, dict) else {}
    return EngineConfig(
        kind=default.kind,
        url=str(values.get("url", default.url)),
        executable_path=str(values.get("path", default.executable_path)),
        model_path=str(values.get("path", default.model_path)) if default.model_path else "",
        speaker_id=int(values.get("speaker_id", default.speaker_id)),
        speed=float(values.get("speed", default.speed)),
        pitch=float(values.get("pitch", default.pitch)),
        intonation=_optional_float(values.get("intonation", default.intonation)),
        volume=float(values.get("volume", default.volume)),
        pause_length=_optional_float(values.get("pause_length", default.pause_length)),
        pre_phoneme_length=_optional_float(values.get("pre_phoneme_length", default.pre_phoneme_length)),
        post_phoneme_length=_optional_float(values.get("post_phoneme_length", default.post_phoneme_length)),
        max_length=int(values.get("max_length", default.max_length)),
        num_steps=_optional_int(values.get("num_steps", default.num_steps)),
        num_threads=_optional_int(values.get("num_threads", default.num_threads)),
        device=str(values.get("device", default.device)),
        device_policy=str(values.get("device_policy", default.device_policy)),
        device_priority=tuple(str(value) for value in values.get("device_priority", default.device_priority)),
        backend=str(values.get("backend", default.backend)),
    )


def _migrate_read_blocks(value: object) -> tuple[ReadBlock, ...]:
    if not isinstance(value, list):
        return (ReadBlock(ReadBlockKind.MESSAGE),)
    blocks = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            kind = ReadBlockKind(str(item.get("type", "")))
        except ValueError:
            continue
        text = str(item.get("value", ""))
        if kind is ReadBlockKind.TEXT and not text:
            continue
        blocks.append(ReadBlock(kind, text))
    return tuple(blocks) or (ReadBlock(ReadBlockKind.MESSAGE),)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
