use std::os::windows::io::AsRawHandle;
use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{
    CloseHandle, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, WAIT_OBJECT_0, WAIT_TIMEOUT,
};
use windows::Win32::System::JobObjects::*;
use windows::Win32::System::Threading::*;

pub struct Child {
    process: isize,
    job: isize,
}
impl Child {
    pub fn spawn(
        path: &std::path::Path,
        args: &[String],
        cwd: Option<&str>,
        env: &std::collections::HashMap<String, String>,
        log: Option<&str>,
    ) -> Result<Self, String> {
        let log_file = log
            .map(|p| {
                std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(p)
            })
            .transpose()
            .map_err(|e| e.to_string())?;
        unsafe {
            let job = CreateJobObjectW(None, PCWSTR::null()).map_err(|e| e.to_string())?;
            let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if let Err(error) = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as _,
                std::mem::size_of_val(&limits) as u32,
            ) {
                let _ = CloseHandle(job);
                return Err(error.to_string());
            }
            let executable: Vec<u16> = path
                .as_os_str()
                .to_string_lossy()
                .encode_utf16()
                .chain(Some(0))
                .collect();
            let mut parts = vec![quote_arg(&path.to_string_lossy())];
            parts.extend(args.iter().map(|a| quote_arg(a)));
            let mut command: Vec<u16> = parts.join(" ").encode_utf16().chain(Some(0)).collect();
            let directory = cwd.map(|p| p.encode_utf16().chain(Some(0)).collect::<Vec<_>>());
            let mut environment: std::collections::BTreeMap<_, _> = std::env::vars_os().collect();
            for (key, value) in env {
                environment.insert(key.into(), value.into());
            }
            let mut environment_block = Vec::<u16>::new();
            use std::os::windows::ffi::OsStrExt;
            for (key, value) in environment {
                environment_block.extend(key.encode_wide());
                environment_block.push('=' as u16);
                environment_block.extend(value.encode_wide());
                environment_block.push(0);
            }
            environment_block.push(0);
            let mut startup = STARTUPINFOW {
                cb: std::mem::size_of::<STARTUPINFOW>() as u32,
                ..Default::default()
            };
            if let Some(file) = &log_file {
                let handle = HANDLE(file.as_raw_handle());
                if let Err(error) =
                    SetHandleInformation(handle, HANDLE_FLAG_INHERIT.0, HANDLE_FLAG_INHERIT)
                {
                    let _ = CloseHandle(job);
                    return Err(error.to_string());
                }
                startup.dwFlags = STARTF_USESTDHANDLES;
                startup.hStdOutput = handle;
                startup.hStdError = handle;
            }
            let mut info = PROCESS_INFORMATION::default();
            if let Err(error) = CreateProcessW(
                PCWSTR(executable.as_ptr()),
                Some(PWSTR(command.as_mut_ptr())),
                None,
                None,
                log_file.is_some(),
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                Some(environment_block.as_ptr() as _),
                directory
                    .as_ref()
                    .map(|p| PCWSTR(p.as_ptr()))
                    .unwrap_or(PCWSTR::null()),
                &startup,
                &mut info,
            ) {
                let _ = CloseHandle(job);
                return Err(error.to_string());
            }
            if let Err(error) = AssignProcessToJobObject(job, info.hProcess) {
                let _ = TerminateProcess(info.hProcess, 1);
                let _ = CloseHandle(info.hThread);
                let _ = CloseHandle(info.hProcess);
                let _ = CloseHandle(job);
                return Err(error.to_string());
            }
            let resumed = ResumeThread(info.hThread);
            let _ = CloseHandle(info.hThread);
            if resumed == u32::MAX {
                let _ = TerminateJobObject(job, 1);
                let _ = CloseHandle(info.hProcess);
                let _ = CloseHandle(job);
                return Err("音声エンジンを開始できません。".into());
            }
            Ok(Self {
                process: info.hProcess.0 as isize,
                job: job.0 as isize,
            })
        }
    }
    pub fn running(&mut self) -> Result<bool, String> {
        unsafe {
            match WaitForSingleObject(HANDLE(self.process as _), 0) {
                WAIT_OBJECT_0 => Ok(false),
                WAIT_TIMEOUT => Ok(true),
                _ => Err(windows::core::Error::from_thread().to_string()),
            }
        }
    }
    pub fn close(&mut self) -> Result<(), String> {
        unsafe {
            let result = TerminateJobObject(HANDLE(self.job as _), 0).map_err(|e| e.to_string());
            WaitForSingleObject(HANDLE(self.process as _), 3000);
            result
        }
    }
    pub fn exit_code(&mut self) -> Result<Option<i32>, String> {
        if self.running()? {
            return Ok(None);
        }
        let mut code = 0;
        unsafe {
            GetExitCodeProcess(HANDLE(self.process as _), &mut code).map_err(|e| e.to_string())?;
        }
        Ok(Some(code as i32))
    }
}

fn quote_arg(value: &str) -> String {
    let mut result = String::from("\"");
    let mut slashes = 0;
    for ch in value.chars() {
        if ch == '\\' {
            slashes += 1;
            continue;
        }
        if ch == '"' {
            result.push_str(&"\\".repeat(slashes * 2 + 1));
        } else {
            result.push_str(&"\\".repeat(slashes));
        }
        result.push(ch);
        slashes = 0;
    }
    result.push_str(&"\\".repeat(slashes * 2));
    result.push('"');
    result
}
impl Drop for Child {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(HANDLE(self.job as _));
            let _ = CloseHandle(HANDLE(self.process as _));
        }
    }
}
