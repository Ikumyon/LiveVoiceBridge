pub mod providers;
pub mod traits;
pub mod types;

use pyo3::prelude::*;
use pyo3::types::PyDict;
use traits::MetricsProvider;

#[pyclass(name = "RustMetricsCollector")]
pub struct RustMetricsCollector {
    provider: Box<dyn MetricsProvider>,
}

#[pymethods]
impl RustMetricsCollector {
    #[new]
    pub fn new() -> Self {
        Self {
            provider: providers::create_metrics_provider(),
        }
    }

    /// メトリクスを収集し、Pythonの辞書形式 (dict) で返す
    pub fn collect<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let snapshot = self.provider.collect();
        snapshot.to_py_dict(py)
    }
}

/// PyO3 Python モジュール定義
#[pymodule]
fn livevoicebridge_metrics(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustMetricsCollector>()?;
    Ok(())
}
