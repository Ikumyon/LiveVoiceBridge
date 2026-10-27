from livevoicebridge import _native
from livevoicebridge.core.telemetry.models import GpuMetric, Measurement, MeasurementState, MetricsSnapshot


def _reading(item: _native.Measurement) -> Measurement:
    return Measurement(item.value, MeasurementState(item.state))


class NativeMetricsProvider:
    def __init__(self):
        self._collector = _native.RustMetricsCollector()

    def set_request(self, identifiers: frozenset[str] | None) -> None:
        self._collector.set_request(None if identifiers is None else sorted(identifiers))

    def discover_gpus(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._collector.discover_gpus())

    def collect(self) -> MetricsSnapshot:
        data = self._collector.collect()
        return MetricsSnapshot(
            _reading(data.cpu_percent),
            _reading(data.ram_percent),
            _reading(data.ram_used_gb),
            _reading(data.ram_total_gb),
            _reading(data.network_send_kbps),
            _reading(data.network_receive_kbps),
            tuple(
                GpuMetric(g.identifier, g.name, _reading(g.usage), _reading(g.memory_used), _reading(g.memory_total))
                for g in data.gpus
            ),
            _reading(data.active_sockets),
            _reading(data.npu_percent),
        )

    def close(self) -> None:
        self._collector.close()
