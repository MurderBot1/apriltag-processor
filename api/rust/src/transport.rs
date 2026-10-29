//! Byte transports: serial port (feature `serial`) and an in-memory loopback.
use std::collections::VecDeque;
use std::io;
use std::time::Duration;

pub trait Transport {
    fn write_all(&mut self, data: &[u8]) -> io::Result<()>;
    /// Reads up to `buf.len()` bytes, waiting at most `timeout`; Ok(0) on timeout.
    fn read(&mut self, buf: &mut [u8], timeout: Duration) -> io::Result<usize>;
}

/// In-memory transport. The optional handler (a fake device) sees every write and returns bytes to make readable.
pub struct LoopbackTransport {
    handler: Option<Box<dyn FnMut(&[u8]) -> Vec<u8>>>,
    rx: VecDeque<u8>,
    pub written: Vec<Vec<u8>>,
}

impl LoopbackTransport {
    pub fn new() -> Self {
        Self { handler: None, rx: VecDeque::new(), written: Vec::new() }
    }

    pub fn with_handler(h: impl FnMut(&[u8]) -> Vec<u8> + 'static) -> Self {
        Self { handler: Some(Box::new(h)), ..Self::new() }
    }

    /// Queues device-originated bytes (streamed frames, garbage, ...).
    pub fn inject(&mut self, data: &[u8]) {
        self.rx.extend(data.iter().copied());
    }
}

impl Default for LoopbackTransport {
    fn default() -> Self {
        Self::new()
    }
}

impl Transport for LoopbackTransport {
    fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
        self.written.push(data.to_vec());
        if let Some(h) = self.handler.as_mut() {
            let out = h(data);
            self.rx.extend(out);
        }
        Ok(())
    }

    fn read(&mut self, buf: &mut [u8], timeout: Duration) -> io::Result<usize> {
        if self.rx.is_empty() {
            std::thread::sleep(timeout.min(Duration::from_millis(1)));
            return Ok(0);
        }
        let n = buf.len().min(self.rx.len());
        for slot in buf.iter_mut().take(n) {
            *slot = self.rx.pop_front().unwrap();
        }
        Ok(n)
    }
}
