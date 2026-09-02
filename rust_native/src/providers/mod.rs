#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;
#[cfg(target_os = "windows")]
pub mod windows;

use crate::traits::MetricsProvider;

/// 実行環境のOSに応じた最適なMetricsProviderを生成して返す
pub fn create_metrics_provider() -> Box<dyn MetricsProvider> {
    #[cfg(target_os = "windows")]
    {
        Box::new(windows::WindowsMetricsProvider::new())
    }

    #[cfg(target_os = "linux")]
    {
        Box::new(linux::LinuxMetricsProvider::new())
    }

    #[cfg(target_os = "macos")]
    {
        Box::new(macos::MacosMetricsProvider::new())
    }

    #[cfg(not(any(target_os = "windows", target_os = "linux", target_os = "macos")))]
    {
        panic!("Unsupported operating system for metrics collection");
    }
}
