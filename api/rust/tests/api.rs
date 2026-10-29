use apriltag_camera::protocol::*;
use apriltag_camera::*;
use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::time::Duration;

fn hex(s: &str) -> Vec<u8> {
    if s == "-" {
        return vec![];
    }
    (0..s.len() / 2).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect()
}

struct Golden {
    name: String,
    typ: u8,
    body: Vec<u8>,
    frame: Vec<u8>,
}

fn golden() -> Vec<Golden> {
    let path = format!("{}/../testdata/golden_frames.txt", env!("CARGO_MANIFEST_DIR"));
    std::fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|l| {
            let p: Vec<&str> = l.split(' ').collect();
            Golden { name: p[0].into(), typ: p[1].parse().unwrap(), body: hex(p[2]), frame: hex(p[3]) }
        })
        .collect()
}

fn g(name: &str) -> Golden {
    golden().into_iter().find(|x| x.name == name).unwrap()
}

#[test]
fn crc_check_value() {
    assert_eq!(crc16(b"123456789"), 0x29B1);
}

#[test]
fn cobs_roundtrip() {
    let mut cases: Vec<Vec<u8>> = vec![vec![], vec![0], vec![0, 0], b"abc".to_vec(), (1..=254).collect(), (1..=255).collect()];
    for n in [253usize, 254, 255, 508] {
        cases.push(vec![1; n]);
    }
    cases.push([vec![0], vec![7; 254], vec![0]].concat());
    cases.push(vec![0; 300]);
    for c in cases {
        let e = cobs_encode(&c);
        assert!(!e.contains(&0));
        assert_eq!(cobs_decode(&e).unwrap(), c);
    }
    assert_eq!(cobs_encode(&[1u8; 254])[0], 0xFF);
}

#[test]
fn golden_frames() {
    for f in golden() {
        assert_eq!(encode_frame(f.typ, &f.body), f.frame, "{}", f.name);
        assert_eq!(FrameDecoder::new().feed(&f.frame), vec![(f.typ, f.body.clone())], "{}", f.name);
    }
}

#[test]
fn decode_messages() {
    let p = decode_pose(&g("pose").body).unwrap();
    assert_eq!((p.frame_id, p.processing_us, p.ntags, p.flags, p.nobs), (1234, 777, 2, 1, 5));
    assert_eq!(p.position, [1.5, -2.25, 0.5]);
    assert_eq!(p.timestamp_us, 0x0123_4567_89AB);
    let t = decode_time(&g("time").body).unwrap();
    assert_eq!((t.now_us, t.frame_us, t.tick_hz), (5_000_000_000, 4_999_000_000, 1_000_000));
    let s = decode_status(&g("status").body).unwrap();
    assert_eq!((s.frame_id, s.ntags, s.pose_valid, s.streaming, s.exposure, s.gain, s.ae_enabled), (4242, 3, true, true, 400, 0x20, true));
    assert_eq!(s.mean_brightness, 110.0);
    assert_eq!(s.fpga_seq(), 5);
    assert!(decode_pose(&[0u8; 44]).is_none());
}

#[test]
fn decoder_resilience() {
    let fr = g("pose").frame;
    let mut bad = fr.clone();
    bad[3] ^= 0x55;
    let mut d = FrameDecoder::new();
    let mut input = b"\x13\x37garbage\x00".to_vec();
    input.extend(&bad);
    input.extend([0, 0]);
    input.extend(&fr);
    input.extend(vec![1u8; 400]);
    input.push(0);
    input.extend(&fr[..5]);
    let mut out = d.feed(&input);
    out.extend(d.feed(&fr[5..]));
    assert_eq!(out.iter().map(|o| o.0).collect::<Vec<_>>(), vec![0x82, 0x82]);
    assert!(d.bad_frames >= 3);
}

// ---------------------------------------------------------------------------------------- fake device
struct Dev {
    clock: Rc<Cell<f64>>,
    t0: f64,
    offset_us: f64,
    skew: f64,
    lats: Vec<f64>,
    calls: usize,
    streaming: bool,
    dec: FrameDecoder,
}

impl Dev {
    fn dev_us(&self) -> u64 {
        (self.offset_us + (self.clock.get() - self.t0) * (1.0 + self.skew) * 1e6) as u64
    }

