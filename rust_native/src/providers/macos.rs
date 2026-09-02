use std::time::Instant;
use sysinfo::{CpuRefreshKind, MemoryRefreshKind, Networks, RefreshKind, System};

use crate::traits::MetricsProvider;
use crate::types::{GpuMetric, MetricsSnapshot};

pub struct MacosMetricsProvider {
    sys: System,
    networks: Networks,
    last_collect_time: Instant,
}

impl Default for MacosMetricsProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl MacosMetricsProvider {
    pub fn new() -> Self {
        let mut sys = System::new_with_specifics(
            RefreshKind::new()
                .with_cpu(CpuRefreshKind::everything())
                .with_memory(MemoryRefreshKind::everything()),
        );
        sys.refresh_cpu();
        sys.refresh_memory();

        let mut networks = Networks::new_with_refreshed_list();
        networks.refresh();

        Self {
            sys,
            networks,
            last_collect_time: Instant::now(),
        }
    }
}

impl MetricsProvider for MacosMetricsProvider {
    fn collect(&mut self) -> MetricsSnapshot {
        let now = Instant::now();
        let dt = now
            .duration_since(self.last_collect_time)
            .as_secs_f32()
            .max(0.001);
        self.last_collect_time = now;

        self.sys.refresh_cpu();
        let cpu_percent = self.sys.global_cpu_info().cpu_usage();

        self.sys.refresh_memory();
        let total_mem_bytes = self.sys.total_memory();
        let used_mem_bytes = self.sys.used_memory();
        let ram_used_gb = used_mem_bytes as f32 / (1024.0 * 1024.0 * 1024.0);
        let ram_total_gb = total_mem_bytes as f32 / (1024.0 * 1024.0 * 1024.0);
        let ram_percent = if total_mem_bytes > 0 {
            (used_mem_bytes as f32 / total_mem_bytes as f32) * 100.0
        } else {
            0.0
        };

        self.networks.refresh();
        let mut total_recv_bytes: u64 = 0;
        let mut total_send_bytes: u64 = 0;

        for (_name, net_data) in &self.networks {
            total_recv_bytes += net_data.received();
            total_send_bytes += net_data.transmitted();
        }

        let net_recv_speed_kb = (total_recv_bytes as f32 / dt) / 1024.0;
        let net_send_speed_kb = (total_send_bytes as f32 / dt) / 1024.0;
        let net_total_speed_kb = net_recv_speed_kb + net_send_speed_kb;

        let mut available_metrics = Vec::new();
        if !self.sys.cpus().is_empty() {
            available_metrics.push("cpu".to_string());
        }
        if total_mem_bytes > 0 {
            available_metrics.push("ram".to_string());
        }
        if !self.networks.is_empty() {
            available_metrics.push("network".to_string());
        }

        MetricsSnapshot {
            available_metrics,
            cpu_percent: (cpu_percent * 10.0).round() / 10.0,
            ram_percent: (ram_percent * 10.0).round() / 10.0,
            ram_used_gb: (ram_used_gb * 100.0).round() / 100.0,
            ram_total_gb: (ram_total_gb * 10.0).round() / 10.0,
            net_send_speed_kb: (net_send_speed_kb * 10.0).round() / 10.0,
            net_recv_speed_kb: (net_recv_speed_kb * 10.0).round() / 10.0,
            net_total_speed_kb: (net_total_speed_kb * 10.0).round() / 10.0,
            gpus: Vec::new(),
            has_npu: false,
            npu_percent: 0.0,
        }
    }
}
