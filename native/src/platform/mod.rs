#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "linux")]
pub(crate) use linux::{initialize, process, SocketCounter, EXECUTABLE_FILTER};
#[cfg(target_os = "windows")]
pub(crate) use windows::{initialize, process, SocketCounter, EXECUTABLE_FILTER};

use crate::traits::MetricsProvider;
pub fn create_metrics_provider() -> Box<dyn MetricsProvider> {
    #[cfg(target_os = "windows")]
    {
        Box::new(windows::WindowsMetricsProvider::new())
    }
    #[cfg(target_os = "linux")]
    {
        Box::new(linux::LinuxMetricsProvider::new())
    }
}
