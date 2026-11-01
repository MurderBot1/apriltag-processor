//! Wire protocol: CRC16, COBS framing, message encode/decode.

pub const MAX_BODY: usize = 256;
pub const MAX_FRAME: usize = MAX_BODY + 8;

pub const CMD_PING: u8 = 0x01;
pub const CMD_SET_CALIB: u8 = 0x02;
pub const CMD_CLEAR_MAP: u8 = 0x03;
pub const CMD_ADD_TAG: u8 = 0x04;
pub const CMD_COMMIT: u8 = 0x05;
pub const CMD_GET_CONFIG: u8 = 0x06;
pub const CMD_STREAM: u8 = 0x07;
pub const CMD_SET_SENSOR: u8 = 0x08;
pub const CMD_GET_STATUS: u8 = 0x09;
pub const CMD_SET_TRACK: u8 = 0x0A;
pub const CMD_GET_POSE: u8 = 0x0B;
pub const CMD_GET_TAG: u8 = 0x0C;
pub const CMD_GET_TAGS_RAW: u8 = 0x0D;
pub const CMD_SET_AE: u8 = 0x0E;
pub const CMD_GET_TIME: u8 = 0x0F;
pub const CMD_SET_AUTO_RATIO: u8 = 0x10;

pub const RSP_ACK: u8 = 0x80;
pub const RSP_PONG: u8 = 0x81;
pub const RSP_POSE: u8 = 0x82;
pub const RSP_TAGS: u8 = 0x83;
pub const RSP_CONFIG: u8 = 0x86;
pub const RSP_TAG: u8 = 0x87;
pub const RSP_STATUS: u8 = 0x89;
pub const RSP_TIME: u8 = 0x8A;
pub const RSP_NAK: u8 = 0xFF;

pub const ERR_BAD_LEN: u8 = 1;
pub const ERR_FULL: u8 = 2;
pub const ERR_FLASH: u8 = 3;
pub const ERR_UNKNOWN: u8 = 4;
pub const ERR_NO_POSE: u8 = 5;
pub const ERR_RANGE: u8 = 6;

pub fn err_name(code: u8) -> &'static str {
    match code {
        1 => "BAD_LEN",
        2 => "FULL",
        3 => "FLASH",
        4 => "UNKNOWN",
        5 => "NO_POSE",
        6 => "RANGE",
        _ => "?",
    }
}

/// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF).
pub fn crc16(data: &[u8]) -> u16 {
    let mut c: u16 = 0xFFFF;
    for &b in data {
        c ^= (b as u16) << 8;
        for _ in 0..8 {
            c = if c & 0x8000 != 0 { (c << 1) ^ 0x1021 } else { c << 1 };
        }
    }
    c
}

pub fn cobs_encode(raw: &[u8]) -> Vec<u8> {
    let mut out = vec![0u8];
    let (mut code_pos, mut code) = (0usize, 1u8);
    for &b in raw {
        if b == 0 {
            out[code_pos] = code;
            code_pos = out.len();
            out.push(0);
            code = 1;
        } else {
            out.push(b);
            code += 1;
            if code == 0xFF {
                out[code_pos] = code;
                code_pos = out.len();
                out.push(0);
                code = 1;
            }
        }
    }
    out[code_pos] = code;
    out
}

/// Returns None on malformed input.
pub fn cobs_decode(enc: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(enc.len());
    let (mut i, n) = (0usize, enc.len());
    while i < n {
        let code = enc[i] as usize;
        i += 1;
        if code == 0 || i + code - 1 > n {
            return None;
        }
        out.extend_from_slice(&enc[i..i + code - 1]);
        i += code - 1;
        if code != 0xFF && i < n {
            out.push(0);
        }
    }
    Some(out)
}

pub fn encode_frame(msg_type: u8, body: &[u8]) -> Vec<u8> {
    assert!(body.len() <= MAX_BODY, "body too large");
    let mut raw = Vec::with_capacity(body.len() + 3);
    raw.push(msg_type);
    raw.extend_from_slice(body);
    let c = crc16(&raw);
    raw.extend_from_slice(&c.to_le_bytes());
    let mut out = cobs_encode(&raw);
    out.push(0);
    out
}

/// Incremental decoder; garbage, bad CRC and oversized frames are dropped and counted.
#[derive(Default)]
pub struct FrameDecoder {
    buf: Vec<u8>,
    overflow: bool,
    pub bad_frames: u32,
    pub good_frames: u32,
}

