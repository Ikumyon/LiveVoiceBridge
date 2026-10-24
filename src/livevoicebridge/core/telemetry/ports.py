from typing import Protocol

from livevoicebridge.core.telemetry.models import MetricsSnapshot


class MetricsProvider(Protocol):
    def close(self) -> None: ...
    def collect(self) -> MetricsSnapshot: ...


class UpdateProvider(Protocol):
    def latest(self) -> str | None: ...
