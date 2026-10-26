"""Host-owned inventory, validation, registration, and plugin lifetimes."""

import hashlib
import importlib
import importlib.util
import json
import logging
import math
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock

from livevoicebridge import _native
from livevoicebridge.core.settings.models import AppConfig
from livevoicebridge.integrations.native.audio import decode_wav
from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.contracts import (
    API_VERSION,
    EngineCapabilities,
    EngineConfig,
    EngineState,
    SettingField,
    TtsProvider,
)
from livevoicebridge.plugins.executable import executable_provider

BUILTINS = ("voicevox", "coeiroink", "bouyomichan", "qwen3")
logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    kind: str
    builtin: bool
    root: Path
    manifest: dict
    enabled: bool = False
    status: str = "無効"
    error: str = ""


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("エントリーは相対パスで指定してください。")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("エントリーがプラグインフォルダーの外を指しています。")
    return path


class PluginManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.inventory: list[PluginInfo] = []
        self.providers: dict[str, TtsProvider] = {}
        self.contexts: dict[str, PluginContext] = {}
        self.states: dict[str, EngineState] = {}
        self._pending: list[tuple[str, dict, int | None]] = []
        self._bound = False
        self._binding = Lock()
        self._state_changed: Callable[[EngineState], None] = lambda _state: None
        self._save: Callable[[str, dict], None] = lambda _id, _values: None
        self._post: Callable[[Callable[[], None]], None] = lambda action: action()
        self._publish: Callable[[str], None] = lambda message: logger.info("%s", message)

    def bind(
        self,
        post: Callable[[Callable[[], None]], None],
        save: Callable[[str, dict], None],
        publish: Callable[[str], None],
        state_changed: Callable[[EngineState], None],
    ) -> None:
        with self._binding:
            self._post, self._save, self._publish = post, save, publish
            self._state_changed = state_changed
            self._bound = True
            pending, self._pending = self._pending, []
        for identifier, values, generation in pending:
            self.save_config(identifier, values, generation)

    def notify(self, message: str) -> None:
        self._publish(message)

    def load(self, config: AppConfig) -> AppConfig:
        enabled = dict(config.application.plugin_enabled)
        builtin_root = Path(__file__).parent / "builtin"
        sources = [(builtin_root / key, True) for key in BUILTINS]
        external_root = self.root / "plugins"
        if external_root.exists():
            if not external_root.resolve().is_relative_to(self.root):
                raise ValueError("pluginsの配置先がポータブル配置先の外を指しています。")
            sources.extend((path, False) for path in sorted(external_root.iterdir()) if path.is_dir())
        for directory, builtin in sources:
            info = PluginInfo(directory.name, directory.name, "", "", builtin, directory, {})
            try:
                if not builtin and not directory.resolve().is_relative_to(external_root.resolve()):
                    raise ValueError("外部プラグインがpluginsの外を指しています。")
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("マニフェストはJSONオブジェクトで指定してください。")
                identifier = manifest["id"]
                if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", identifier):
                    raise ValueError("プラグインIDが不正です。")
                info.id = identifier
                info.manifest = manifest
                for key in ("name", "version", "kind"):
                    if not isinstance(manifest.get(key), str) or not manifest[key]:
                        raise ValueError(f"{key}を指定してください。")
                info.name, info.version, info.kind = manifest["name"], manifest["version"], manifest["kind"]
                if type(manifest.get("api_version")) is not int or manifest["api_version"] != API_VERSION:
                    raise ValueError("未対応のプラグインAPI版です。")
                if (
                    not isinstance(manifest.get("platforms"), list)
                    or _native.plugin_platform() not in manifest["platforms"]
                ):
                    raise ValueError("現在のOSには対応していません。")
                if info.kind not in {"python", "executable"}:
                    raise ValueError("未対応の実行形式です。")
                if builtin and identifier != directory.name:
                    raise ValueError("内蔵プラグインのIDが一致しません。")
                if info.kind == "python":
                    entry = manifest["entry"]
                    if builtin:
                        if entry != "entry.py":
                            raise ValueError("内蔵プラグインのエントリーが不正です。")
                    elif not contained(directory, entry).is_file():
                        raise ValueError("Pythonエントリーがありません。")
                else:
                    executable = manifest["executables"][_native.plugin_platform()]
                    if not contained(directory, executable["path"]).is_file():
                        raise ValueError("外部プラグインの実行ファイルがありません。")
                    arguments = executable.get("args", [])
                    if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
                        raise ValueError("実行引数は文字列配列で指定してください。")
            except Exception as exc:
                info.error, info.status = str(exc), "エラー"
            info.enabled = enabled.get(info.id, builtin)
            self.inventory.append(info)
        duplicates = Counter(info.id for info in self.inventory if not info.builtin)
        builtin_ids = {info.id for info in self.inventory if info.builtin}
        for info in self.inventory:
            if not info.builtin and (info.id in builtin_ids or duplicates[info.id] > 1):
                info.error, info.status = "プラグインIDが重複しています。", "エラー"
            if info.error or not info.enabled:
                continue
            context = None
            try:
                data = self.root / "data/plugins" / info.id
                if not data.resolve().is_relative_to(self.root):
                    raise ValueError("プラグイン保存先がポータブル配置先の外を指しています。")
                data.mkdir(parents=True, exist_ok=True)
                context = PluginContext(info.id, info.root, data, decode_wav, self.save_config, self.publish_state)
                if info.kind == "python":
                    if info.builtin:
                        module = importlib.import_module(f"livevoicebridge.plugins.builtin.{info.id}.entry")
                    else:
                        path = contained(info.root, info.manifest["entry"])
                        name = "livevoicebridge_external_" + hashlib.sha256(info.id.encode("utf-8")).hexdigest()
                        spec = importlib.util.spec_from_file_location(
                            name, path, submodule_search_locations=[str(path.parent)]
                        )
                        if spec is None or spec.loader is None:
                            raise ValueError("Pythonエントリーを読み込めません。")
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[name] = module

                        def unload(prefix=name):
                            for key in tuple(sys.modules):
                                if key == prefix or key.startswith(prefix + "."):
                                    del sys.modules[key]

                        context.on_close(unload)
                        spec.loader.exec_module(module)
                    module.register(context)
                else:
                    executable = info.manifest["executables"][_native.plugin_platform()]
                    args = executable.get("args", [])
                    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                        raise ValueError("実行引数は文字列配列で指定してください。")
                    context.register(executable_provider(context, str(contained(info.root, executable["path"])), args))
                context._accepting = False
                provider = context.provider
                if provider is None:
                    raise ValueError("TTS提供者が登録されていません。")
                if not all(
                    callable(getattr(provider, name, None))
                    for name in ("defaults", "validate", "create", "configure", "wait_ready", "close")
                ):
                    raise ValueError("TTS提供者の契約が不正です。")
                if provider.id != info.id or not isinstance(provider.name, str) or not provider.name:
                    raise ValueError("TTS提供者のIDまたは表示名が不正です。")
                fields = provider.fields
                if not isinstance(fields, tuple) or not all(isinstance(field, SettingField) for field in fields):
                    raise ValueError("設定項目はSettingFieldのタプルで指定してください。")
                if len({field.key for field in fields}) != len(fields):
                    raise ValueError("設定項目のキーが重複しています。")
                if any(
                    field.kind not in {"text", "secret", "file", "directory", "choice", "bool", "integer", "number"}
                    or not isinstance(field.key, str)
                    or not field.key
                    or not isinstance(field.title, str)
                    or not math.isfinite(field.minimum)
                    or not math.isfinite(field.maximum)
                    or field.minimum > field.maximum
                    or not isinstance(field.choices, tuple)
                    or not all(isinstance(choice, str) for choice in field.choices)
                    for field in fields
                ):
                    raise ValueError("設定項目の定義が不正です。")
                allowed = {"speaker_id", "speed", "pitch", "volume", "echo", "yamabiko", "panning"}
                capability = provider.capabilities
                if (
                    not isinstance(capability, EngineCapabilities)
                    or type(capability.local_audio) is not bool
                    or type(capability.completion_known) is not bool
                    or not isinstance(capability.controls, frozenset)
                    or not capability.controls <= allowed
                ):
                    raise ValueError("対応するコメント制御が不正です。")
                defaults = provider.defaults()
                if (
                    not isinstance(defaults, EngineConfig)
                    or defaults.engine_id != info.id
                    or not isinstance(defaults.speaker_id, str)
                    or not defaults.speaker_id
                    or type(defaults.max_length) is not int
                    or defaults.max_length == 0
                    or defaults.max_length < -1
                    or not isinstance(defaults.settings, dict)
                    or any(
                        not isinstance(key, str)
                        or type(value) not in (str, int, float, bool, type(None))
                        or isinstance(value, float)
                        and not math.isfinite(value)
                        for key, value in defaults.settings.items()
                    )
                ):
                    raise ValueError("TTSの既定設定が不正です。")
                provider.validate(defaults)
                self.providers[info.id], self.contexts[info.id] = provider, context
                info.status = "読み込み済み"
            except Exception as exc:
                info.error, info.status = str(exc), "エラー"
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        logger.exception("プラグイン登録失敗時の終了処理")
        configs = {engine.engine_id: engine for engine in config.speech.engines}
        for key, provider in self.providers.items():
            if key not in configs:
                configs[key] = provider.defaults()
            else:
                saved = configs[key]
                configs[key] = replace(saved, settings={**provider.defaults().settings, **saved.settings})
        return replace(config, speech=replace(config.speech, engines=tuple(configs.values())))

    def save_config(self, identifier: str, values: dict, generation: int | None = None) -> None:
        values = dict(values)
        with self._binding:
            if not self._bound:
                self._pending.append((identifier, values, generation))
                return

        def apply() -> None:
            if identifier not in self.providers:
                return
            state = self.states.get(identifier)
            if generation is None or state is not None and state.generation == generation:
                self._save(identifier, values)

        self._post(apply)

    def publish_state(self, state: EngineState) -> None:
        previous = self.states.get(state.engine_id)
        if previous is not None and state.generation < previous.generation:
            return
        self.states[state.engine_id] = state
        if previous is None or previous.phase != state.phase:
            self.notify(f"[{state.engine_id}] {state.message}")
        self._state_changed(state)

    def require(self, identifier: str) -> TtsProvider:
        if identifier not in self.providers:
            raise ValueError("選択中のTTSを利用できません。設定で利用可能なTTSを選択してください。")
        return self.providers[identifier]

    def create(self, config: EngineConfig):
        provider = self.require(config.engine_id)
        provider.validate(config)
        return provider.create(config)

    def configure(self, config: EngineConfig) -> None:
        for key, provider in self.providers.items():
            provider.configure(config if key == config.engine_id else None)

    def wait_ready(self, identifier: str, cancelled):
        return self.require(identifier).wait_ready(cancelled)

    def close(self) -> None:
        for key, context in reversed(tuple(self.contexts.items())):
            try:
                context.close()
            except Exception:
                logger.exception("プラグインの終了に失敗しました: %s", key)
