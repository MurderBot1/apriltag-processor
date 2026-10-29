//! Device -> host clock mapping from GET_TIME round trips.
use crate::camera::{Camera, Error};
use crate::protocol::Pose;
use crate::transport::Transport;
use std::collections::VecDeque;

#[derive(Clone, Copy)]
struct Sample {
    host_mid: f64,
    dev_s: f64,
    rtt: f64,
}

/// Keeps (host midpoint, device time, rtt) samples. The min-RTT sample gives the offset (error <= rtt/2); with `fit`
/// and >= 3 low-RTT samples a linear fit also estimates the relative skew.
pub struct ClockSync {
    samples: VecDeque<Sample>,
    max_samples: usize,
    pub fit: bool,
    model: Option<(f64, f64, f64)>, // (dev_ref_s, host_ref_s, slope host-seconds per device-second)
}

impl Default for ClockSync {
    fn default() -> Self {
        Self::new(64, true)
    }
}

impl ClockSync {
    pub fn new(max_samples: usize, fit: bool) -> Self {
        Self { samples: VecDeque::new(), max_samples, fit, model: None }
    }

    pub fn len(&self) -> usize {
        self.samples.len()
    }

    pub fn is_empty(&self) -> bool {
        self.samples.is_empty()
    }

    /// t0/t1: host clock (seconds) before send and after receive of a GET_TIME exchange.
    pub fn add_sample(&mut self, t0: f64, t1: f64, device_us: u64, tick_hz: u32) {
        assert!(t1 >= t0, "t1 < t0");
        if self.samples.len() == self.max_samples {
            self.samples.pop_front();
        }
        self.samples.push_back(Sample { host_mid: (t0 + t1) / 2.0, dev_s: device_us as f64 / tick_hz as f64, rtt: t1 - t0 });
        self.model = None;
    }

    /// Runs `n` GET_TIME round trips.
    pub fn sample<T: Transport>(&mut self, cam: &mut Camera<T>, n: usize) -> Result<(), Error> {
        for _ in 0..n {
            let (t0, t1, ti) = cam.get_time_sample()?;
            self.add_sample(t0, t1, ti.now_us, ti.tick_hz);
        }
        Ok(())
    }

    pub fn best_rtt(&self) -> Option<f64> {
        self.samples.iter().map(|s| s.rtt).fold(None, |a, r| Some(a.map_or(r, |x: f64| x.min(r))))
    }

    fn build(&mut self) -> (f64, f64, f64) {
        if let Some(m) = self.model {
            return m;
        }
        let best = *self.samples.iter().min_by(|a, b| a.rtt.partial_cmp(&b.rtt).unwrap()).expect("no clock samples");
        let mut m = (best.dev_s, best.host_mid, 1.0);
        if self.fit && self.samples.len() >= 3 {
            let lim = 2.0 * best.rtt + 1e-9;
            let used: Vec<&Sample> = self.samples.iter().filter(|s| s.rtt <= lim).collect();
            if used.len() >= 3 {
                let n = used.len() as f64;
                let xm = used.iter().map(|s| s.dev_s).sum::<f64>() / n;
                let ym = used.iter().map(|s| s.host_mid).sum::<f64>() / n;
                let sxx: f64 = used.iter().map(|s| (s.dev_s - xm).powi(2)).sum();
                if sxx > 0.0 {
                    let sxy: f64 = used.iter().map(|s| (s.dev_s - xm) * (s.host_mid - ym)).sum();
                    m = (xm, ym, sxy / sxx);
                }
            }
        }
        self.model = Some(m);
        m
    }

    /// host - device seconds at the reference sample.
    pub fn offset_s(&mut self) -> f64 {
        let (d, h, _) = self.build();
        h - d
    }

    /// Host seconds per device second minus one, in ppm.
    pub fn skew_ppm(&mut self) -> f64 {
        (self.build().2 - 1.0) * 1e6
    }

    /// Device ticks -> host seconds (the Camera clock domain).
    pub fn to_host(&mut self, device_us: u64, tick_hz: u32) -> f64 {
        let (d, h, k) = self.build();
        h + (device_us as f64 / tick_hz as f64 - d) * k
    }

    pub fn to_device_us(&mut self, host_s: f64, tick_hz: u32) -> f64 {
        let (d, h, k) = self.build();
        (d + (host_s - h) / k) * tick_hz as f64
    }

    pub fn pose_host_time(&mut self, pose: &Pose) -> f64 {
        self.to_host(pose.timestamp_us, 1_000_000)
    }
}
