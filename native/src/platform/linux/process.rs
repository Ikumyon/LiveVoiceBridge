use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
pub struct Child {
    child: std::process::Child,
    group: Option<i32>,
}
impl Child {
    pub fn spawn(
        path: &std::path::Path,
        args: &[String],
        cwd: Option<&str>,
        env: &std::collections::HashMap<String, String>,
        log: Option<&str>,
    ) -> Result<Self, String> {
        let mut command = Command::new(path);
        command.args(args).envs(env).process_group(0);
        if let Some(directory) = cwd {
            command.current_dir(directory);
        }
        if let Some(log) = log {
            let file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(log)
                .map_err(|e| e.to_string())?;
            command
                .stdout(file.try_clone().map_err(|e| e.to_string())?)
                .stderr(file);
        } else {
            command.stdout(Stdio::null()).stderr(Stdio::null());
        }
        let child = command
            .stdin(Stdio::null())
            .spawn()
            .map_err(|e| e.to_string())?;
        let group = child.id() as i32;
        Ok(Self {
            child,
            group: Some(group),
        })
    }
    pub fn running(&mut self) -> Result<bool, String> {
        Ok(self.child.try_wait().map_err(|e| e.to_string())?.is_none())
    }
    pub fn exit_code(&mut self) -> Result<Option<i32>, String> {
        Ok(self
            .child
            .try_wait()
            .map_err(|e| e.to_string())?
            .map(|s| s.code().unwrap_or(-1)))
    }
    pub fn close(&mut self) -> Result<(), String> {
        let Some(group) = self.group.take() else {
            return Ok(());
        };
        unsafe {
            libc::kill(-group, libc::SIGTERM);
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if unsafe { libc::kill(-group, 0) } != 0 {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        unsafe {
            libc::kill(-group, libc::SIGKILL);
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if self.child.try_wait().map_err(|e| e.to_string())?.is_some() {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        Err("所有プロセスの終了待ちがタイムアウトしました。".into())
    }
}
impl Drop for Child {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
