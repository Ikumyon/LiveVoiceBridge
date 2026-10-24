use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
pub struct Child {
    child: std::process::Child,
    group: Option<i32>,
}
impl Child {
    pub fn spawn(path: &std::path::Path) -> Result<Self, String> {
        let child = Command::new(path)
            .process_group(0)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| e.to_string())?;
        let group = child.id() as i32;
        Ok(Self {
            child,
            group: Some(group),
        })
    }
    pub fn running(&mut self) -> Result<bool, String> {
        let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
        let result = unsafe {
            libc::waitid(
                libc::P_PID,
                self.child.id(),
                &mut info,
                libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
            )
        };
        if result != 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        Ok(unsafe { info.si_pid() } == 0)
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
