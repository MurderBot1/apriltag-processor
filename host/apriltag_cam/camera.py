"""High level camera API over a Transport."""
import json
import struct
import time
from collections import deque

from . import protocol as P
from .transport import Transport


class CameraError(Exception):
    pass


class CameraTimeout(CameraError, TimeoutError):
    pass


class NakError(CameraError):
    def __init__(self, cmd, code):
        self.cmd, self.code = cmd, code
        super().__init__('device NAK for command 0x%02X: error %d (%s)' % (cmd, code, P.ERR_NAMES.get(code, '?')))


DEFAULT_THRESH = dict(diff=24, abs_black=64, mindim=10, maxham=2)       # reset values of the FPGA threshold register


class Camera:
    def __init__(self, transport: Transport, timeout: float = 1.0, retries: int = 2):
        self.t = transport
        self.timeout = timeout
        self.retries = retries
        self.dec = P.FrameDecoder()
        self._poses = deque(maxlen=1024)
        self._tags = deque(maxlen=64)
        self._inbox = deque()
        self.frames_ignored = 0

    # ----------------------------------------------------------------------------- construction helpers
    @classmethod
    def open_serial(cls, port, **kw):
        from .transport import SerialTransport
        return cls(SerialTransport(port), **kw)

    @classmethod
    def open_sim(cls, frames=None, **kw):
        from .sim import SimTransport
        return cls(SimTransport(frames), **kw)

    def close(self):
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ----------------------------------------------------------------------------- framing
    def _pump(self, timeout):
        """Read once from the transport and route decoded frames.  Returns True if any bytes arrived."""
        data = self.t.read(4096, timeout)
        if not data:
            return False
        for typ, body in self.dec.feed(data):
            if typ == P.RSP_POSE:
                try:
                    self._poses.append(P.decode_pose(body))
                except ValueError:
                    self.frames_ignored += 1
                    continue
            self._inbox.append((typ, body))     # POSE frames are also visible to a pending GET_POSE request
        return True

    def _send(self, cmd, body=b''):
        self.t.write(P.encode_frame(cmd, body))

    def _request(self, cmd, body=b'', rsp=P.RSP_ACK, timeout=None, retries=None):
        """Send a command and wait for its ACK (or typed response).  A NAK for this command raises NakError; silence is
        retried (all commands are idempotent) and finally raises CameraTimeout."""
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        for attempt in range(retries + 1):
            self._inbox.clear()
            self._send(cmd, body)
            deadline = time.monotonic() + timeout
            while True:
                while self._inbox:
                    typ, b = self._inbox.popleft()
                    if typ == P.RSP_NAK and len(b) >= 2 and b[0] == cmd:
                        raise NakError(cmd, b[1])
                    if typ == rsp and (rsp != P.RSP_ACK or (len(b) >= 1 and b[0] == cmd)):
                        return b
                    if typ != P.RSP_POSE:
                        self.frames_ignored += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if not self._pump(min(remaining, 0.05)):
                    time.sleep(0.0005)
        raise CameraTimeout('no response to command 0x%02X after %d attempts' % (cmd, retries + 1))

    # ----------------------------------------------------------------------------- commands
    def ping(self, token: bytes = b'ping'):
        """Returns dict(firmware_version, fpga_id, rtt_s)."""
        t0 = time.monotonic()
        b = self._request(P.CMD_PING, token[:4].ljust(4, b'\0'), P.RSP_PONG)
        if len(b) != 12:
            raise CameraError('bad PONG length')
        ver, fid = struct.unpack_from('<II', b, 4)
        return dict(firmware_version=ver, fpga_id=fid, rtt_s=time.monotonic() - t0, echo=b[:4])

    def set_calibration(self, cal=None, **kw):
        """cal: dict like config/camera_calibration.json (fx fy cx cy dist[5]  or  K 3x3 + dist), or keyword arguments."""
        c = dict(cal or {})
        c.update(kw)
        if 'K' in c:
            K = c['K']
            c.setdefault('fx', K[0][0]); c.setdefault('fy', K[1][1]); c.setdefault('cx', K[0][2]); c.setdefault('cy', K[1][2])
        dist = list(c.get('dist', [c.get(k, 0.0) for k in ('k1', 'k2', 'p1', 'p2', 'k3')]))
        dist += [0.0] * (5 - len(dist))
        if len(dist) != 5:
            raise ValueError('dist must have <= 5 coefficients (k1 k2 p1 p2 k3)')
        self._request(P.CMD_SET_CALIB, P.encode_calib(c['fx'], c['fy'], c['cx'], c['cy'], *dist))

    def clear_field(self):
        self._request(P.CMD_CLEAR_MAP)

    def add_tag(self, tag_id, size, position, quat_wxyz):
        self._request(P.CMD_ADD_TAG, P.encode_tag(int(tag_id), size, position, quat_wxyz))

    def set_field(self, tag_map):
        """tag_map: dict like config/tag_map.json ({'tags': [{id,size,position,quat_wxyz}]}) or a list of such dicts."""
        tags = tag_map['tags'] if isinstance(tag_map, dict) else list(tag_map)
        ids = [int(t['id']) for t in tags]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate tag ids')
        if len(ids) > 64:
            raise ValueError('at most 64 tags are supported')
        self.clear_field()
        for t in tags:
            self.add_tag(t['id'], t['size'], t['position'], t['quat_wxyz'])
        return len(tags)

    def commit(self):
        """Persist calibration + field map to flash."""
        self._request(P.CMD_COMMIT, timeout=max(self.timeout, 3.0))

    def get_config(self):
        b = self._request(P.CMD_GET_CONFIG, rsp=P.RSP_CONFIG)
        if len(b) != 40:
            raise CameraError('bad CONFIG length')
        v = struct.unpack_from('<9f', b, 0)
        n = struct.unpack_from('<H', b, 36)[0]
        cal = dict(fx=v[0], fy=v[1], cx=v[2], cy=v[3], dist=list(v[4:9]))
        tags = []
        for i in range(n):
            tb = self._request(P.CMD_GET_TAG, struct.pack('<H', i), P.RSP_TAG)
            tid, _pad, size, x, y, z, qw, qx, qy, qz = struct.unpack('<HHf3f4f', tb)
            tags.append(dict(id=tid, size=size, position=[x, y, z], quat_wxyz=[qw, qx, qy, qz]))
        return dict(calibration=cal, tags=tags)

    def get_status(self):
        return P.decode_status(self._request(P.CMD_GET_STATUS, rsp=P.RSP_STATUS))

    def get_time(self):
        """Device clock: protocol.DeviceTime(now_us, frame_us, tick_hz)."""
        return P.decode_time(self._request(P.CMD_GET_TIME, rsp=P.RSP_TIME))

    def sync_clock(self, samples=16):
        """Estimate device->host monotonic offset.  Returns (offset_s, rtt_s): host_time = device_us / tick_hz + offset_s.
        Uses the minimum-round-trip sample (device time is taken somewhere inside the round trip, so the midpoint is exact to rtt/2)."""
        best = None
        for _ in range(samples):
            t0 = time.monotonic(); d = self.get_time(); t1 = time.monotonic()
            if best is None or t1 - t0 < best[0]:
                best = (t1 - t0, (t0 + t1) / 2 - d.now_us / d.tick_hz)
        return best[1], best[0]

    def get_pose(self):
        """Latest solved pose.  Raises NakError(code=ERR_NO_POSE) when no pose has been solved yet."""
        self._poses.clear()
        b = self._request(P.CMD_GET_POSE, rsp=P.RSP_POSE)
        return P.decode_pose(b)

    def get_raw_tags(self):
        """Tag observations of the last processed frame: list of dict(id, ham, corners[4][2])."""
        b = self._request(P.CMD_GET_TAGS_RAW, rsp=P.RSP_TAGS)
        frame, n = struct.unpack_from('<IB', b, 0)
        out, o = [], 5
        for _ in range(n):
            tid, ham = struct.unpack_from('<HB', b, o)
            c = struct.unpack_from('<8f', b, o + 3)
            out.append(dict(id=tid, ham=ham, corners=[[c[0], c[1]], [c[2], c[3]], [c[4], c[5]], [c[6], c[7]]]))
            o += 35
        return dict(frame_id=frame, tags=out)

    def set_exposure_gain(self, exposure, gain=0x10):
        """Manual sensor control (disables auto exposure).  exposure in sensor lines (1..800), gain register 0x10 = 1x."""
        self._request(P.CMD_SET_SENSOR, struct.pack('<HB', int(exposure), int(gain)))

    def set_ae(self, enable: bool):
        self._request(P.CMD_SET_AE, bytes([1 if enable else 0]))

    def set_tracking_params(self, diff=None, abs_black=None, mindim=None, maxham=None):
        """FPGA threshold register: local-contrast min, absolute black level, min tag dimension (px), max hamming distance."""
        d = DEFAULT_THRESH
        v = [d['diff'] if diff is None else diff, d['abs_black'] if abs_black is None else abs_black,
             d['mindim'] if mindim is None else mindim, d['maxham'] if maxham is None else maxham]
        if not all(0 <= x <= 255 for x in v) or v[3] > 63:
            raise ValueError('tracking parameter out of range')
        self._request(P.CMD_SET_TRACK, bytes(v))

    # ----------------------------------------------------------------------------- streaming
    def set_stream(self, enable, divider=1):
        self._request(P.CMD_STREAM, struct.pack('<BH', 1 if enable else 0, divider))

    def stream(self, divider=1, max_frames=None, timeout=1.0, on_timeout='raise'):
        """Generator of Pose objects.  Sends STREAM on, yields poses, sends STREAM off when closed.
        on_timeout='raise' raises CameraTimeout when no pose arrives for `timeout` seconds; 'stop' ends the generator."""
        self.set_stream(True, divider)
        self._poses.clear()
        n = 0
        try:
            while max_frames is None or n < max_frames:
                if not self._poses:
                    deadline = time.monotonic() + timeout
                    while not self._poses:
                        self._inbox.clear()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if on_timeout == 'stop':
                                return
                            raise CameraTimeout('no pose within %.2f s' % timeout)
                        if not self._pump(min(remaining, 0.05)):
                            time.sleep(0.0005)
                n += 1
                yield self._poses.popleft()
        finally:
            try:
                self.set_stream(False, 1)
            except (CameraError, OSError):
                pass


def load_json(path):
    with open(path) as f:
        return json.load(f)
