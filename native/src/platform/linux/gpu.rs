use crate::types::GpuMetric;
use std::path::PathBuf;
use std::time::{Duration, Instant};

struct Device {
    id: String,
    name: String,
    vendor: String,
    path: PathBuf,
    nvidia: Option<u32>,
}
pub struct LinuxGpuMetrics {
    nvml: Option<nvml_wrapper::Nvml>,
    devices: Vec<Device>,
    last_devices: Option<Instant>,
}
fn number(path: PathBuf) -> Option<f32> {
    std::fs::read_to_string(path).ok()?.trim().parse().ok()
}
impl LinuxGpuMetrics {
    pub fn new() -> Self {
        Self {
            nvml: nvml_wrapper::Nvml::init().ok(),
            devices: Vec::new(),
            last_devices: None,
        }
    }
    fn enumerate(&mut self) {
        if self.nvml.is_none() {
            self.nvml = nvml_wrapper::Nvml::init().ok();
        }
        let mut devices = Vec::new();
        if let Ok(entries) = std::fs::read_dir("/sys/class/drm") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                if !name
                    .strip_prefix("card")
                    .is_some_and(|v| !v.is_empty() && v.chars().all(|c| c.is_ascii_digit()))
                {
                    continue;
                }
                let Ok(path) = entry.path().join("device").canonicalize() else {
                    continue;
                };
                let vendor = std::fs::read_to_string(path.join("vendor"))
                    .unwrap_or_default()
                    .trim()
                    .to_string();
                let id = path
                    .file_name()
                    .map(|v| v.to_string_lossy().into_owned())
                    .unwrap_or(name);
                let product = std::fs::read_to_string(path.join("device"))
                    .unwrap_or_default()
                    .trim()
                    .to_string();
                let mut title = format!(
                    "GPU {}: {} {}",
                    devices.len(),
                    match vendor.as_str() {
                        "0x10de" => "NVIDIA",
                        "0x1002" => "AMD",
                        "0x8086" => "Intel",
                        _ => "PCI",
                    },
                    product
                );
                let mut nvidia = None;
                if vendor == "0x10de" {
                    if let Some(nvml) = &self.nvml {
                        for index in 0..nvml.device_count().unwrap_or(0) {
                            if let Ok(device) = nvml.device_by_index(index) {
                                if device.pci_info().is_ok_and(|pci| {
                                    pci.bus_id.to_lowercase().ends_with(&id.to_lowercase())
                                }) {
                                    if let Ok(name) = device.name() {
                                        title = format!("GPU {}: {name}", devices.len());
                                    }
                                    nvidia = Some(index);
                                    break;
                                }
                            }
                        }
                    }
                }
                devices.push(Device {
                    id: format!("pci_{id}"),
                    name: title,
                    vendor,
                    path,
                    nvidia,
                });
            }
        }
        devices.sort_by(|a, b| a.id.cmp(&b.id));
        self.devices = devices;
        self.last_devices = Some(Instant::now());
    }
    pub fn collect(&mut self) -> Vec<GpuMetric> {
        if self
            .last_devices
            .is_none_or(|time| time.elapsed() >= Duration::from_secs(10))
        {
            self.enumerate();
        }
        let gib = 1024.0_f32.powi(3);
        self.devices
            .iter()
            .map(|info| {
                let mut usage = None;
                let mut used = None;
                let mut total = None;
                if info.vendor == "0x1002" {
                    usage = number(info.path.join("gpu_busy_percent"));
                    used = number(info.path.join("mem_info_vram_used")).map(|v| v / gib);
                    total = number(info.path.join("mem_info_vram_total")).map(|v| v / gib);
                } else if let (Some(nvml), Some(index)) = (&self.nvml, info.nvidia) {
                    if let Ok(device) = nvml.device_by_index(index) {
                        usage = device.utilization_rates().ok().map(|v| v.gpu as f32);
                        if let Ok(memory) = device.memory_info() {
                            used = Some(memory.used as f32 / gib);
                            total = Some(memory.total as f32 / gib);
                        }
                    }
                }
                GpuMetric {
                    id: info.id.clone(),
                    name: info.name.clone(),
                    gpu_percent: usage,
                    usage_supported: info.vendor == "0x1002" || info.vendor == "0x10de",
                    vram_used_gb: used.unwrap_or(0.0),
                    vram_total_gb: total.unwrap_or(0.0),
                    vram_percent: used
                        .zip(total)
                        .filter(|(_, total)| *total > 0.0)
                        .map(|(used, total)| used / total * 100.0)
                        .unwrap_or(0.0),
                    has_vram: used.is_some() && total.is_some_and(|v| v > 0.0),
                }
            })
            .collect()
    }
}
