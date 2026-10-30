mod gpu;
mod input_method;
pub(crate) use gpu::LinuxGpuMetrics as GpuMetrics;
pub(crate) mod process;
mod sockets;
pub(crate) use sockets::SocketCounter;
pub const EXECUTABLE_FILTER: &str = "All Files (*)";
pub fn initialize() -> Result<(), String> {
    input_method::configure();
    Ok(())
}
