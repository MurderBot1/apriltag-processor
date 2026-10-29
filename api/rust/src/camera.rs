//! High level camera API over a Transport.
use crate::protocol::*;
use crate::transport::Transport;
use std::collections::VecDeque;
use std::fmt;
use std::io;
use std::time::{Duration, Instant};

#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    Timeout { cmd: u8 },
    Nak { cmd: u8, code: u8 },
    Protocol(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Io(e) => write!(f, "io error: {e}"),
            Error::Timeout { cmd } => write!(f, "no response to command 0x{cmd:02X}"),
            Error::Nak { cmd, code } => write!(f, "device NAK for command 0x{cmd:02X}: error {code} ({})", err_name(*code)),
            Error::Protocol(s) => write!(f, "protocol error: {s}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Calibration {
    pub fx: f32,
    pub fy: f32,
    pub cx: f32,
    pub cy: f32,
    /// k1, k2, p1, p2, k3
    pub dist: [f32; 5],
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TagDef {
    pub id: u16,
    pub size: f32,
    pub position: [f32; 3],
    /// w, x, y, z
    pub quat_wxyz: [f32; 4],
}

#[derive(Debug, Clone, PartialEq)]
pub struct Config {
    pub calibration: Calibration,
    pub tags: Vec<TagDef>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RawTag {
    pub id: u16,
    pub hamming: u8,
    /// TL, TR, BR, BL
    pub corners: [[f32; 2]; 4],
}

#[derive(Debug, Clone, PartialEq)]
pub struct TagsRaw {
    pub frame_id: u32,
    pub tags: Vec<RawTag>,
}

pub struct Camera<T: Transport> {
    t: T,
    pub timeout: Duration,
    pub retries: u32,
    clock: Box<dyn Fn() -> f64>,
    dec: FrameDecoder,
    poses: VecDeque<Pose>,
    inbox: VecDeque<(u8, Vec<u8>)>,
    pub frames_ignored: u32,
}

fn default_clock() -> Box<dyn Fn() -> f64> {
    let start = Instant::now();
    Box::new(move || start.elapsed().as_secs_f64())
}

impl<T: Transport> Camera<T> {
    /// Sends the lone 0x00 resync byte. Clock = seconds since construction (monotonic).
    pub fn new(t: T) -> Result<Self> {
        Self::with_clock(t, default_clock())
    }

    /// Custom host clock in seconds (must be monotonic); used for timeouts, RTTs and ClockSync.
    pub fn with_clock(mut t: T, clock: Box<dyn Fn() -> f64>) -> Result<Self> {
        t.write_all(&[0])?;
        Ok(Self {
            t,
            timeout: Duration::from_secs(1),
            retries: 2,
            clock,
            dec: FrameDecoder::new(),
            poses: VecDeque::new(),
            inbox: VecDeque::new(),
            frames_ignored: 0,
        })
    }

    pub fn now(&self) -> f64 {
        (self.clock)()
    }

    pub fn transport(&mut self) -> &mut T {
        &mut self.t
    }

    fn pump(&mut self, timeout: Duration) -> Result<bool> {
        let mut buf = [0u8; 4096];
        let n = self.t.read(&mut buf, timeout)?;
        if n == 0 {
            return Ok(false);
        }
        for (typ, body) in self.dec.feed(&buf[..n]) {
            if typ == RSP_POSE {
                match decode_pose(&body) {
                    Some(p) => self.poses.push_back(p),
                    None => {
                        self.frames_ignored += 1;
                        continue;
                    }
                }
                if self.poses.len() > 1024 {
                    self.poses.pop_front();
                }
            }
            self.inbox.push_back((typ, body));
        }
        Ok(true)
    }

    /// Sends and waits for the matching response; POSE frames received meanwhile are queued. NAK -> Error::Nak,
    /// silence is retried (commands are idempotent) and finally Error::Timeout.
    fn request(&mut self, cmd: u8, body: &[u8], rsp: u8, timeout: Option<Duration>, retries: Option<u32>) -> Result<Vec<u8>> {
        let timeout = timeout.unwrap_or(self.timeout).as_secs_f64();
        let retries = retries.unwrap_or(self.retries);
        for _ in 0..=retries {
            self.inbox.clear();
            self.t.write_all(&encode_frame(cmd, body))?;
            let deadline = self.now() + timeout;
            loop {
                while let Some((typ, b)) = self.inbox.pop_front() {
                    if typ == RSP_NAK && b.len() >= 2 && b[0] == cmd {
                        return Err(Error::Nak { cmd, code: b[1] });
                    }
                    if typ == rsp && (rsp != RSP_ACK || (!b.is_empty() && b[0] == cmd)) {
                        return Ok(b);
                    }
                    if typ != RSP_POSE {
                        self.frames_ignored += 1;
                    }
                }
                let remaining = deadline - self.now();
                if remaining <= 0.0 {
                    break;
                }
                self.pump(Duration::from_secs_f64(remaining.min(0.05)))?;
            }
        }
        Err(Error::Timeout { cmd })
    }

    fn ack(&mut self, cmd: u8, body: &[u8]) -> Result<()> {
        self.request(cmd, body, RSP_ACK, None, None).map(|_| ())
    }

    // ------------------------------------------------------------------------------------ commands
    /// Returns (firmware_version, fpga_id, rtt_s).
    pub fn ping(&mut self) -> Result<(u32, u32, f64)> {
        let t0 = self.now();
        let b = self.request(CMD_PING, b"ping", RSP_PONG, None, None)?;
        if b.len() != 12 {
            return Err(Error::Protocol("bad PONG length".into()));
        }
        Ok((u32::from_le_bytes(b[4..8].try_into().unwrap()), u32::from_le_bytes(b[8..12].try_into().unwrap()), self.now() - t0))
    }

    pub fn set_calibration(&mut self, c: &Calibration) -> Result<()> {
        let mut b = Vec::with_capacity(36);
        for v in [c.fx, c.fy, c.cx, c.cy].iter().chain(c.dist.iter()) {
            b.extend_from_slice(&v.to_le_bytes());
        }
        self.ack(CMD_SET_CALIB, &b)
    }

    pub fn clear_map(&mut self) -> Result<()> {
        self.ack(CMD_CLEAR_MAP, &[])
    }

    pub fn add_tag(&mut self, t: &TagDef) -> Result<()> {
        let mut b = Vec::with_capacity(34);
        b.extend_from_slice(&t.id.to_le_bytes());
        b.extend_from_slice(&t.size.to_le_bytes());
        for v in t.position.iter().chain(t.quat_wxyz.iter()) {
            b.extend_from_slice(&v.to_le_bytes());
        }
        self.ack(CMD_ADD_TAG, &b)
    }

    pub fn commit(&mut self) -> Result<()> {
        let to = self.timeout.max(Duration::from_secs(3));
        self.request(CMD_COMMIT, &[], RSP_ACK, Some(to), None).map(|_| ())
    }

    pub fn get_config(&mut self) -> Result<Config> {
        let b = self.request(CMD_GET_CONFIG, &[], RSP_CONFIG, None, None)?;
        if b.len() != CONFIG_LEN {
            return Err(Error::Protocol("bad CONFIG length".into()));
        }
        let f = |i: usize| f32_at(&b, i * 4);
        let calibration = Calibration { fx: f(0), fy: f(1), cx: f(2), cy: f(3), dist: [f(4), f(5), f(6), f(7), f(8)] };
        let n = u16::from_le_bytes([b[36], b[37]]);
        let tags = (0..n).map(|i| self.get_tag(i)).collect::<Result<Vec<_>>>()?;
        Ok(Config { calibration, tags })
    }

    pub fn get_tag(&mut self, index: u16) -> Result<TagDef> {
        let b = self.request(CMD_GET_TAG, &index.to_le_bytes(), RSP_TAG, None, None)?;
        if b.len() != TAG_LEN {
            return Err(Error::Protocol("bad TAG length".into()));
        }
        Ok(TagDef {
            id: u16::from_le_bytes([b[0], b[1]]),
            size: f32_at(&b, 4),
            position: [f32_at(&b, 8), f32_at(&b, 12), f32_at(&b, 16)],
            quat_wxyz: [f32_at(&b, 20), f32_at(&b, 24), f32_at(&b, 28), f32_at(&b, 32)],
        })
    }

    pub fn stream(&mut self, enable: bool, divider: u16) -> Result<()> {
        let d = divider.to_le_bytes();
        self.ack(CMD_STREAM, &[enable as u8, d[0], d[1]])
    }

    /// Manual exposure (lines, 1..800) and gain register (0x10 = 1x); disables auto exposure.
    pub fn set_sensor(&mut self, exposure: u16, gain: u8) -> Result<()> {
        let e = exposure.to_le_bytes();
        self.ack(CMD_SET_SENSOR, &[e[0], e[1], gain])
    }

    pub fn set_ae(&mut self, enable: bool) -> Result<()> {
        self.ack(CMD_SET_AE, &[enable as u8])
    }

    /// diff, abs_black, mindim, maxham (<= 63). Reset values 24, 64, 10, 2.
    pub fn set_track(&mut self, diff: u8, abs_black: u8, mindim: u8, maxham: u8) -> Result<()> {
        if maxham > 63 {
            return Err(Error::Protocol("maxham out of range".into()));
        }
        self.ack(CMD_SET_TRACK, &[diff, abs_black, mindim, maxham])
    }

    pub fn get_status(&mut self) -> Result<Status> {
        let b = self.request(CMD_GET_STATUS, &[], RSP_STATUS, None, None)?;
        decode_status(&b).ok_or_else(|| Error::Protocol("bad STATUS length".into()))
    }

    /// Latest solved pose; Error::Nak { code: ERR_NO_POSE } if none yet.
    pub fn get_pose(&mut self) -> Result<Pose> {
        let b = self.request(CMD_GET_POSE, &[], RSP_POSE, None, None)?;
        decode_pose(&b).ok_or_else(|| Error::Protocol("bad POSE length".into()))
    }

    pub fn get_tags_raw(&mut self) -> Result<TagsRaw> {
        let b = self.request(CMD_GET_TAGS_RAW, &[], RSP_TAGS, None, None)?;
        if b.len() < 5 || b.len() < 5 + 35 * b[4] as usize {
            return Err(Error::Protocol("bad TAGS length".into()));
        }
        let frame_id = u32::from_le_bytes(b[0..4].try_into().unwrap());
        let mut tags = Vec::new();
        for i in 0..b[4] as usize {
            let o = 5 + 35 * i;
            let mut corners = [[0f32; 2]; 4];
            for (k, c) in corners.iter_mut().enumerate() {
                *c = [f32_at(&b, o + 3 + 8 * k), f32_at(&b, o + 7 + 8 * k)];
            }
            tags.push(RawTag { id: u16::from_le_bytes([b[o], b[o + 1]]), hamming: b[o + 2], corners });
        }
        Ok(TagsRaw { frame_id, tags })
    }

    /// (t0, t1, time): host clock before send and after receive, plus the device reply. No retries, to keep the RTT honest.
    pub fn get_time_sample(&mut self) -> Result<(f64, f64, TimeInfo)> {
        let t0 = self.now();
        let b = self.request(CMD_GET_TIME, &[], RSP_TIME, None, Some(0))?;
        let t1 = self.now();
        let ti = decode_time(&b).ok_or_else(|| Error::Protocol("bad TIME length".into()))?;
        Ok((t0, t1, ti))
    }

    pub fn get_time(&mut self) -> Result<TimeInfo> {
        Ok(self.get_time_sample()?.2)
    }

    // ------------------------------------------------------------------------------------ poses
    /// Next queued streamed pose, waiting up to `timeout`.
    pub fn poll_pose(&mut self, timeout: Duration) -> Result<Option<Pose>> {
        let deadline = self.now() + timeout.as_secs_f64();
        loop {
            if let Some(p) = self.poses.pop_front() {
                return Ok(Some(p));
            }
            self.inbox.clear();
            let remaining = deadline - self.now();
            if remaining <= 0.0 {
                self.pump(Duration::ZERO)?;
                return Ok(self.poses.pop_front());
            }
            self.pump(Duration::from_secs_f64(remaining.min(0.05)))?;
        }
    }

    /// Enables streaming and returns an iterator of poses; streaming is disabled again when it is dropped.
    /// The iterator yields Err(Error::Timeout) if no pose arrives within `timeout`.
    pub fn poses(&mut self, divider: u16, timeout: Duration) -> Result<PoseStream<'_, T>> {
        self.stream(true, divider)?;
        Ok(PoseStream { cam: self, timeout })
    }

    /// Callback style: `f` returns false to stop.
    pub fn on_pose(&mut self, divider: u16, timeout: Duration, mut f: impl FnMut(&Pose) -> bool) -> Result<()> {
        for p in self.poses(divider, timeout)? {
            if !f(&p?) {
                break;
            }
        }
        Ok(())
    }
}

pub struct PoseStream<'a, T: Transport> {
    cam: &'a mut Camera<T>,
    timeout: Duration,
}

impl<T: Transport> Iterator for PoseStream<'_, T> {
    type Item = Result<Pose>;
    fn next(&mut self) -> Option<Self::Item> {
        match self.cam.poll_pose(self.timeout) {
            Ok(Some(p)) => Some(Ok(p)),
            Ok(None) => Some(Err(Error::Timeout { cmd: CMD_STREAM })),
            Err(e) => Some(Err(e)),
        }
    }
}

impl<T: Transport> Drop for PoseStream<'_, T> {
    fn drop(&mut self) {
        let _ = self.cam.stream(false, 1);
    }
}
