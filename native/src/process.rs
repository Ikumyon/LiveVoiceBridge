use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::collections::HashMap;
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
    #[pyo3(signature = (executable, args=Vec::new(), cwd=None, env=None, log=None))]
    fn start(
        &self,
        py: Python<'_>,
        executable: String,
        args: Vec<String>,
        cwd: Option<String>,
        env: Option<HashMap<String, String>>,
        log: Option<String>,
    ) -> PyResult<()> {
        py.detach(|| -> Result<(), String> {
            let path = Path::new(&executable)
                .canonicalize()
                .map_err(|e| e.to_string())?;
            let mut child = self.child.lock().map_err(|e| e.to_string())?;
            if child.is_some() {
                return Err("所有プロセスが既に存在します。".into());
            }
            *child = Some(os::Child::spawn(
                &path,
                &args,
                cwd.as_deref(),
                &env.unwrap_or_default(),
                log.as_deref(),
                false,
            )?);
            Ok(())
        })
        .map_err(PyRuntimeError::new_err)
    }
    fn exit_code(&self, py: Python<'_>) -> PyResult<Option<i32>> {
        py.detach(|| {
            self.child
                .lock()
                .map_err(|e| e.to_string())?
                .as_mut()
                .map(|c| c.exit_code())
                .unwrap_or(Ok(None))
        })
        .map_err(PyRuntimeError::new_err)
    }
    fn is_running(&self, py: Python<'_>) -> PyResult<bool> {
        py.detach(|| {
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
        py.detach(|| {
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
