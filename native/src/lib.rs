pub mod audio;
mod bindings;
mod platform;
mod playback;
mod process;
mod runtime;
pub mod text;
pub mod traits;
pub mod types;

#[cfg(not(any(target_os = "windows", target_os = "linux")))]
compile_error!("LiveVoiceBridge supports Windows and Linux.");

use pyo3::prelude::*;

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<bindings::RustMetricsCollector>()?;
    m.add_class::<bindings::Measurement>()?;
    m.add_class::<bindings::NativeGpu>()?;
    m.add_class::<bindings::NativeMetricsSnapshot>()?;
    m.add_class::<audio::AudioClip>()?;
    m.add_class::<playback::AudioPlayer>()?;
    m.add_class::<process::ManagedProcess>()?;
    m.add_class::<runtime::PlatformPaths>()?;
    m.add_class::<text::DictionaryMatcher>()?;
    m.add_class::<text::ParsedSegment>()?;
    m.add_function(wrap_pyfunction!(runtime::initialize_platform, m)?)?;
    m.add_function(wrap_pyfunction!(text::parse_comment, m)?)?;
    m.add_function(wrap_pyfunction!(text::split_sentences, m)?)?;
    m.add_function(wrap_pyfunction!(text::hiragana_to_katakana, m)?)?;
    Ok(())
}
