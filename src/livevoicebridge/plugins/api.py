"""The registration context retained by a Python plugin for its lifetime."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from livevoicebridge.plugins.contracts import AudioData, EngineConfig, EngineState, SpeechControls, TtsProvider

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from livevoicebridge.plugins.ui import SettingsPage


class PluginContext:
    def __init__(
        self,
        plugin_id: str,
        root: Path,
        data: Path,
        decode_wav: Callable[[bytes, SpeechControls, int], AudioData],
        save_config: Callable[[str, dict, int | None], None],
        publish_state: Callable[[EngineState], None],
    ):
        self.id = plugin_id
        self.root = root
        self.data = data
        self.logger = logging.getLogger(f"plugins.{plugin_id}")
        self.decode_wav = decode_wav
        self.save_config = lambda values, generation=None: save_config(plugin_id, values, generation)
        self._publish_state = publish_state
        self.provider: TtsProvider | None = None
        self.settings_page: Callable[[QWidget, Callable[[], EngineConfig]], SettingsPage] | None = None
        self._callbacks: list[Callable[[], None]] = []
        self._accepting = True

    def publish_state(self, state: EngineState) -> None:
        if state.engine_id != self.id:
            raise ValueError("状態通知のエンジンIDが一致しません。")
        self._publish_state(state)

    def register(self, provider: TtsProvider) -> None:
        if not self._accepting or self.provider is not None or provider.id != self.id:
            raise ValueError("プラグインは自身のIDで提供者を一度だけ登録してください。")
        self.provider = provider
        if callable(getattr(provider, "close", None)):
            self.on_close(provider.close)

    def on_close(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def managed_process(self):
        from livevoicebridge import _native

        process = _native.ManagedProcess()
        self.on_close(process.close)
        return process

    def close(self) -> None:
        self._accepting = False
        errors = []
        for callback in reversed(self._callbacks):
            try:
                callback()
            except Exception as exc:
                errors.append(str(exc))
        self._callbacks.clear()
        if errors:
            raise RuntimeError(" / ".join(errors))
