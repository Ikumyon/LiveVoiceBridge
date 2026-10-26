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
    EngineConfig,
    ReadBlock,
    ReadBlockKind,
    SpeechConfig,
)
from livevoicebridge.integrations.storage.migrations import legacy_defaults, upgrade_schema1, upgrade_schema2


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
            original = self.path.read_bytes()
            document = json.loads(original.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"設定ファイルを読み込めません: {self.path}") from exc
        if not isinstance(document, dict):
            raise ConfigError("設定ファイルのルートはJSONオブジェクトである必要があります。")

        old_version = document.get("schema_version")
        if type(old_version) is int and old_version in (1, 2):
            try:
                values = document
                if old_version == 1:
                    values = upgrade_schema1(values, legacy_defaults(self._encode(default_config())))
                values = upgrade_schema2(values)
                config = self._decode(values)
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(str(exc)) from exc
            self._backup(original, old_version)
            self.save(config)
            return config
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ConfigError(f"未対応の設定スキーマです: {document.get('schema_version')}")
        return self._decode(document)

    def _backup(self, original: bytes, version: int) -> None:
        backup = self.path.with_suffix(self.path.suffix + f".schema{version}.bak")
        try:
            try:
                with backup.open("xb") as stream:
                    stream.write(original)
            except FileExistsError:
                if backup.read_bytes() != original:
                    raise ConfigError(f"既存の変換前バックアップが異なるため、変換を中止しました: {backup}") from None
        except OSError as exc:
            raise ConfigError(f"変換前の設定をバックアップできません: {backup}") from exc

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
            application = dict(document["application"])
            application["plugin_enabled"] = tuple(tuple(item) for item in application["plugin_enabled"])
            values["application"] = ApplicationConfig(**application)
            values["resources"] = ResourceLimits(**document["resources"])
            config = AppConfig(**values)
            validate(config)
            return config
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"設定値が不正です: {exc}") from exc

    @staticmethod
    def _decode_engine(data: dict[str, Any]) -> EngineConfig:
        return EngineConfig(**data)

    @staticmethod
    def _decode_read_block(data: dict[str, Any]) -> ReadBlock:
        values = dict(data)
        values["kind"] = ReadBlockKind(values["kind"])
        return ReadBlock(**values)
