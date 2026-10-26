//! Bounded, serialized stdio RPC owned by the host, including its process tree.
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::io::{BufRead, BufReader, Read, Write};
use std::sync::{mpsc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

const MAX_LINE: usize = 360 * 1024 * 1024;
const MAX_LOG: usize = 8 * 1024 * 1024;

struct Running {
    child: crate::platform::process::Child,
    requests: mpsc::SyncSender<(String, usize)>,
    replies: mpsc::Receiver<Result<String, String>>,
    readers: Vec<JoinHandle<()>>,
}

impl Running {
    fn close(&mut self) {
        let _ = self.child.close();
        // Closing the process tree releases blocked pipe readers and writers.
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
    }
}

#[pyclass]
pub struct PluginProcess {
    running: Mutex<Option<Running>>,
}

#[pymethods]
impl PluginProcess {
    #[new]
    fn new() -> Self {
        Self {
            running: Mutex::new(None),
        }
    }

    fn start(
        &self,
        py: Python<'_>,
        executable: String,
        args: Vec<String>,
        cwd: String,
        log: String,
    ) -> PyResult<()> {
        py.detach(|| -> Result<(), String> {
            let mut slot = self.running.lock().map_err(|e| e.to_string())?;
            if slot.is_some() {
                return Err("プラグインは既に実行中です。".into());
            }
            let path = std::path::Path::new(&executable)
                .canonicalize()
                .map_err(|e| e.to_string())?;
            let mut child = crate::platform::process::Child::spawn(
                &path,
                &args,
                Some(&cwd),
                &Default::default(),
                None,
                true,
            )?;
            let mut input = child.stdin.take().ok_or("stdin is missing")?;
            let output = child.stdout.take().ok_or("stdout is missing")?;
            let error = child.stderr.take().ok_or("stderr is missing")?;
            let existing = std::fs::metadata(&log).map(|info| info.len()).unwrap_or(0);
            let reset = existing >= MAX_LOG as u64;
            let log = match std::fs::OpenOptions::new()
                .create(true)
                .write(true)
                .append(!reset)
                .truncate(reset)
                .open(log)
            {
                Ok(file) => file,
                Err(error) => {
                    let _ = child.close();
                    return Err(error.to_string());
                }
            };
            let (requests, request_rx) = mpsc::sync_channel::<(String, usize)>(1);
            let (limits_tx, limits_rx) = mpsc::sync_channel::<usize>(1);
            let (reply_tx, replies) = mpsc::sync_channel(1);
            let writer = std::thread::spawn(move || {
                while let Ok((line, limit)) = request_rx.recv() {
                    if limits_tx.send(limit).is_err() {
                        break;
                    }
                    if input
                        .write_all(line.as_bytes())
                        .and_then(|_| input.write_all(b"\n"))
                        .and_then(|_| input.flush())
                        .is_err()
                    {
                        break;
                    }
                }
            });
            let reader = std::thread::spawn(move || {
                let mut output = BufReader::new(output);
                while let Ok(limit) = limits_rx.recv() {
                    let mut bytes = Vec::new();
                    let result = output
                        .by_ref()
                        .take((limit + 1) as u64)
                        .read_until(b'\n', &mut bytes)
                        .map_err(|e| e.to_string())
                        .and_then(|size| {
                            if size == 0 || size > limit || bytes.last() != Some(&b'\n') {
                                return Err(
                                    "プラグイン応答が欠落、不正、または容量超過です。".into()
                                );
                            }
                            String::from_utf8(bytes).map_err(|e| e.to_string())
                        });
                    let failed = result.is_err();
                    if reply_tx.send(result).is_err() || failed {
                        break;
                    }
                }
            });
            let stderr = std::thread::spawn(move || {
                let mut error = error;
                let mut log = log;
                let mut buffer = [0; 8192];
                // Drain stderr continuously, but bound persistent log output.
                let mut remaining =
                    MAX_LOG.saturating_sub(if reset { 0 } else { existing as usize });
                while let Ok(size) = error.read(&mut buffer) {
                    if size == 0 {
                        break;
                    }
                    let count = size.min(remaining);
                    let _ = log.write_all(&buffer[..count]);
                    remaining -= count;
                }
            });
            *slot = Some(Running {
                child,
                requests,
                replies,
                readers: vec![writer, reader, stderr],
            });
            Ok(())
        })
        .map_err(PyRuntimeError::new_err)
    }

    fn exchange(
        &self,
        py: Python<'_>,
        request: String,
        timeout: f64,
        response_limit: usize,
    ) -> PyResult<String> {
        py.detach(|| -> Result<String, String> {
            if request.len() > MAX_LINE
                || request.contains('\n')
                || !timeout.is_finite()
                || timeout <= 0.0
                || timeout > 300.0
                || response_limit == 0
                || response_limit > MAX_LINE
            {
                return Err("プラグイン要求または期限が不正です。".into());
            }
            let mut slot = self.running.lock().map_err(|e| e.to_string())?;
            let running = slot.as_mut().ok_or("プラグインは終了しています。")?;
            let result = running
                .requests
                .try_send((request, response_limit))
                .map_err(|e| e.to_string())
                .and_then(|_| {
                    running
                        .replies
                        .recv_timeout(Duration::from_secs_f64(timeout))
                        .map_err(|e| e.to_string())
                })
                .and_then(|r| r);
            if result.is_err() {
                if let Some(mut running) = slot.take() {
                    // Drop channels before joining, to unblock idle writer/readers.
                    let (dummy, _) = mpsc::sync_channel(1);
                    running.requests = dummy;
                    let (_, dummy_rx) = mpsc::sync_channel(1);
                    running.replies = dummy_rx;
                    running.close();
                }
            }
            result
        })
        .map_err(PyRuntimeError::new_err)
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            if let Some(mut running) = self.running.lock().map_err(|e| e.to_string())?.take() {
                let (dummy, _) = mpsc::sync_channel(1);
                running.requests = dummy;
                let (_, dummy_rx) = mpsc::sync_channel(1);
                running.replies = dummy_rx;
                running.close();
            }
            Ok::<(), String>(())
        })
        .map_err(PyRuntimeError::new_err)
    }
}

impl Drop for PluginProcess {
    fn drop(&mut self) {
        if let Ok(slot) = self.running.get_mut() {
            if let Some(mut running) = slot.take() {
                let (dummy, _) = mpsc::sync_channel(1);
                running.requests = dummy;
                let (_, dummy_rx) = mpsc::sync_channel(1);
                running.replies = dummy_rx;
                running.close();
            }
        }
    }
}

#[pyfunction]
pub fn plugin_platform() -> &'static str {
    if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}
