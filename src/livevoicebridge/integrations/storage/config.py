"""Versioned, atomic JSON configuration persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from livevoicebridge.core.chat.models import StreamingConfig
from livevoicebridge.core.dictionary.models import DictionaryConfig
from livevoicebridge.core.settings.defaults import default_config
from livevoicebridge.core.settings.models import (
    SCHEMA_VERSION,
    AppConfig,
    ApplicationConfig,
    PopupMetricsConfig,
    PresentationConfig,
    ResourceLimits,
)
from livevoicebridge.core.settings.service import validate
from livevoicebridge.core.speech.models import (
    BouyomiConfig,
    CoeiroinkConfig,
    EngineConfig,
    Qwen3Config,
    ReadBlock,
    ReadBlockKind,
    SpeechConfig,
    TtsEngineKind,
    VoicevoxConfig,
)


class ConfigError(RuntimeError):
    """Invalid or unsupported persisted configuration."""


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

        if document.get("schema_version") != SCHEMA_VERSION:
            raise ConfigError(f"未対応の設定スキーマです: {document.get('schema_version')}")
        return self._decode(document)

    def save(self, config: AppConfig) -> None:
        validate(config)
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
            speech_data = dict(document["speech"])
            speech_data["active_engine"] = TtsEngineKind(speech_data["active_engine"])
            speech_data["engines"] = tuple(JsonConfigRepository._decode_engine(item) for item in speech_data["engines"])
            speech_data["read_blocks"] = tuple(
                JsonConfigRepository._decode_read_block(item) for item in speech_data["read_blocks"]
            )
            presentation_data = dict(document["presentation"])
            popup_data = dict(presentation_data["popup_metrics"])
            modes = popup_data["display_modes"]
            if not isinstance(modes, dict):
                raise ValueError("メトリクス表示はオブジェクトで指定してください。")
            popup_data["display_modes"] = tuple(sorted(modes.items()))
            presentation_data["popup_metrics"] = PopupMetricsConfig(**popup_data)
            values = dict(document)
            values["streaming"] = StreamingConfig(**document["streaming"])
            values["speech"] = SpeechConfig(**speech_data)
            values["presentation"] = PresentationConfig(**presentation_data)
            values["dictionary"] = DictionaryConfig(**document["dictionary"])
            values["application"] = ApplicationConfig(**document["application"])
            values["resources"] = ResourceLimits(**document["resources"])
            config = AppConfig(**values)
            validate(config)
            return config
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"設定値が不正です: {exc}") from exc

    @staticmethod
    def _decode_engine(data: dict[str, Any]) -> EngineConfig:
        kind = TtsEngineKind(data["kind"])
        classes = {
            TtsEngineKind.VOICEVOX: VoicevoxConfig,
            TtsEngineKind.COEIROINK: CoeiroinkConfig,
            TtsEngineKind.BOUYOMICHAN: BouyomiConfig,
            TtsEngineKind.QWEN3: Qwen3Config,
        }
        values = dict(data)
        values["kind"] = kind
        return classes[kind](**values)

    @staticmethod
    def _decode_read_block(data: dict[str, Any]) -> ReadBlock:
        values = dict(data)
        values["kind"] = ReadBlockKind(values["kind"])
        return ReadBlock(**values)
