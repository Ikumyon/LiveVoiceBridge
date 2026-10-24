#[derive(Debug, Clone)]
pub struct GpuMetric {
    pub id: String,
    pub name: String,
    pub gpu_percent: Option<f32>,
    pub usage_supported: bool,
    pub vram_used_gb: f32,
    pub vram_total_gb: f32,
    pub vram_percent: f32,
    pub has_vram: bool,
}

#[derive(Debug, Clone)]
pub struct MetricsSnapshot {
    pub available_metrics: Vec<String>,
    pub cpu_percent: f32,
    pub ram_percent: f32,
    pub ram_used_gb: f32,
    pub ram_total_gb: f32,
    pub net_send_speed_kb: f32,
    pub net_recv_speed_kb: f32,
    pub net_total_speed_kb: f32,
    pub gpus: Vec<GpuMetric>,
}
