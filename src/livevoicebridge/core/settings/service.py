import math
from dataclasses import asdict, fields, is_dataclass
from threading import RLock
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from livevoicebridge.core.settings.models import SCHEMA_VERSION, AppConfig
from livevoicebridge.core.settings.ports import ConfigRepository
from livevoicebridge.core.speech.models import BouyomiConfig, Qwen3Config, TtsEngineKind


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
    kinds = [engine.kind for engine in config.speech.engines]
    if len(kinds) != len(set(kinds)) or set(kinds) != set(TtsEngineKind):
        raise ValueError("対応する全エンジンの設定を重複なく指定してください。")
    config.speech.engine()
    if not config.speech.read_blocks or not 1 <= config.speech.queue_limit <= 10000:
        raise ValueError("読み上げブロックとキュー上限が不正です。")
    for engine in config.speech.engines:
        if not engine.url or engine.max_length == 0 or engine.max_length < -1:
            raise ValueError("接続先または最大文字数が不正です。")
        for value in asdict(engine).values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("音声パラメータは有限値で指定してください。")
        if engine.speaker_id < 0:
            raise ValueError("話者IDが不正です。")
        if isinstance(engine, BouyomiConfig):
            if not all(-1 <= value <= 32767 for value in (engine.speed, engine.pitch, engine.volume)):
                raise ValueError("棒読みちゃんの数値指定が範囲外です。")
        elif engine.volume < 0:
            raise ValueError("音量は0以上で指定してください。")
        if isinstance(engine, Qwen3Config) and (engine.speaker_id > 8 or engine.volume > 2):
            raise ValueError("Qwen3の話者または音量が範囲外です。")
    view = config.presentation
    if not all(0 <= value <= 1 for value in (view.comment_opacity, view.header_opacity, view.border_opacity)):
        raise ValueError("不透明度が範囲外です。")
    popup = view.popup_metrics
    if popup.placement not in {"top", "bottom", "left", "right"}:
        raise ValueError("メトリクスの配置が不正です。")
    if not all(0.1 <= value <= 0.9 for value in (popup.vertical_ratio, popup.horizontal_ratio)):
        raise ValueError("メトリクスの分割比率が不正です。")


def _validate_type(value, expected, location: str) -> None:
    origin = get_origin(expected)
    if origin is UnionType:
        for alternative in get_args(expected):
            try:
                _validate_type(value, alternative, location)
                return
            except ValueError:
                continue
        raise ValueError(f"{location} の型が不正です。")
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
