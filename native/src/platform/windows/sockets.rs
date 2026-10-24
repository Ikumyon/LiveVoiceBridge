pub struct SocketCounter {
    buffer: Vec<u64>,
}

impl SocketCounter {
    pub fn new() -> Self {
        Self { buffer: Vec::new() }
    }
    fn table<T: Copy>(
        &mut self,
        tcp: bool,
        family: u32,
        offset: usize,
        pid: impl Fn(T) -> u32,
    ) -> Option<usize> {
        use windows::Win32::NetworkManagement::IpHelper::*;
        let mut bytes = 0;
        let call = |pointer, size: &mut u32| unsafe {
            if tcp {
                GetExtendedTcpTable(pointer, size, false, family, TCP_TABLE_OWNER_PID_ALL, 0)
            } else {
                GetExtendedUdpTable(pointer, size, false, family, UDP_TABLE_OWNER_PID, 0)
            }
        };
        let first = call(None, &mut bytes);
        if first != 0 && first != 122 {
            return None;
        }
        for _ in 0..4 {
            if bytes > 4 * 1024 * 1024 {
                return None;
            }
            self.buffer.resize((bytes as usize).div_ceil(8).max(1), 0);
            let status = call(Some(self.buffer.as_mut_ptr().cast()), &mut bytes);
            if status == 122 {
                continue;
            }
            if status != 0 {
                return None;
            }
            let pointer = self.buffer.as_ptr().cast::<u8>();
            let count = unsafe { pointer.cast::<u32>().read_unaligned() } as usize;
            if offset.checked_add(count.checked_mul(std::mem::size_of::<T>())?)?
                > self.buffer.len() * 8
            {
                return None;
            }
            let own = std::process::id();
            return Some(
                (0..count)
                    .filter(|index| {
                        let row = unsafe {
                            pointer
                                .add(offset + index * std::mem::size_of::<T>())
                                .cast::<T>()
                                .read_unaligned()
                        };
                        pid(row) == own
                    })
                    .count(),
            );
        }
        None
    }
    pub fn count(&mut self) -> Option<usize> {
        use windows::Win32::NetworkManagement::IpHelper::*;
        Some(
            self.table::<MIB_TCPROW_OWNER_PID>(
                true,
                2,
                std::mem::offset_of!(MIB_TCPTABLE_OWNER_PID, table),
                |r| r.dwOwningPid,
            )? + self.table::<MIB_TCP6ROW_OWNER_PID>(
                true,
                23,
                std::mem::offset_of!(MIB_TCP6TABLE_OWNER_PID, table),
                |r| r.dwOwningPid,
            )? + self.table::<MIB_UDPROW_OWNER_PID>(
                false,
                2,
                std::mem::offset_of!(MIB_UDPTABLE_OWNER_PID, table),
                |r| r.dwOwningPid,
            )? + self.table::<MIB_UDP6ROW_OWNER_PID>(
                false,
                23,
                std::mem::offset_of!(MIB_UDP6TABLE_OWNER_PID, table),
                |r| r.dwOwningPid,
            )?,
        )
    }
}
