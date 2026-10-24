use std::collections::HashSet;
use std::io::BufRead;

pub struct SocketCounter {
    line: String,
}
impl SocketCounter {
    pub fn new() -> Self {
        Self {
            line: String::with_capacity(512),
        }
    }
    pub fn count(&mut self) -> Option<usize> {
        let mut owned = HashSet::new();
        for entry in std::fs::read_dir("/proc/self/fd").ok()? {
            let path = entry.ok()?.path();
            match std::fs::read_link(path) {
                Ok(link) => {
                    let value = link.to_string_lossy();
                    if let Some(inode) = value
                        .strip_prefix("socket:[")
                        .and_then(|v| v.strip_suffix(']'))
                    {
                        owned.insert(inode.to_string());
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => return None,
            }
        }
        let mut found = HashSet::new();
        for name in ["tcp", "tcp6", "udp", "udp6"] {
            let file = match std::fs::File::open(format!("/proc/self/net/{name}")) {
                Ok(value) => value,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(_) => return None,
            };
            let mut reader = std::io::BufReader::new(file);
            self.line.clear();
            reader.read_line(&mut self.line).ok()?;
            loop {
                self.line.clear();
                if reader.read_line(&mut self.line).ok()? == 0 {
                    break;
                }
                if let Some(inode) = self.line.split_whitespace().nth(9) {
                    if owned.contains(inode) {
                        found.insert(inode.to_string());
                    }
                }
            }
        }
        Some(found.len())
    }
}
