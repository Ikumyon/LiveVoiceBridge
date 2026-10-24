use std::collections::HashMap;
use std::time::{Duration, Instant};
use windows::core::{w, PCWSTR};
use windows::Win32::Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1};
use windows::Win32::System::Performance::{
    PdhAddEnglishCounterW, PdhCloseQuery, PdhCollectQueryData, PdhGetFormattedCounterArrayW,
    PdhOpenQueryW, PDH_CSTATUS_NEW_DATA, PDH_CSTATUS_VALID_DATA, PDH_FMT_COUNTERVALUE_ITEM_W,
    PDH_FMT_DOUBLE, PDH_MORE_DATA,
};

use crate::types::GpuMetric;

type AdapterId = (u32, u32);

struct GpuQuery {
    handle: isize,
    engines: isize,
    memory: isize,
    engine_buffer: Vec<u64>,
    memory_buffer: Vec<u64>,
}

impl GpuQuery {
    fn new() -> Option<Self> {
        unsafe {
            let mut handle = 0;
            if PdhOpenQueryW(PCWSTR::null(), 0, &mut handle) != 0 {
                return None;
            }
            let mut query = Self {
                handle,
                engines: 0,
                memory: 0,
                engine_buffer: Vec::new(),
                memory_buffer: Vec::new(),
            };
            if PdhAddEnglishCounterW(
                handle,
                w!("\\GPU Engine(*)\\Utilization Percentage"),
                0,
                &mut query.engines,
            ) != 0
            {
                query.engines = 0;
            }
            if PdhAddEnglishCounterW(
                handle,
                w!("\\GPU Adapter Memory(*)\\Dedicated Usage"),
                0,
                &mut query.memory,
            ) != 0
            {
                query.memory = 0;
            }
            // Rate counters need two samples. Prime once and retain the query.
            PdhCollectQueryData(handle);
            Some(query)
        }
    }

    fn values(counter: isize, buffer: &mut Vec<u64>) -> Vec<(String, f64)> {
        if counter == 0 {
            return Vec::new();
        }
        unsafe {
            let mut bytes = 0;
            let mut count = 0;
            if PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &mut bytes, &mut count, None)
                != PDH_MORE_DATA
            {
                return Vec::new();
            }
            // A typed buffer supplies the alignment required by the PDH item array.
            for _ in 0..4 {
                if bytes > 4 * 1024 * 1024 {
                    return Vec::new();
                }
                buffer.resize((bytes as usize).div_ceil(8), 0);
                let status = PdhGetFormattedCounterArrayW(
                    counter,
                    PDH_FMT_DOUBLE,
                    &mut bytes,
                    &mut count,
                    Some(buffer.as_mut_ptr().cast()),
                );
                if status == PDH_MORE_DATA {
                    continue;
                }
                if status != 0
                    || count as usize
                        > buffer.len() * 8 / std::mem::size_of::<PDH_FMT_COUNTERVALUE_ITEM_W>()
                {
                    return Vec::new();
                }
                let items = std::slice::from_raw_parts(
                    buffer.as_ptr().cast::<PDH_FMT_COUNTERVALUE_ITEM_W>(),
                    count as usize,
                );
                return items
                    .iter()
                    .take(count as usize)
                    .filter_map(|item| {
                        if !matches!(
                            item.FmtValue.CStatus,
                            PDH_CSTATUS_VALID_DATA | PDH_CSTATUS_NEW_DATA
                        ) {
                            return None;
                        }
                        let value = item.FmtValue.Anonymous.doubleValue;
                        if !value.is_finite() || value < 0.0 || item.szName.is_null() {
                            return None;
                        }
                        Some((item.szName.to_string().ok()?, value))
                    })
                    .collect();
            }
        }
        Vec::new()
    }
}

impl Drop for GpuQuery {
    fn drop(&mut self) {
        unsafe {
            PdhCloseQuery(self.handle);
        }
    }
}

fn adapter_id(instance: &str) -> Option<AdapterId> {
    let (_, suffix) = instance.split_once("luid_")?;
    let mut parts = suffix.split('_');
    let high = u32::from_str_radix(parts.next()?.strip_prefix("0x")?, 16).ok()?;
    let low = u32::from_str_radix(parts.next()?.strip_prefix("0x")?, 16).ok()?;
    Some((high, low))
}

