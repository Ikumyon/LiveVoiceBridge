use std::time::Instant;
use sysinfo::{CpuRefreshKind, MemoryRefreshKind, Networks, RefreshKind, System};
use windows::core::PCWSTR;
use windows::Win32::Devices::DeviceAndDriverInstallation::{
    SetupDiDestroyDeviceInfoList, SetupDiEnumDeviceInfo, SetupDiGetClassDevsW,
    SetupDiGetDeviceRegistryPropertyW, DIGCF_ALLCLASSES, DIGCF_PRESENT, HDEVINFO, SPDRP_DEVICEDESC,
    SPDRP_FRIENDLYNAME, SP_DEVINFO_DATA,
};
use windows::Win32::Foundation::HWND;

use crate::traits::MetricsProvider;
use crate::types::{GpuMetric, MetricsSnapshot};

pub struct WindowsMetricsProvider {
    sys: System,
    networks: Networks,
    last_collect_time: Instant,
    nvml: Option<nvml_wrapper::Nvml>,
    has_npu: bool,
}

impl Default for WindowsMetricsProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl WindowsMetricsProvider {
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

        let nvml = nvml_wrapper::Nvml::init().ok();

        let has_npu = Self::check_npu_available();

        Self {
            sys,
            networks,
            last_collect_time: Instant::now(),
            nvml,
            has_npu,
        }
    }

    fn check_npu_available() -> bool {
        unsafe {
            let Ok(device_set) = SetupDiGetClassDevsW(
                None,
                PCWSTR::null(),
                HWND::default(),
                DIGCF_PRESENT | DIGCF_ALLCLASSES,
            ) else {
                return false;
            };

            let mut found = false;
            let mut index = 0u32;
            loop {
                let mut device_info = SP_DEVINFO_DATA {
                    cbSize: std::mem::size_of::<SP_DEVINFO_DATA>() as u32,
                    ..Default::default()
                };
                if SetupDiEnumDeviceInfo(device_set, index, &mut device_info).is_err() {
                    break;
                }
                index += 1;

                for property in [SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC] {
                    if let Some(name) = Self::device_property(device_set, &device_info, property) {
                        let normalized = name.to_lowercase();
                        if normalized.contains("npu")
                            || normalized.contains("neural processing")
                            || normalized.contains("ai boost")
                            || normalized.contains("neural processor")
                            || normalized.contains("amd ipu")
                        {
                            found = true;
                            break;
                        }
                    }
                }
                if found {
                    break;
                }
            }
            let _ = SetupDiDestroyDeviceInfoList(device_set);
            found
        }
    }

    unsafe fn device_property(
        device_set: HDEVINFO,
        device_info: &SP_DEVINFO_DATA,
        property: windows::Win32::Devices::DeviceAndDriverInstallation::SETUP_DI_REGISTRY_PROPERTY,
    ) -> Option<String> {
        let mut buffer = vec![0u8; 2048];
        SetupDiGetDeviceRegistryPropertyW(
            device_set,
            device_info,
            property,
            None,
            Some(&mut buffer),
            None,
        )
        .ok()?;
        let utf16: Vec<u16> = buffer
            .chunks_exact(2)
            .map(|bytes| u16::from_le_bytes([bytes[0], bytes[1]]))
            .take_while(|value| *value != 0)
            .collect();
        Some(String::from_utf16_lossy(&utf16))
    }

    fn collect_gpus(&self) -> Vec<GpuMetric> {
        let mut gpus = Vec::new();

        // 1. NVIDIA NVML 経由の取得
        if let Some(ref nvml) = self.nvml {
            if let Ok(count) = nvml.device_count() {
                for i in 0..count {
                    if let Ok(device) = nvml.device_by_index(i) {
                        let name = device.name().unwrap_or_else(|_| format!("GPU {}", i));
                        let util = device
                            .utilization_rates()
                            .map(|u| u.gpu as f32)
                            .unwrap_or(0.0);

                        let (vram_used_gb, vram_total_gb, vram_percent, has_vram) =
                            if let Ok(mem) = device.memory_info() {
                                let used = mem.used as f32 / (1024.0 * 1024.0 * 1024.0);
                                let total = mem.total as f32 / (1024.0 * 1024.0 * 1024.0);
                                let pct = if total > 0.0 {
                                    (used / total) * 100.0
                                } else {
                                    0.0
                                };
                                (used, total, pct, total > 0.0)
                            } else {
                                (0.0, 0.0, 0.0, false)
                            };

                        gpus.push(GpuMetric {
                            id: format!("nvidia_{}", i),
                            name: format!("GPU {}: {}", i, name),
                            gpu_percent: (util * 10.0).round() / 10.0,
                            vram_used_gb: (vram_used_gb * 100.0).round() / 100.0,
                            vram_total_gb: (vram_total_gb * 10.0).round() / 10.0,
                            vram_percent: (vram_percent * 10.0).round() / 10.0,
                            has_vram,
                        });
                    }
                }
            }
        }

        // 2. NVML で取得できなかった場合、DXGI (DirectX) API でシステムGPUを列挙
        if gpus.is_empty() {
            unsafe {
                use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1};
                if let Ok(factory) = CreateDXGIFactory1::<IDXGIFactory1>() {
                    let mut index = 0;
                    while let Ok(adapter) = factory.EnumAdapters1(index) {
                        if let Ok(desc) = adapter.GetDesc1() {
                            // ソフトウェアレンダラー（Flags & 2）を除外
                            if (desc.Flags & 2) == 0 {
                                let name = String::from_utf16_lossy(&desc.Description)
                                    .trim_matches(char::from(0))
                                    .to_string();

                                let vram_dedicated =
                                    desc.DedicatedVideoMemory as f32 / (1024.0 * 1024.0 * 1024.0);
                                let vram_shared =
                                    desc.SharedSystemMemory as f32 / (1024.0 * 1024.0 * 1024.0);
                                let total_vram = if vram_dedicated > 0.1 {
                                    vram_dedicated
                                } else {
                                    vram_shared * 0.5
                                };

                                gpus.push(GpuMetric {
                                    id: format!("dxgi_{}", index),
                                    name: format!("GPU {}: {}", index, name),
                                    gpu_percent: 0.0,
                                    vram_used_gb: 0.0,
                                    vram_total_gb: (total_vram * 10.0).round() / 10.0,
                                    vram_percent: 0.0,
                                    has_vram: total_vram > 0.1,
                                });
                            }
                        }
                        index += 1;
                    }
                }
            }
        }

        gpus
    }
}

impl MetricsProvider for WindowsMetricsProvider {
    fn collect(&mut self) -> MetricsSnapshot {
        let now = Instant::now();
        let dt = now
            .duration_since(self.last_collect_time)
            .as_secs_f32()
            .max(0.001);
        self.last_collect_time = now;

        // CPU
        self.sys.refresh_cpu();
        let cpu_percent = self.sys.global_cpu_info().cpu_usage();

        // Memory
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

        // Networks
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

        // GPUs
        let gpus = self.collect_gpus();

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
        if self.has_npu {
            available_metrics.push("npu".to_string());
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
            gpus,
            has_npu: self.has_npu,
            npu_percent: 0.0,
        }
    }
}
