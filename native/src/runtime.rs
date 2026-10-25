use pyo3::exceptions::PyIOError;
use pyo3::prelude::*;
use std::path::{Path, PathBuf};

#[pyclass(frozen, get_all)]
pub struct PlatformPaths {
    pub root: String,
    pub config: String,
    pub dictionary: String,
    pub sounds: String,
    pub executable_filter: String,
}

fn portable_directory(root: &Path, relative: &str) -> std::io::Result<PathBuf> {
    let directory = root.join(relative);
    std::fs::create_dir_all(&directory)?;
    let resolved = directory.canonicalize()?;
    if !resolved.starts_with(root) {
        return Err(std::io::Error::other(
            "保存先がポータブル配置先の外を指しています。",
        ));
    }
    Ok(resolved)
}

#[pymethods]
impl PlatformPaths {
    #[new]
    #[pyo3(signature = (source_root=None))]
    fn new(source_root: Option<String>) -> PyResult<Self> {
        let root = if let Some(source) = source_root {
            PathBuf::from(source).canonicalize()
        } else {
            std::env::current_exe().and_then(|exe| {
                exe.parent()
                    .ok_or_else(|| std::io::Error::other("EXEの配置先を取得できません。"))
                    .and_then(Path::canonicalize)
            })
        }
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
        let data =
            portable_directory(&root, "data").map_err(|e| PyIOError::new_err(e.to_string()))?;
        let sounds = portable_directory(&root, "data/sounds")
            .map_err(|e| PyIOError::new_err(e.to_string()))?;
        Ok(Self {
            root: root.to_string_lossy().into_owned(),
            config: data.join("config.json").to_string_lossy().into_owned(),
            dictionary: data.join("dictionary.db").to_string_lossy().into_owned(),
            sounds: sounds.to_string_lossy().into_owned(),
            executable_filter: crate::platform::EXECUTABLE_FILTER.into(),
        })
    }
}

#[pyfunction]
pub fn initialize_platform() -> PyResult<()> {
    crate::platform::initialize().map_err(PyIOError::new_err)
}

#[pyfunction]
pub fn qwen_platform() -> PyResult<(String, String)> {
    if !cfg!(target_arch = "x86_64") {
        return Err(PyIOError::new_err("Qwenの自動導入はx86_64環境が対象です。"));
    }
    #[cfg(target_os = "windows")]
    {
        Ok(("windows".into(), "python/python.exe".into()))
    }
    #[cfg(target_os = "linux")]
    {
        Ok(("linux".into(), "python/bin/python3".into()))
    }
}