fn engine_id(instance: &str) -> Option<(AdapterId, u32, u32)> {
    let adapter = adapter_id(instance)?;
    let physical = instance
        .split_once("_phys_")?
        .1
        .split('_')
        .next()?
        .parse()
        .ok()?;
    let engine = instance
        .split_once("_eng_")?
        .1
        .split('_')
        .next()?
        .parse()
        .ok()?;
    Some((adapter, physical, engine))
}

pub struct WindowsGpuMetrics {
    query: Option<GpuQuery>,
    devices: Vec<(AdapterId, String, f64)>,
    last_devices: Option<Instant>,
}

impl WindowsGpuMetrics {
    pub fn new() -> Self {
        Self {
            query: GpuQuery::new(),
            devices: Vec::new(),
            last_devices: None,
        }
    }

    pub fn collect(&mut self) -> Vec<GpuMetric> {
        if self.query.is_none() {
            self.query = GpuQuery::new();
        }
        let mut engines = HashMap::new();
        let mut memory = HashMap::new();
        if let Some(query) = &mut self.query {
            if unsafe { PdhCollectQueryData(query.handle) } == 0 {
                for (instance, value) in GpuQuery::values(query.engines, &mut query.engine_buffer) {
                    if let Some(id) = engine_id(&instance) {
                        *engines.entry(id).or_insert(0.0) += value;
                    }
                }
                for (instance, value) in GpuQuery::values(query.memory, &mut query.memory_buffer) {
                    if let Some(id) = adapter_id(&instance) {
                        *memory.entry(id).or_insert(0.0) += value;
                    }
                }
            }
        }
        let mut usage: HashMap<AdapterId, f64> = HashMap::new();
        // Sum processes on the same engine, then use the busiest engine per GPU.
        // Summing different engines would overstate concurrent GPU activity.
        for ((adapter, _, _), value) in engines {
            let busiest = usage.entry(adapter).or_insert(0.0);
            *busiest = busiest.max(value);
        }
        if self
            .last_devices
            .is_none_or(|time| time.elapsed() >= Duration::from_secs(10))
        {
            if self.query.as_ref().is_some_and(|query| query.engines == 0) {
                self.query = GpuQuery::new();
            }
            self.devices = Self::enumerate();
            self.last_devices = Some(Instant::now());
        }
        self.devices
            .iter()
            .map(|(id, name, total)| {
                let used = memory.get(id).map(|bytes| bytes / 1024.0_f64.powi(3));
                GpuMetric {
                    id: format!("luid_{:08x}_{:08x}", id.0, id.1),
                    name: name.clone(),
                    gpu_percent: usage.get(id).map(|value| value.clamp(0.0, 100.0) as f32),
                    usage_supported: true,
                    vram_used_gb: used.unwrap_or(0.0) as f32,
                    vram_total_gb: *total as f32,
                    vram_percent: used
                        .filter(|_| *total > 0.0)
                        .map(|used| (used / total * 100.0) as f32)
                        .unwrap_or(0.0),
                    has_vram: *total > 0.0 && used.is_some(),
                }
            })
            .collect()
    }

    fn enumerate() -> Vec<(AdapterId, String, f64)> {
        let mut devices = Vec::new();
        unsafe {
            let Ok(factory) = CreateDXGIFactory1::<IDXGIFactory1>() else {
                return devices;
            };
            let mut index = 0;
            while let Ok(adapter) = factory.EnumAdapters1(index) {
                if let Ok(desc) = adapter.GetDesc1() {
                    if desc.Flags & 2 == 0 {
                        let id = (desc.AdapterLuid.HighPart as u32, desc.AdapterLuid.LowPart);
                        let name = String::from_utf16_lossy(&desc.Description)
                            .trim_end_matches('\0')
                            .to_string();
                        devices.push((
                            id,
                            format!("GPU {index}: {name}"),
                            desc.DedicatedVideoMemory as f64 / 1024.0_f64.powi(3),
                        ));
                    }
                }
                index += 1;
            }
        }
        devices
    }
}
