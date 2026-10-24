import math
from dataclasses import dataclass
from enum import StrEnum


class ErrorKind(StrEnum):
    RECOVERABLE = "recoverable"
    USER_ACTION_REQUIRED = "user_action_required"
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class ApplicationIssue:
    kind: ErrorKind
    code: str
    message: str
    detail: str = ""


class MeasurementState(StrEnum):
    AVAILABLE = "available"
    WARMING_UP = "warming_up"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Measurement:
    value: float | None
    state: MeasurementState

    def __post_init__(self) -> None:
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("測定値は有限値で指定してください。")
        if (self.value is not None) != (self.state is MeasurementState.AVAILABLE):
            raise ValueError("測定状態と値が一致しません。")

    @property
    def text(self) -> str:
        return {
            MeasurementState.AVAILABLE: "",
            MeasurementState.WARMING_UP: "計測中",
            MeasurementState.UNSUPPORTED: "未対応",
            MeasurementState.UNAVAILABLE: "取得不可",
        }[self.state]


@dataclass(frozen=True, slots=True)
class GpuMetric:
    identifier: str
    name: str
    usage: Measurement
    memory_used: Measurement
    memory_total: Measurement


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    cpu_percent: Measurement
    ram_percent: Measurement
    ram_used_gb: Measurement
    ram_total_gb: Measurement
    network_send_kbps: Measurement
    network_receive_kbps: Measurement
    gpus: tuple[GpuMetric, ...]
    active_sockets: Measurement
    npu_percent: Measurement = Measurement(None, MeasurementState.UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class MetricFrame:
    identifier: str
    title: str
    kind: str
    unit: str
    maximum: float
    text: str
    histories: tuple[tuple[float | None, ...], ...]
