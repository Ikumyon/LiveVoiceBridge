use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::path::Path;
use std::sync::Mutex;

use crate::platform::process as os;

#[pyclass]
pub struct ManagedProcess {
    child: Mutex<Option<os::Child>>,
}

#[pymethods]
impl ManagedProcess {
    #[new]
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }
    fn start(&self, py: Python<'_>, executable: String) -> PyResult<()> {
        py.allow_threads(|| -> Result<(), String> {
            let path = Path::new(&executable)
                .canonicalize()
                .map_err(|e| e.to_string())?;
            let mut child = self.child.lock().map_err(|e| e.to_string())?;
            if child.is_some() {
                return Err("所有プロセスが既に存在します。".into());
            }
            *child = Some(os::Child::spawn(&path)?);
            Ok(())
        })
        .map_err(PyRuntimeError::new_err)
    }
    fn is_running(&self, py: Python<'_>) -> PyResult<bool> {
        py.allow_threads(|| {
            self.child
                .lock()
                .map_err(|e| e.to_string())?
                .as_mut()
                .map(|c| c.running())
                .unwrap_or(Ok(false))
        })
        .map_err(PyRuntimeError::new_err)
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.allow_threads(|| {
            if let Some(mut child) = self.child.lock().map_err(|e| e.to_string())?.take() {
                child.close()?;
            }
            Ok::<(), String>(())
        })
        .map_err(PyRuntimeError::new_err)
    }
}

impl Drop for ManagedProcess {
    fn drop(&mut self) {
        if let Ok(slot) = self.child.get_mut() {
            if let Some(mut child) = slot.take() {
                let _ = child.close();
            }
        }
    }
}
