"""Device -> host clock mapping from GET_TIME round trips."""
from collections import deque


class ClockSync:
    """Collects (host midpoint, device time, rtt) samples. The device time `now_us` corresponds to the host midpoint of the
    request to within half the RTT, so the min-RTT sample gives the best offset. With fit=True and >= 3 low-RTT samples a
    linear fit also estimates the relative skew (device clock vs host clock)."""

    def __init__(self, max_samples=64, fit=True):
        self.samples = deque(maxlen=max_samples)     # (host_mid_s, dev_s, rtt_s)
        self.fit = fit
        self._model = None                           # (dev_ref_s, host_ref_s, slope)

    def add_sample(self, t0, t1, device_us, tick_hz=1_000_000):
        if t1 < t0:
            raise ValueError('t1 < t0')
        self.samples.append(((t0 + t1) / 2.0, device_us / float(tick_hz), t1 - t0))
        self._model = None

    def sample(self, camera, n=16):
        """Runs n GET_TIME round trips on `camera`; returns self."""
        for _ in range(n):
            t0, t1, ti = camera.get_time_sample()
            self.add_sample(t0, t1, ti.now_us, ti.tick_hz)
        return self

    @property
    def best_rtt(self):
        return min(s[2] for s in self.samples) if self.samples else None

    def _build(self):
        if self._model:
            return self._model
        if not self.samples:
            raise RuntimeError('no clock samples')
        best = min(self.samples, key=lambda s: s[2])
        model = (best[1], best[0], 1.0)
        if self.fit and len(self.samples) >= 3:
            lim = 2.0 * best[2] + 1e-9
            use = [s for s in self.samples if s[2] <= lim]
            if len(use) >= 3:
                xm = sum(s[1] for s in use) / len(use)
                ym = sum(s[0] for s in use) / len(use)
                sxx = sum((s[1] - xm) ** 2 for s in use)
                if sxx > 0:
                    model = (xm, ym, sum((s[1] - xm) * (s[0] - ym) for s in use) / sxx)
        self._model = model
        return model

    @property
    def offset_s(self):
        """host - device seconds at the reference sample."""
        d, h, _ = self._build()
        return h - d

    @property
    def skew_ppm(self):
        """Host seconds per device second, minus one, in ppm (positive: device clock runs slow)."""
        return (self._build()[2] - 1.0) * 1e6

    def to_host(self, device_us, tick_hz=1_000_000):
        """Device timestamp (ticks) -> host seconds in the Camera clock domain (time.monotonic by default)."""
        d, h, k = self._build()
        return h + (device_us / float(tick_hz) - d) * k

    def to_device_us(self, host_s, tick_hz=1_000_000):
        d, h, k = self._build()
        return (d + (host_s - h) / k) * tick_hz

    def pose_host_time(self, pose, tick_hz=1_000_000):
        return self.to_host(pose.timestamp_us, tick_hz)
