import math
from dataclasses import fields, is_dataclass
from threading import RLock
from types import UnionType
from typing import TypeAliasType, get_args, get_origin, get_type_hints

from livevoicebridge.core.settings.models import SCHEMA_VERSION, AppConfig
from livevoicebridge.core.settings.ports import ConfigRepository


def validate(config: AppConfig) -> None:
    _validate_type(config, AppConfig, "設定")
    if config.schema_version != SCHEMA_VERSION:
        raise ValueError("未対応の設定スキーマです。設定を新しい形式で作成してください。")
    limits = config.resources
    for value, minimum, maximum, step in (
        (limits.comment_count, 100, 10000, 100),
        (limits.log_lines, 100, 20000, 100),
        (limits.audio_mib, 4, 256, 4),
        (limits.avatar_mib, 1, 64, 1),
    ):
        if not minimum <= value <= maximum or value % step:
            raise ValueError("リソース上限の範囲または刻みが不正です。")
    identifiers = [engine.engine_id for engine in config.speech.engines]
    if len(identifiers) != len(set(identifiers)) or any(not key for key in identifiers):
        raise ValueError("エンジンIDが空または重複しています。")
    config.speech.engine()
    plugin_ids = [identifier for identifier, _enabled in config.application.plugin_enabled]
    if len(plugin_ids) != len(set(plugin_ids)) or any(not identifier for identifier in plugin_ids):
        raise ValueError("プラグイン有効状態のIDが空または重複しています。")
    if not config.speech.read_blocks or not 1 <= config.speech.queue_limit <= 10000:
        raise ValueError("読み上げブロックとキュー上限が不正です。")
    for engine in config.speech.engines:
        if engine.max_length == 0 or engine.max_length < -1:
            raise ValueError("最大文字数が不正です。")
        if not engine.speaker_id:
            raise ValueError("話者IDを指定してください。")
        for parameter in engine.settings.values():
            if isinstance(parameter, float) and not math.isfinite(parameter):
                raise ValueError("音声パラメータは有限値で指定してください。")
    view = config.presentation
    if not all(0 <= value <= 1 for value in (view.comment_opacity, view.header_opacity, view.border_opacity)):
        raise ValueError("不透明度が範囲外です。")
    popup = view.popup_metrics
    if popup.placement not in {"top", "bottom", "left", "right"}:
        raise ValueError("メトリクスの配置が不正です。")
    if not all(0.1 <= value <= 0.9 for value in (popup.vertical_ratio, popup.horizontal_ratio)):
        raise ValueError("メトリクスの分割比率が不正です。")


def _validate_type(value, expected, location: str) -> None:
    while isinstance(expected, TypeAliasType):
        expected = expected.__value__
    origin = get_origin(expected)
    if origin is UnionType:
        for alternative in get_args(expected):
            try:
                _validate_type(value, alternative, location)
                return
            except ValueError:
                continue
        raise ValueError(f"{location} の型が不正です。")
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{location} はオブジェクトで指定してください。")
        key_type, value_type = get_args(expected)
        for key, item in value.items():
            _validate_type(key, key_type, location)
            _validate_type(item, value_type, location)
        return
    if origin is tuple:
        if not isinstance(value, tuple):
            raise ValueError(f"{location} は配列で指定してください。")
        arguments = get_args(expected)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            for item in value:
                _validate_type(item, arguments[0], location)
        else:
            if len(value) != len(arguments):
                raise ValueError(f"{location} の項目数が不正です。")
            for item, annotation in zip(value, arguments, strict=True):
                _validate_type(item, annotation, location)
        return
    if is_dataclass(expected):
        if type(value) is not expected:
            raise ValueError(f"{location} の設定形式が不正です。")
        annotations = get_type_hints(expected)
        for item in fields(expected):
            _validate_type(getattr(value, item.name), annotations[item.name], f"{location}.{item.name}")
        return
    valid = type(value) in (int, float) if expected is float else type(value) is expected
    if not valid:
        raise ValueError(f"{location} の型が不正です。")


class SettingsService:
    def __init__(self, repository: ConfigRepository):
        self._repository = repository
        self._lock = RLock()
        self._config = repository.load()
        validate(self._config)
        self._revision = 0

    @property
    def current(self) -> AppConfig:
        with self._lock:
            return self._config

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def apply(self, config: AppConfig) -> int:
        validate(config)
        with self._lock:
            self._repository.save(config)
            self._config = config
            self._revision += 1
            return self._revision
