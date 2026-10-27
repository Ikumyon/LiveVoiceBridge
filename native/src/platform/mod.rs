#[cfg(target_os = "linux")]
mod linux;
mod metrics;
#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "linux")]
pub(crate) use linux::{initialize, process, GpuMetrics, SocketCounter, EXECUTABLE_FILTER};
#[cfg(target_os = "windows")]
pub(crate) use windows::{initialize, process, GpuMetrics, SocketCounter, EXECUTABLE_FILTER};

use crate::traits::MetricsProvider;
pub fn create_metrics_provider() -> Box<dyn MetricsProvider> {
    Box::new(metrics::SystemMetricsProvider::new())
}
