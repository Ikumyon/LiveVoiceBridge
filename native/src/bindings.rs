use crate::platform;
use crate::platform::SocketCounter;
use crate::traits::MetricsProvider;
use crate::types::MetricsRequest;
use pyo3::prelude::*;
use std::collections::HashSet;

#[pyclass(frozen, get_all, from_py_object)]
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

#[pyclass(frozen, get_all, from_py_object)]
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
    request: MetricsRequest,
    active: HashSet<String>,
    closed: bool,
}

#[pymethods]
impl RustMetricsCollector {
    #[new]
    fn new() -> Self {
        Self {
            provider: None,
            sockets: SocketCounter::new(),
            request: MetricsRequest(Some(HashSet::new())),
            active: HashSet::new(),
            closed: false,
        }
    }
    #[pyo3(signature = (identifiers))]
    fn set_request(&mut self, identifiers: Option<Vec<String>>) {
        self.request = MetricsRequest(identifiers.map(|ids| ids.into_iter().collect()));
        self.active.retain(|id| self.request.wants(id));
        if let Some(provider) = &mut self.provider {
            provider.set_request(&self.request);
        }
    }

    fn discover_gpus(&mut self, py: Python<'_>) -> PyResult<Vec<(String, String)>> {
        py.detach(|| {
            if self.closed {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    "メトリクス取得は終了しています。",
                ));
            }
            Ok(self
                .provider
                .get_or_insert_with(platform::create_metrics_provider)
                .discover_gpus())
        })
    }

    fn collect(&mut self, py: Python<'_>) -> PyResult<NativeMetricsSnapshot> {
        py.detach(|| {
            if self.closed {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    "メトリクス取得は終了しています。",
                ));
            }
            let raw = self
                .provider
                .get_or_insert_with(platform::create_metrics_provider)
                .collect(&self.request);
            let available = |id: &str| raw.available_metrics.iter().any(|key| key == id);
            let cpu_ready = self.active.contains("cpu");
            let network_ready = self.active.contains("network");
            let cpu = Measurement::new(
                (available("cpu") && cpu_ready).then_some(raw.cpu_percent as f64),
                if cpu_ready {
                    "unavailable"
                } else {
                    "warming_up"
                },
            );
            let ram = available("ram");
            let network = available("network") && network_ready;
            let gpus = raw
                .gpus
                .into_iter()
                .map(|gpu| {
                    let id = format!("gpu:{}", gpu.id);
                    let ready = self.active.contains(&id);
                    self.active.insert(id);
                    let state = if !gpu.usage_supported {
                        "unsupported"
                    } else if ready {
                        "unavailable"
                    } else {
                        "warming_up"
                    };
                    NativeGpu {
                        identifier: gpu.id,
                        name: gpu.name,
                        usage: Measurement::new(
                            gpu.gpu_percent.filter(|_| ready).map(f64::from),
                            state,
                        ),
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
            for id in ["cpu", "network"] {
                if self.request.wants(id) {
                    self.active.insert(id.into());
                }
            }
            let phase = if network_ready {
                "unavailable"
            } else {
                "warming_up"
            };
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
                    if self.request.wants("sockets") {
                        self.sockets.count().map(|value| value as f64)
                    } else {
                        None
                    },
                    "unavailable",
                ),
            })
        })
    }
    fn close(&mut self, py: Python<'_>) {
        self.closed = true;
        let provider = self.provider.take();
        py.detach(|| drop(provider));
        self.sockets = SocketCounter::new();
    }
}
