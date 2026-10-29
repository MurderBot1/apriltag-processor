"""High level camera API over a Transport."""
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


class Camera:
    def __init__(self, transport: Transport, timeout=1.0, retries=2, clock=time.monotonic):
        self.t = transport
        self.timeout = timeout
        self.retries = retries
        self.clock = clock
        self.dec = P.FrameDecoder()
        self._poses = deque(maxlen=1024)
        self._inbox = deque()
        self.frames_ignored = 0
        self.t.write(b'\x00')               # resynchronise the device's frame parser

    @classmethod
    def open_serial(cls, port, **kw):
        from .transport import SerialTransport
        return cls(SerialTransport(port), **kw)

    def close(self):
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ------------------------------------------------------------------------------------ framing
    def _pump(self, timeout):
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
            self._inbox.append((typ, body))
        return True

    def _request(self, cmd, body=b'', rsp=P.RSP_ACK, timeout=None, retries=None):
        """Send and wait for the matching response; POSE frames received meanwhile are queued. NAK -> NakError,
        silence is retried (commands are idempotent) then CameraTimeout."""
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        for _ in range(retries + 1):
            self._inbox.clear()
            self.t.write(P.encode_frame(cmd, body))
            deadline = self.clock() + timeout
            while True:
                while self._inbox:
                    typ, b = self._inbox.popleft()
                    if typ == P.RSP_NAK and len(b) >= 2 and b[0] == cmd:
                        raise NakError(cmd, b[1])
                    if typ == rsp and (rsp != P.RSP_ACK or (len(b) >= 1 and b[0] == cmd)):
                        return b
                    if typ != P.RSP_POSE:
                        self.frames_ignored += 1
                remaining = deadline - self.clock()
                if remaining <= 0:
                    break
                self._pump(min(remaining, 0.05))
        raise CameraTimeout('no response to command 0x%02X after %d attempts' % (cmd, retries + 1))

    # ------------------------------------------------------------------------------------ commands
    def ping(self, token=b'ping'):
        """Returns dict(firmware_version, fpga_id, rtt_s, echo)."""
        t0 = self.clock()
        b = self._request(P.CMD_PING, bytes(token[:4]).ljust(4, b'\0'), P.RSP_PONG)
        if len(b) != 12:
            raise CameraError('bad PONG length')
        ver, fid = struct.unpack_from('<II', b, 4)
        return dict(firmware_version=ver, fpga_id=fid, rtt_s=self.clock() - t0, echo=b[:4])

    def set_calibration(self, fx, fy, cx, cy, k1=0.0, k2=0.0, p1=0.0, p2=0.0, k3=0.0):
        self._request(P.CMD_SET_CALIB, P.encode_calib(fx, fy, cx, cy, k1, k2, p1, p2, k3))

    def clear_map(self):
        self._request(P.CMD_CLEAR_MAP)

    def add_tag(self, tag_id, size, position, quat_wxyz):
        self._request(P.CMD_ADD_TAG, P.encode_tag(int(tag_id), size, position, quat_wxyz))

    def commit(self):
        self._request(P.CMD_COMMIT, timeout=max(self.timeout, 3.0))

    def get_config(self):
        """dict(calibration=dict(fx, fy, cx, cy, dist=[k1,k2,p1,p2,k3]), tags=[dict(id,size,position,quat_wxyz)])."""
        b = self._request(P.CMD_GET_CONFIG, rsp=P.RSP_CONFIG)
        if len(b) != P.CONFIG_LEN:
            raise CameraError('bad CONFIG length')
        v = struct.unpack_from('<9f', b, 0)
        n = struct.unpack_from('<H', b, 36)[0]
        cal = dict(fx=v[0], fy=v[1], cx=v[2], cy=v[3], dist=list(v[4:9]))
        return dict(calibration=cal, tags=[self.get_tag(i) for i in range(n)])

    def get_tag(self, index):
        tb = self._request(P.CMD_GET_TAG, struct.pack('<H', index), P.RSP_TAG)
        if len(tb) != P.TAG_LEN:
            raise CameraError('bad TAG length')
        tid, _pad, size, x, y, z, qw, qx, qy, qz = struct.unpack('<HHf3f4f', tb)
        return dict(id=tid, size=size, position=[x, y, z], quat_wxyz=[qw, qx, qy, qz])

    def stream(self, enable, divider=1):
        self._request(P.CMD_STREAM, struct.pack('<BH', 1 if enable else 0, divider))

    def set_sensor(self, exposure, gain=0x10):
        """Manual exposure (lines, 1..800) and gain register (0x10 = 1x); disables auto exposure."""
        self._request(P.CMD_SET_SENSOR, struct.pack('<HB', int(exposure), int(gain)))

    def set_ae(self, enable):
        self._request(P.CMD_SET_AE, bytes([1 if enable else 0]))

    def set_track(self, diff=24, abs_black=64, mindim=10, maxham=2):
        v = [diff, abs_black, mindim, maxham]
        if not all(0 <= x <= 255 for x in v) or maxham > 63:
            raise ValueError('tracking parameter out of range')
        self._request(P.CMD_SET_TRACK, bytes(v))

    def get_status(self):
        return P.decode_status(self._request(P.CMD_GET_STATUS, rsp=P.RSP_STATUS))

    def get_pose(self):
        """Latest solved pose; NakError(code=ERR_NO_POSE) if none yet."""
        return P.decode_pose(self._request(P.CMD_GET_POSE, rsp=P.RSP_POSE))

    def get_tags_raw(self):
        b = self._request(P.CMD_GET_TAGS_RAW, rsp=P.RSP_TAGS)
        frame, n = struct.unpack_from('<IB', b, 0)
        out, o = [], 5
        for _ in range(n):
            tid, ham = struct.unpack_from('<HB', b, o)
            c = struct.unpack_from('<8f', b, o + 3)
            out.append(dict(id=tid, ham=ham, corners=[[c[0], c[1]], [c[2], c[3]], [c[4], c[5]], [c[6], c[7]]]))
            o += 35
        return dict(frame_id=frame, tags=out)

    def get_time_sample(self):
        """Returns (t0, t1, TimeInfo) with t0/t1 the host clock before send and after receive (no retries, to keep RTT honest)."""
        t0 = self.clock()
        b = self._request(P.CMD_GET_TIME, rsp=P.RSP_TIME, retries=0)
        t1 = self.clock()
        return t0, t1, P.decode_time(b)

    def get_time(self):
        """TimeInfo(now_us, frame_us, tick_hz)."""
        return self.get_time_sample()[2]

    # ------------------------------------------------------------------------------------ poses
    def poll_pose(self, timeout=0.0):
        """Next queued streamed Pose (waiting up to `timeout` s), or None."""
        deadline = self.clock() + timeout
        while True:
            if self._poses:
                return self._poses.popleft()
            self._inbox.clear()
            remaining = deadline - self.clock()
            if remaining <= 0:
                return self._poses.popleft() if self._pump(0) and self._poses else None
            self._pump(min(remaining, 0.05))

    def poses(self, divider=1, max_frames=None, timeout=1.0):
        """Generator: enables streaming, yields Poses, disables streaming on close. Raises CameraTimeout on silence."""
        self.stream(True, divider)
        n = 0
        try:
            while max_frames is None or n < max_frames:
                p = self.poll_pose(timeout)
                if p is None:
                    raise CameraTimeout('no pose within %.2f s' % timeout)
                n += 1
                yield p
        finally:
            try:
                self.stream(False, 1)
            except (CameraError, OSError):
                pass

    def on_pose(self, callback, divider=1, timeout=1.0):
        """Callback style: calls callback(pose) until it returns False."""
        for p in self.poses(divider, timeout=timeout):
            if callback(p) is False:
                break
