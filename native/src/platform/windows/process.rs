use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{CloseHandle, HANDLE, WAIT_OBJECT_0, WAIT_TIMEOUT};
use windows::Win32::System::JobObjects::*;
use windows::Win32::System::Threading::*;

pub struct Child {
    process: isize,
    job: isize,
}
impl Child {
    pub fn spawn(path: &std::path::Path) -> Result<Self, String> {
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
            let mut command: Vec<u16> = format!("\"{}\"", path.display())
                .encode_utf16()
                .chain(Some(0))
                .collect();
            let startup = STARTUPINFOW {
                cb: std::mem::size_of::<STARTUPINFOW>() as u32,
                ..Default::default()
            };
            let mut info = PROCESS_INFORMATION::default();
            if let Err(error) = CreateProcessW(
                PCWSTR(executable.as_ptr()),
                PWSTR(command.as_mut_ptr()),
                None,
                None,
                false,
                CREATE_SUSPENDED | CREATE_NO_WINDOW,
                None,
                PCWSTR::null(),
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
                _ => Err(windows::core::Error::from_win32().to_string()),
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
}
impl Drop for Child {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(HANDLE(self.job as _));
            let _ = CloseHandle(HANDLE(self.process as _));
        }
    }
}
