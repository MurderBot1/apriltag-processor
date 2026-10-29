//! Serial port transport (crate `serialport`).
use apriltag_camera::Transport;
use std::io;
use std::time::Duration;

pub struct SerialTransport {
    port: Box<dyn serialport::SerialPort>,
}

impl SerialTransport {
    pub fn open(path: &str) -> io::Result<Self> {
        let port = serialport::new(path, 115_200)
            .timeout(Duration::from_millis(10))
            .open()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, e.to_string()))?;
        Ok(Self { port })
    }
}

impl Transport for SerialTransport {
    fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
        use std::io::Write;
        self.port.write_all(data)?;
        self.port.flush()
    }

    fn read(&mut self, buf: &mut [u8], timeout: Duration) -> io::Result<usize> {
        use std::io::Read;
        self.port.set_timeout(timeout.max(Duration::from_millis(1))).map_err(|e| io::Error::new(io::ErrorKind::Other, e.to_string()))?;
        match self.port.read(buf) {
            Ok(n) => Ok(n),
            Err(e) if e.kind() == io::ErrorKind::TimedOut => Ok(0),
            Err(e) => Err(e),
        }
    }
}
