use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuMetric {
    pub id: String,
    pub name: String,
    pub gpu_percent: f32,
    pub vram_used_gb: f32,
    pub vram_total_gb: f32,
    pub vram_percent: f32,
    pub has_vram: bool,
}

impl GpuMetric {
    pub fn to_py_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("id", &self.id)?;
        dict.set_item("name", &self.name)?;
        dict.set_item("gpu_percent", self.gpu_percent)?;
        dict.set_item("vram_used_gb", self.vram_used_gb)?;
        dict.set_item("vram_total_gb", self.vram_total_gb)?;
        dict.set_item("vram_percent", self.vram_percent)?;
        dict.set_item("has_vram", self.has_vram)?;
        Ok(dict)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricsSnapshot {
    pub cpu_percent: f32,
    pub ram_percent: f32,
    pub ram_used_gb: f32,
    pub ram_total_gb: f32,
    pub net_send_speed_kb: f32,
    pub net_recv_speed_kb: f32,
    pub net_total_speed_kb: f32,
    pub gpus: Vec<GpuMetric>,
    pub has_npu: bool,
    pub npu_percent: f32,
}

impl MetricsSnapshot {
    pub fn to_py_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("cpu_percent", self.cpu_percent)?;
        dict.set_item("ram_percent", self.ram_percent)?;
        dict.set_item("ram_used_gb", self.ram_used_gb)?;
        dict.set_item("ram_total_gb", self.ram_total_gb)?;
        dict.set_item("net_send_speed_kb", self.net_send_speed_kb)?;
        dict.set_item("net_recv_speed_kb", self.net_recv_speed_kb)?;
        dict.set_item("net_total_speed_kb", self.net_total_speed_kb)?;

        let gpus_list = pyo3::types::PyList::empty(py);
        for gpu in &self.gpus {
            gpus_list.append(gpu.to_py_dict(py)?)?;
        }
        dict.set_item("gpus", gpus_list)?;

        dict.set_item("has_npu", self.has_npu)?;
        dict.set_item("npu_percent", self.npu_percent)?;

        Ok(dict)
    }
}
