"""Byte-level protocol: COBS + CRC16 framing and message encode/decode.  Mirrors firmware/core/atproto.[ch]; see docs/protocol.md."""
import struct
from dataclasses import dataclass

MAX_BODY = 256
MAX_FRAME = MAX_BODY + 8

# host -> device
CMD_PING, CMD_SET_CALIB, CMD_CLEAR_MAP, CMD_ADD_TAG, CMD_COMMIT = 0x01, 0x02, 0x03, 0x04, 0x05
CMD_GET_CONFIG, CMD_STREAM, CMD_SET_SENSOR, CMD_GET_STATUS, CMD_SET_TRACK = 0x06, 0x07, 0x08, 0x09, 0x0A
CMD_GET_POSE, CMD_GET_TAG, CMD_GET_TAGS_RAW, CMD_SET_AE, CMD_GET_TIME = 0x0B, 0x0C, 0x0D, 0x0E, 0x0F
CMD_SET_AUTO_RATIO = 0x10
# device -> host
RSP_ACK, RSP_PONG, RSP_POSE, RSP_TAGS, RSP_CONFIG, RSP_TAG, RSP_STATUS, RSP_TIME, RSP_NAK = 0x80, 0x81, 0x82, 0x83, 0x86, 0x87, 0x89, 0x8A, 0xFF
ERR_BAD_LEN, ERR_FULL, ERR_FLASH, ERR_UNKNOWN, ERR_NO_POSE, ERR_RANGE = 1, 2, 3, 4, 5, 6
ERR_NAMES = {1: 'BAD_LEN', 2: 'FULL', 3: 'FLASH', 4: 'UNKNOWN', 5: 'NO_POSE', 6: 'RANGE'}


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout)."""
    c = 0xFFFF
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def cobs_encode(raw: bytes) -> bytes:
    out = bytearray([0]); code_pos = 0; code = 1
    for b in raw:
        if b == 0:
            out[code_pos] = code; code_pos = len(out); out.append(0); code = 1
        else:
            out.append(b); code += 1
            if code == 0xFF:
                out[code_pos] = code; code_pos = len(out); out.append(0); code = 1
    out[code_pos] = code
    return bytes(out)


def cobs_decode(enc: bytes) -> bytes:
    """Same (lenient on trailing-code) semantics as the firmware decoder; raises ValueError on malformed input."""
    out = bytearray(); i = 0; n = len(enc)
    while i < n:
        code = enc[i]; i += 1
        if code == 0:
            raise ValueError('zero in COBS data')
        for _ in range(code - 1):
            if i >= n:
                raise ValueError('truncated COBS block')
            out.append(enc[i]); i += 1
        if code != 0xFF and i < n:
            out.append(0)
    return bytes(out)


def encode_frame(msg_type: int, body: bytes = b'') -> bytes:
    if len(body) > MAX_BODY:
        raise ValueError('body too large')
    raw = bytes([msg_type]) + bytes(body)
    raw += struct.pack('<H', crc16(raw))
    return cobs_encode(raw) + b'\x00'


class FrameDecoder:
    """Incremental decoder.  feed(bytes) -> list of (type, body).  Garbage, bad CRC and oversized frames are dropped and counted;
    a 0x00 always resynchronises."""
    def __init__(self):
        self.buf = bytearray(); self.overflow = False; self.bad_frames = 0; self.good_frames = 0

    def feed(self, data: bytes):
        out = []
        for b in data:
            if b != 0:
                if len(self.buf) < MAX_FRAME:
                    self.buf.append(b)
                else:
                    self.overflow = True
                continue
            enc, ovf = bytes(self.buf), self.overflow
            self.buf.clear(); self.overflow = False
            if not enc:
                continue
            try:
                if ovf:
                    raise ValueError('overflow')
                dec = cobs_decode(enc)
                if len(dec) < 3 or crc16(dec[:-2]) != struct.unpack('<H', dec[-2:])[0]:
                    raise ValueError('crc')
            except ValueError:
                self.bad_frames += 1
                continue
            self.good_frames += 1
            out.append((dec[0], dec[1:-2]))
        return out


# ------------------------------------------------------------------ message bodies
@dataclass
class Pose:
    frame_id: int
    position: tuple          # x, y, z (m), camera -> world
    quaternion: tuple        # w, x, y, z
    rms_px: float
    ntags: int
    flags: int
    processing_us: int
    nobs: int = 0
    timestamp_us: int = 0    # device clock at the start of the source frame

    FLAG_AMBIGUOUS = 1
    FLAG_OUTLIER_DROPPED = 2
    FLAG_SINGLE_TAG = 4

    def rotation_matrix(self):
        w, x, y, z = self.quaternion
        n = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
        w, x, y, z = w / n, x / n, y / n, z / n
        return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


POSE_LEN = 52


def decode_pose(body: bytes) -> Pose:
    if len(body) != POSE_LEN:
        raise ValueError('bad POSE length %d' % len(body))
    fid, us, nt, fl, nobs = struct.unpack_from('<IIBBH', body, 0)
    f = struct.unpack_from('<8f', body, 12)
    ts, = struct.unpack_from('<Q', body, 44)
    return Pose(fid, tuple(f[0:3]), tuple(f[3:7]), f[7], nt, fl, us, nobs, ts)


@dataclass
class Status:
    fpga_status: int
    ccl: int
    frames_dropped: int
    frames_total: int
    frames_processed: int
    solved: int
    solve_fail: int
    torn_reads: int
    frame_id: int
    ntags: int
    pose_valid: bool
    streaming: bool
    exposure: int = 0
    gain: int = 0
    ae_enabled: bool = False
    mean_brightness: float = 0.0
    ratio: int = 0                # contrast-ratio field currently in the FPGA THRESH register
    auto_ratio: bool = False      # automatic ratio selection active

    @property
    def init_done(self): return bool(self.fpga_status >> 3 & 1)
    @property
    def tpu_busy(self): return bool(self.fpga_status >> 2 & 1)
    @property
    def res_valid(self): return bool(self.fpga_status & 1)
    @property
    def fpga_seq(self): return self.fpga_status >> 16


STATUS_LEN = 48


def decode_status(body: bytes) -> Status:
    if len(body) != STATUS_LEN:
        raise ValueError('bad STATUS length %d' % len(body))
    w = struct.unpack_from('<9IHBB', body, 0)
    exp, gain, ae, meanq = struct.unpack_from('<HBBH', body, 40)
    rflags = body[46]
    return Status(*w[:9], w[9], bool(w[10]), bool(w[11]), exp, gain, bool(ae), meanq / 256.0, rflags & 3, bool(rflags & 4))


def encode_calib(fx, fy, cx, cy, k1=0.0, k2=0.0, p1=0.0, p2=0.0, k3=0.0) -> bytes:
    return struct.pack('<9f', fx, fy, cx, cy, k1, k2, p1, p2, k3)


def encode_tag(tag_id, size, pos, quat_wxyz) -> bytes:
    return struct.pack('<Hf3f4f', tag_id, size, *pos, *quat_wxyz)


@dataclass
class DeviceTime:
    now_us: int          # device clock when the MCU served the request
    frame_us: int        # capture timestamp of the newest processed frame
    tick_hz: int


TIME_LEN = 20


def decode_time(body: bytes) -> DeviceTime:
    if len(body) != TIME_LEN:
        raise ValueError('bad TIME length %d' % len(body))
    now, frame, hz = struct.unpack('<QQI', body)
    return DeviceTime(now, frame, hz)
