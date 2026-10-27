use std::time::{Duration, Instant};

use sysinfo::{Networks, System};

use super::GpuMetrics;
use crate::traits::MetricsProvider;
use crate::types::{MetricsRequest, MetricsSnapshot};

pub struct SystemMetricsProvider {
    sys: Option<System>,
    networks: Option<Networks>,
    last_network: Option<Instant>,
    last_devices: Option<Instant>,
    gpu: Option<GpuMetrics>,
}

impl SystemMetricsProvider {
    pub fn new() -> Self {
        Self {
            sys: None,
            networks: None,
            last_network: None,
            last_devices: None,
            gpu: None,
        }
    }
}

impl MetricsProvider for SystemMetricsProvider {
    fn set_request(&mut self, request: &MetricsRequest) {
        if !request.wants("network") {
            self.networks = None;
            self.last_network = None;
            self.last_devices = None;
        }
        if !request.wants_gpu() {
            self.gpu = None;
        }
    }

    fn discover_gpus(&mut self) -> Vec<(String, String)> {
        // Identification only: no performance counters or usage sampling.
        GpuMetrics::new().catalog()
    }

    fn collect(&mut self, request: &MetricsRequest) -> MetricsSnapshot {
        let mut result = MetricsSnapshot {
            available_metrics: Vec::new(),
            cpu_percent: 0.0,
            ram_percent: 0.0,
            ram_used_gb: 0.0,
            ram_total_gb: 0.0,
            net_send_speed_kb: 0.0,
            net_recv_speed_kb: 0.0,
            net_total_speed_kb: 0.0,
            gpus: Vec::new(),
        };
        if request.wants("cpu") || request.wants("ram") {
            let sys = self.sys.get_or_insert_with(System::new);
            if request.wants("cpu") {
                sys.refresh_cpu_usage();
                result.cpu_percent = sys.global_cpu_usage();
                if !sys.cpus().is_empty() {
                    result.available_metrics.push("cpu".into());
                }
            }
            if request.wants("ram") {
                sys.refresh_memory();
                let total = sys.total_memory();
                let used = sys.used_memory();
                result.ram_used_gb = used as f32 / 1024.0_f32.powi(3);
                result.ram_total_gb = total as f32 / 1024.0_f32.powi(3);
                if total > 0 {
                    result.ram_percent = used as f32 / total as f32 * 100.0;
                    result.available_metrics.push("ram".into());
                }
            }
        }
        if request.wants("network") {
            let now = Instant::now();
            let networks = self
                .networks
                .get_or_insert_with(Networks::new_with_refreshed_list);
            let refresh_devices = self
                .last_devices
                .is_none_or(|time| time.elapsed() >= Duration::from_secs(10));
            networks.refresh(refresh_devices);
            if refresh_devices {
                self.last_devices = Some(now);
            }
            let dt = self.last_network.replace(now).map_or(1.0, |last| {
                now.duration_since(last).as_secs_f32().max(0.001)
            });
            for data in networks.values() {
                result.net_recv_speed_kb += data.received() as f32 / dt / 1024.0;
                result.net_send_speed_kb += data.transmitted() as f32 / dt / 1024.0;
            }
            result.net_total_speed_kb = result.net_recv_speed_kb + result.net_send_speed_kb;
            if !networks.is_empty() {
                result.available_metrics.push("network".into());
            }
        }
        if request.wants_gpu() {
            result.gpus = self
                .gpu
                .get_or_insert_with(GpuMetrics::new)
                .collect(request);
        }
        result
    }
}
