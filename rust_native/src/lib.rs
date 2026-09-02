pub mod audio;
pub mod providers;
pub mod text;
pub mod traits;
pub mod types;

use pyo3::prelude::*;
use pyo3::types::PyDict;
use traits::MetricsProvider;

#[pyclass(name = "RustMetricsCollector")]
pub struct RustMetricsCollector {
    provider: Box<dyn MetricsProvider>,
}

impl Default for RustMetricsCollector {
    fn default() -> Self {
        Self::new()
    }
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
fn livevoicebridge_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustMetricsCollector>()?;
    m.add_class::<text::DictionaryMatcher>()?;
    m.add_function(wrap_pyfunction!(audio::apply_audio_effects, m)?)?;
    m.add_function(wrap_pyfunction!(audio::float_audio_to_wav_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(text::parse_comment, m)?)?;
    m.add_function(wrap_pyfunction!(text::split_sentences, m)?)?;
    m.add_function(wrap_pyfunction!(text::hiragana_to_katakana, m)?)?;
    Ok(())
}
