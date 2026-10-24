from typing import Protocol

from livevoicebridge.core.settings.models import AppConfig


class ConfigRepository(Protocol):
    def load(self) -> AppConfig: ...
    def save(self, config: AppConfig) -> None: ...