impl FrameDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn feed(&mut self, data: &[u8]) -> Vec<(u8, Vec<u8>)> {
        let mut out = Vec::new();
        for &b in data {
            if b != 0 {
                if self.buf.len() < MAX_FRAME {
                    self.buf.push(b);
                } else {
                    self.overflow = true;
                }
                continue;
            }
            let enc = std::mem::take(&mut self.buf);
            let ovf = std::mem::replace(&mut self.overflow, false);
            if enc.is_empty() {
                continue;
            }
            let dec = if ovf { None } else { cobs_decode(&enc) };
            match dec {
                Some(d) if d.len() >= 3 && crc16(&d[..d.len() - 2]) == u16::from_le_bytes([d[d.len() - 2], d[d.len() - 1]]) => {
                    self.good_frames += 1;
                    out.push((d[0], d[1..d.len() - 2].to_vec()));
                }
                _ => self.bad_frames += 1,
            }
        }
        out
    }
}

// ------------------------------------------------------------------------------------------ messages
fn u16_at(b: &[u8], o: usize) -> u16 {
    u16::from_le_bytes(b[o..o + 2].try_into().unwrap())
}
fn u32_at(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes(b[o..o + 4].try_into().unwrap())
}
fn u64_at(b: &[u8], o: usize) -> u64 {
    u64::from_le_bytes(b[o..o + 8].try_into().unwrap())
}
pub(crate) fn f32_at(b: &[u8], o: usize) -> f32 {
    f32::from_le_bytes(b[o..o + 4].try_into().unwrap())
}

pub const POSE_LEN: usize = 52;
pub const STATUS_LEN: usize = 48;
pub const TIME_LEN: usize = 20;
pub const CONFIG_LEN: usize = 40;
pub const TAG_LEN: usize = 36;

pub const FLAG_AMBIGUOUS: u8 = 1;
pub const FLAG_OUTLIER_DROPPED: u8 = 2;
pub const FLAG_SINGLE_TAG: u8 = 4;

#[derive(Debug, Clone, PartialEq)]
pub struct Pose {
    pub frame_id: u32,
    pub processing_us: u32,
    pub ntags: u8,
    pub flags: u8,
    pub nobs: u16,
    /// Camera to world translation (m).
    pub position: [f32; 3],
    /// w, x, y, z
    pub quaternion: [f32; 4],
    pub rms_px: f32,
    /// Device clock at the start of the source frame.
    pub timestamp_us: u64,
}

pub fn decode_pose(b: &[u8]) -> Option<Pose> {
    if b.len() != POSE_LEN {
        return None;
    }
    Some(Pose {
        frame_id: u32_at(b, 0),
        processing_us: u32_at(b, 4),
        ntags: b[8],
        flags: b[9],
        nobs: u16_at(b, 10),
        position: [f32_at(b, 12), f32_at(b, 16), f32_at(b, 20)],
        quaternion: [f32_at(b, 24), f32_at(b, 28), f32_at(b, 32), f32_at(b, 36)],
        rms_px: f32_at(b, 40),
        timestamp_us: u64_at(b, 44),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeInfo {
    pub now_us: u64,
    pub frame_us: u64,
    pub tick_hz: u32,
}

pub fn decode_time(b: &[u8]) -> Option<TimeInfo> {
    if b.len() != TIME_LEN {
        return None;
    }
    Some(TimeInfo { now_us: u64_at(b, 0), frame_us: u64_at(b, 8), tick_hz: u32_at(b, 16) })
}

#[derive(Debug, Clone, PartialEq)]
pub struct Status {
    pub fpga_status: u32,
    pub ccl: u32,
    pub frames_dropped: u32,
    pub frames_total: u32,
    pub frames_processed: u32,
    pub solved: u32,
    pub solve_fail: u32,
    pub torn_reads: u32,
    pub frame_id: u32,
    pub ntags: u16,
    pub pose_valid: bool,
    pub streaming: bool,
    pub exposure: u16,
    pub gain: u8,
    pub ae_enabled: bool,
    pub mean_brightness: f32,
}

impl Status {
    pub fn init_done(&self) -> bool {
        self.fpga_status >> 3 & 1 != 0
    }
    pub fn tpu_busy(&self) -> bool {
        self.fpga_status >> 2 & 1 != 0
    }
    pub fn res_valid(&self) -> bool {
        self.fpga_status & 1 != 0
    }
    pub fn fpga_seq(&self) -> u16 {
        (self.fpga_status >> 16) as u16
    }
}

pub fn decode_status(b: &[u8]) -> Option<Status> {
    if b.len() != STATUS_LEN {
        return None;
    }
    Some(Status {
        fpga_status: u32_at(b, 0),
        ccl: u32_at(b, 4),
        frames_dropped: u32_at(b, 8),
        frames_total: u32_at(b, 12),
        frames_processed: u32_at(b, 16),
        solved: u32_at(b, 20),
        solve_fail: u32_at(b, 24),
        torn_reads: u32_at(b, 28),
        frame_id: u32_at(b, 32),
        ntags: u16_at(b, 36),
        pose_valid: b[38] != 0,
        streaming: b[39] != 0,
        exposure: u16_at(b, 40),
        gain: b[42],
        ae_enabled: b[43] != 0,
        mean_brightness: u16_at(b, 44) as f32 / 256.0,
    })
}