    fn pose_frame(&self) -> Vec<u8> {
        let mut b = Vec::new();
        b.extend(1u32.to_le_bytes());
        b.extend(500u32.to_le_bytes());
        b.extend([1u8, 4, 1, 0]);
        for v in [1f32, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.5] {
            b.extend(v.to_le_bytes());
        }
        b.extend(self.dev_us().to_le_bytes());
        encode_frame(RSP_POSE, &b)
    }

    fn handle(&mut self, data: &[u8]) -> Vec<u8> {
        let mut out = Vec::new();
        for (typ, body) in self.dec.feed(data) {
            let lat = self.lats[self.calls % self.lats.len()];
            self.calls += 1;
            self.clock.set(self.clock.get() + lat);
            let pre = if self.streaming { self.pose_frame() } else { vec![] };
            let rsp = match typ {
                CMD_GET_TIME => {
                    let mut b = self.dev_us().to_le_bytes().to_vec();
                    b.extend((self.dev_us() - 1000).to_le_bytes());
                    b.extend(1_000_000u32.to_le_bytes());
                    encode_frame(RSP_TIME, &b)
                }
                CMD_PING => encode_frame(RSP_PONG, &[body.clone(), vec![0, 0, 1, 0, 0x31, 0x47, 0x54, 0x41]].concat()),
                CMD_STREAM => {
                    self.streaming = body[0] == 1;
                    encode_frame(RSP_ACK, &[typ])
                }
                CMD_GET_POSE => encode_frame(RSP_NAK, &[typ, ERR_NO_POSE]),
                CMD_SET_SENSOR if body[0] == 0 && body[1] == 0 => encode_frame(RSP_NAK, &[typ, ERR_RANGE]),
                _ => encode_frame(RSP_ACK, &[typ]),
            };
            out.extend(pre);
            out.extend(rsp);
            self.clock.set(self.clock.get() + lat);
        }
        out
    }
}

type Cam = Camera<LoopbackTransport>;

fn make(offset_us: f64, skew: f64, lats: Vec<f64>) -> (Cam, Rc<RefCell<Dev>>, Rc<Cell<f64>>) {
    let clock = Rc::new(Cell::new(100.0));
    let dev = Rc::new(RefCell::new(Dev {
        clock: clock.clone(),
        t0: 100.0,
        offset_us,
        skew,
        lats,
        calls: 0,
        streaming: false,
        dec: FrameDecoder::new(),
    }));
    let d2 = dev.clone();
    let t = LoopbackTransport::with_handler(move |w| d2.borrow_mut().handle(w));
    let c2 = clock.clone();
    (Camera::with_clock(t, Box::new(move || c2.get())).unwrap(), dev, clock)
}

#[test]
fn ping_and_leading_zero() {
    let (mut cam, _d, _c) = make(0.0, 0.0, vec![0.001]);
    assert_eq!(cam.transport().written[0], vec![0u8]);
    let (ver, fid, _) = cam.ping().unwrap();
    assert_eq!((ver, fid), (0x10000, 0x41544731));
}

#[test]
fn nak_is_typed_error() {
    let (mut cam, _d, _c) = make(0.0, 0.0, vec![0.001]);
    match cam.get_pose() {
        Err(Error::Nak { cmd, code }) => assert_eq!((cmd, code), (CMD_GET_POSE, ERR_NO_POSE)),
        other => panic!("{other:?}"),
    }
    assert!(matches!(cam.set_sensor(0, 0x10), Err(Error::Nak { code: ERR_RANGE, .. })));
}

#[test]
fn interleaved_stream() {
    let (mut cam, dev, _c) = make(7e6, 0.0, vec![0.001]);
    cam.stream(true, 2).unwrap();
    cam.set_ae(true).unwrap();
    cam.set_track(24, 64, 10, 2).unwrap();
    cam.add_tag(&TagDef { id: 1, size: 0.1, position: [0.0; 3], quat_wxyz: [1.0, 0.0, 0.0, 0.0] }).unwrap();
    assert_eq!(cam.get_time().unwrap().tick_hz, 1_000_000);
    let mut n = 0;
    while let Some(p) = cam.poll_pose(Duration::ZERO).unwrap() {
        assert!(p.timestamp_us > 0);
        n += 1;
    }
    assert_eq!(n, 4);
    let f = dev.borrow().pose_frame();
    cam.transport().inject(&f);
    assert!(cam.poll_pose(Duration::from_millis(10)).unwrap().is_some());
}

