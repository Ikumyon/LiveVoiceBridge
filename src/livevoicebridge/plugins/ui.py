"""Optional Python plugin settings pages, separate from worker contracts."""

from typing import Protocol

from PySide6.QtWidgets import QWidget

from livevoicebridge.plugins.contracts import EngineConfig


class SettingsPage(Protocol):
    widget: QWidget

    def read(self, config: EngineConfig) -> EngineConfig: ...
    def close(self) -> None: ...
