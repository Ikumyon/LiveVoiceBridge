use crate::platform;
use crate::platform::SocketCounter;
use crate::traits::MetricsProvider;
use pyo3::prelude::*;

#[pyclass(frozen, get_all)]
#[derive(Clone)]
pub struct Measurement {
    pub value: Option<f64>,
    pub state: String,
}
impl Measurement {
    fn new(value: Option<f64>, state: &str) -> Self {
        let value = value.filter(|value| value.is_finite());
        Self {
            value,
            state: if value.is_some() {
                "available".into()
            } else {
                state.into()
            },
        }
    }
}

#[pyclass(frozen, get_all)]
#[derive(Clone)]
pub struct NativeGpu {
    pub identifier: String,
    pub name: String,
    pub usage: Measurement,
    pub memory_used: Measurement,
    pub memory_total: Measurement,
}

#[pyclass(frozen, get_all)]
pub struct NativeMetricsSnapshot {
    pub cpu_percent: Measurement,
    pub ram_percent: Measurement,
    pub ram_used_gb: Measurement,
    pub ram_total_gb: Measurement,
    pub network_send_kbps: Measurement,
    pub network_receive_kbps: Measurement,
    pub gpus: Vec<NativeGpu>,
    pub active_sockets: Measurement,
    pub npu_percent: Measurement,
}

#[pyclass]
pub struct RustMetricsCollector {
    provider: Option<Box<dyn MetricsProvider>>,
    sockets: SocketCounter,
    first: bool,
}

#[pymethods]
impl RustMetricsCollector {
    #[new]
    fn new() -> Self {
        Self {
            provider: Some(platform::create_metrics_provider()),
            sockets: SocketCounter::new(),
            first: true,
        }
    }
    fn collect(&mut self, py: Python<'_>) -> PyResult<NativeMetricsSnapshot> {
        py.allow_threads(|| {
            let raw = self
                .provider
                .as_mut()
                .ok_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err("メトリクス取得は終了しています。")
                })?
                .collect();
            let phase = if self.first {
                "warming_up"
            } else {
                "unavailable"
            };
            let available = |id: &str| raw.available_metrics.iter().any(|key| key == id);
            let cpu = Measurement::new(
                (available("cpu") && !self.first).then_some(raw.cpu_percent as f64),
                phase,
            );
            let ram = available("ram");
            let network = available("network") && !self.first;
            let gpus = raw
                .gpus
                .into_iter()
                .map(|gpu| {
                    let state = if gpu.usage_supported {
                        phase
                    } else {
                        "unsupported"
                    };
                    NativeGpu {
                        identifier: gpu.id,
                        name: gpu.name,
                        usage: Measurement::new(gpu.gpu_percent.map(f64::from), state),
                        memory_used: Measurement::new(
                            gpu.has_vram.then_some(gpu.vram_used_gb as f64),
                            if gpu.vram_total_gb > 0.0 {
                                "unavailable"
                            } else {
                                "unsupported"
                            },
                        ),
                        memory_total: Measurement::new(
                            (gpu.vram_total_gb > 0.0).then_some(gpu.vram_total_gb as f64),
                            "unsupported",
                        ),
                    }
                })
                .collect();
            self.first = false;
            Ok(NativeMetricsSnapshot {
                cpu_percent: cpu,
                npu_percent: Measurement::new(None, "unsupported"),
                ram_percent: Measurement::new(ram.then_some(raw.ram_percent as f64), "unavailable"),
                ram_used_gb: Measurement::new(ram.then_some(raw.ram_used_gb as f64), "unavailable"),
                ram_total_gb: Measurement::new(
                    ram.then_some(raw.ram_total_gb as f64),
                    "unavailable",
                ),
                network_send_kbps: Measurement::new(
                    network.then_some(raw.net_send_speed_kb as f64),
                    phase,
                ),
                network_receive_kbps: Measurement::new(
                    network.then_some(raw.net_recv_speed_kb as f64),
                    phase,
                ),
                gpus,
                active_sockets: Measurement::new(
                    self.sockets.count().map(|value| value as f64),
                    "unavailable",
                ),
            })
        })
    }
    fn close(&mut self, py: Python<'_>) {
        let provider = self.provider.take();
        py.allow_threads(|| drop(provider));
        self.sockets = SocketCounter::new();
    }
}
