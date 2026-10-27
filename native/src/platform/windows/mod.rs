mod gpu;
pub(crate) use gpu::WindowsGpuMetrics as GpuMetrics;
pub(crate) mod process;
mod sockets;
pub(crate) use sockets::SocketCounter;
pub const EXECUTABLE_FILTER: &str = "Executable Files (*.exe);;All Files (*)";

pub fn initialize() -> Result<(), String> {
    #[link(name = "shell32")]
    extern "system" {
        fn SetCurrentProcessExplicitAppUserModelID(id: *const u16) -> i32;
    }
    let id: Vec<u16> = "Ikumyon.LiveVoiceBridge.App\0".encode_utf16().collect();
    let status = unsafe { SetCurrentProcessExplicitAppUserModelID(id.as_ptr()) };
    if status < 0 {
        Err(format!("アプリID設定失敗: {status}"))
    } else {
        Ok(())
    }
}
