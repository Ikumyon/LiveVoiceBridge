from collections import deque
from dataclasses import dataclass
from threading import Lock

from livevoicebridge.core.telemetry.models import Measurement, MetricFrame, MetricsSnapshot


@dataclass
class _Track:
    histories: list[deque[float | None]]


def _format(item: Measurement, suffix: str = "", precision: int = 1) -> str:
    return f"{item.value:.{precision}f}{suffix}" if item.value is not None else item.text


class MetricsStore:
    """A single 60-sample history; immutable frames are shared by every view."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._tracks: dict[str, _Track] = {}
        self._frames: tuple[MetricFrame, ...] = ()
        self._latest: MetricsSnapshot | None = None
        self._connections = 0

    def set_connections(self, count: int) -> None:
        with self._lock:
            self._connections = count

    def record(self, sample: MetricsSnapshot) -> None:
        with self._lock:
            self._latest = sample
            specs: list[tuple[str, str, str, str, float, str, tuple[float | None, ...]]] = [
                ("cpu", "CPU 使用率", "cpu", "%", 100, _format(sample.cpu_percent, " %"), (sample.cpu_percent.value,)),
                (
                    "ram",
                    "メモリ (RAM) 使用量",
                    "ram",
                    "%",
                    100,
                    f"{_format(sample.ram_used_gb, precision=2)} / {_format(sample.ram_total_gb)} GB",
                    (sample.ram_percent.value,),
                ),
                (
                    "network",
                    "ネットワーク通信速度",
                    "network",
                    "KiB/s",
                    max(100, ((sample.network_send_kbps.value or 0) + (sample.network_receive_kbps.value or 0)) * 1.5),
                    f"↓ {_format(sample.network_receive_kbps)} ↑ {_format(sample.network_send_kbps)} KiB/s",
                    (sample.network_receive_kbps.value, sample.network_send_kbps.value),
                ),
                (
                    "youtube_connections",
                    "YouTube 同時接続数",
                    "connections",
                    "件",
                    4,
                    f"{self._connections} 件",
                    (float(self._connections),),
                ),
            ]
            if sample.npu_percent.value is not None:
                specs.append(
                    (
                        "npu",
                        "NPU 使用率",
                        "npu",
                        "%",
                        100,
                        _format(sample.npu_percent, " %"),
                        (sample.npu_percent.value,),
                    )
                )
            for gpu in sample.gpus:
                usage = gpu.usage.value
                used, total = gpu.memory_used.value, gpu.memory_total.value
                values: tuple[float | None, ...] = (usage,)
                text = f"Core: {_format(gpu.usage, '%')}"
                if total is not None and total > 0:
                    values = (usage, used / total * 100 if used is not None else None)
                    text += f" | VRAM: {_format(gpu.memory_used, precision=2)}/{total:.1f} GB"
                specs.append((f"gpu:{gpu.identifier}", gpu.name, "gpu", "%", 100, text, values))
            alive = {spec[0] for spec in specs}
            self._tracks = {key: value for key, value in self._tracks.items() if key in alive}
            frames = []
            for identifier, title, kind, unit, maximum, text, values in specs:
                track = self._tracks.get(identifier)
                if track is None:
                    track = _Track([])
                    self._tracks[identifier] = track
                while len(track.histories) < len(values):
                    track.histories.append(deque([None] * 60, maxlen=60))
                del track.histories[len(values) :]
                for history, value in zip(track.histories, values, strict=True):
                    history.append(value)
                frames.append(
                    MetricFrame(identifier, title, kind, unit, maximum, text, tuple(tuple(h) for h in track.histories))
                )
            self._frames = tuple(frames)

    def read(self) -> tuple[tuple[MetricFrame, ...], MetricsSnapshot | None]:
        with self._lock:
            return self._frames, self._latest