#[test]
fn pose_iterator_disables_stream() {
    let (mut cam, dev, _c) = make(0.0, 0.0, vec![0.001]);
    let f = dev.borrow().pose_frame();
    cam.transport().inject(&f.repeat(3));
    {
        let mut it = cam.poses(1, Duration::from_millis(50)).unwrap();
        assert_eq!(it.by_ref().take(2).filter(|p| p.is_ok()).count(), 2);
    }
    assert!(!dev.borrow().streaming);
}

#[test]
fn timeout_and_retry() {
    let mut cam = Camera::new(LoopbackTransport::new()).unwrap();
    cam.timeout = Duration::from_millis(20);
    cam.retries = 1;
    assert!(matches!(cam.ping(), Err(Error::Timeout { .. })));
    assert_eq!(cam.transport().written.len(), 3);

    let drop_first = Rc::new(Cell::new(true));
    let t = LoopbackTransport::with_handler(move |_| {
        if drop_first.replace(false) {
            vec![]
        } else {
            encode_frame(RSP_PONG, b"ping\0\0\0\0\0\0\0\0")
        }
    });
    let mut cam = Camera::new(t).unwrap();
    cam.timeout = Duration::from_millis(20);
    assert!(cam.ping().is_ok());
}

#[test]
fn clock_sync_offset_and_skew() {
    let (mut cam, dev, clk) = make(7e6, 200e-6, vec![0.001, 0.0003, 0.002, 0.0003]);
    let mut cs = ClockSync::default();
    for _ in 0..40 {
        cs.sample(&mut cam, 1).unwrap();
        clk.set(clk.get() + 0.1);
    }
    assert!((cs.best_rtt().unwrap() - 0.0006).abs() < 1e-6);
    let want = (1.0 / (1.0 + 200e-6) - 1.0) * 1e6;
    assert!((cs.skew_ppm() - want).abs() < 5.0, "{} vs {}", cs.skew_ppm(), want);
    let dev_us = dev.borrow().dev_us();
    assert!((cs.to_host(dev_us, 1_000_000) - clk.get()).abs() < 50e-6);
    assert!((cs.to_device_us(clk.get(), 1_000_000) - dev_us as f64).abs() < 50.0);
    let mut nofit = ClockSync::new(64, false);
    nofit.sample(&mut cam, 8).unwrap();
    let dev_us = dev.borrow().dev_us();
    assert!((nofit.to_host(dev_us, 1_000_000) - clk.get()).abs() <= nofit.best_rtt().unwrap() / 2.0 + 1e-6);
}

#[test]
fn clock_sync_pose_timestamp() {
    let (mut cam, dev, clk) = make(123_456_789.0, 0.0, vec![0.001]);
    let mut cs = ClockSync::default();
    cs.sample(&mut cam, 8).unwrap();
    clk.set(clk.get() + 0.5);
    let f = dev.borrow().pose_frame();
    let (_, body) = FrameDecoder::new().feed(&f).remove(0);
    let p = decode_pose(&body).unwrap();
    assert!((cs.pose_host_time(&p) - clk.get()).abs() < 1e-5);
}

#[test]
fn synthetic_samples_with_jitter() {
    let mut cs = ClockSync::default();
    let mut seed = 12345u64;
    let skew = 1.0 - 50e-6;
    for i in 0..50 {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let rtt = 0.0004 + ((seed >> 33) as f64 / (1u64 << 31) as f64) * 0.004;
        let h = 10.0 + i as f64 * 0.05;
        let dev_s = 3.0 + (h - 10.0) / skew;
        cs.add_sample(h - rtt / 2.0, h + rtt / 2.0, (dev_s * 1e6).round() as u64, 1_000_000);
    }
    let t = cs.to_host(((3.0 + 5.0 / skew) * 1e6).round() as u64, 1_000_000);
    assert!((t - 15.0).abs() < 0.002);
}
