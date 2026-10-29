"""Shared helpers for the firmware / host tests (not a test module)."""
import json
import math
import os
import random
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'host'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from apriltag_cam import protocol as P      # noqa: E402
from apriltag_cam import simfw              # noqa: E402


def load_json(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return json.load(f)


def cal_body(cal=None):
    cal = cal or load_json('config/camera_calibration.json')
    return P.encode_calib(cal['fx'], cal['fy'], cal['cx'], cal['cy'], *cal['dist'])


def tag_body(t):
    return P.encode_tag(t['id'], t['size'], t['position'], t['quat_wxyz'])


def rand_tags(rng, n, id_pool=None):
    ids = rng.sample(id_pool or range(0, 587), n)
    out = []
    for i in ids:
        q = [rng.uniform(-1, 1) for _ in range(4)]
        nq = math.sqrt(sum(x * x for x in q))
        out.append(dict(id=i, size=rng.uniform(0.05, 0.3), position=[rng.uniform(-5, 5) for _ in range(3)],
                        quat_wxyz=[x / nq for x in q]))
    return out


def rand_cal(rng):
    return dict(fx=rng.uniform(400, 900), fy=rng.uniform(400, 900), cx=rng.uniform(600, 680), cy=rng.uniform(380, 420),
                dist=[rng.uniform(-.3, .3), rng.uniform(-.1, .1), rng.uniform(-.01, .01), rng.uniform(-.01, .01), rng.uniform(-.05, .05)])


class Dev:
    """A firmware instance driven through the byte protocol."""
    def __init__(self, fw=None, **kw):
        self.fw = fw or simfw.NativeFirmware(**kw)
        self.dec = P.FrameDecoder()

    @property
    def fpga(self):
        return self.fw.fpga

    @property
    def flash(self):
        return self.fw.flash

    def send(self, typ, body=b''):
        """Send one command frame, return all frames the device answered with (list of (type, body))."""
        self.fw.rx(P.encode_frame(typ, body))
        return self.dec.feed(self.fw.take_tx())

    def drain(self):
        return self.dec.feed(self.fw.take_tx())

    def ok(self, typ, body=b''):
        r = self.send(typ, body)
        assert r == [(P.RSP_ACK, bytes([typ]))], r
        return r

    def nak(self, typ, body=b''):
        r = self.send(typ, body)
        assert len(r) == 1 and r[0][0] == P.RSP_NAK and r[0][1][0] == typ, r
        return r[0][1][1]

    def rsp(self, typ, body, rtype):
        r = self.send(typ, body)
        assert len(r) == 1 and r[0][0] == rtype, r
        return r[0][1]

    def set_config(self, cal, tags, commit=False):
        self.ok(P.CMD_SET_CALIB, cal_body(cal))
        self.ok(P.CMD_CLEAR_MAP)
        for t in tags:
            self.ok(P.CMD_ADD_TAG, tag_body(t))
        if commit:
            self.ok(P.CMD_COMMIT)

    def dump(self):
        """Canonical copy of the configuration held in RAM: (config bytes, [tag bytes])."""
        cfg = self.rsp(P.CMD_GET_CONFIG, b'', P.RSP_CONFIG)
        n = struct.unpack_from('<H', cfg, 36)[0]
        return cfg, [self.rsp(P.CMD_GET_TAG, struct.pack('<H', i), P.RSP_TAG) for i in range(n)]

    def reboot(self):
        self.fw.boot()
        self.dec = P.FrameDecoder()


def close_dump(a, b, tol=2e-6):
    """Compare two dump() results allowing float rounding."""
    if len(a[1]) != len(b[1]):
        return False
    fa = struct.unpack_from('<9f', a[0]); fb = struct.unpack_from('<9f', b[0])
    if any(abs(x - y) > tol * max(1, abs(x)) for x, y in zip(fa, fb)):
        return False
    for ta, tb in zip(a[1], b[1]):
        va = struct.unpack('<HHf3f4f', ta); vb = struct.unpack('<HHf3f4f', tb)
        if va[0] != vb[0]:
            return False
        qa, qb = va[6:], vb[6:]
        if sum(x * y for x, y in zip(qa, qb)) < 0:
            qb = tuple(-x for x in qb)
        if any(abs(x - y) > 1e-5 for x, y in zip(va[2:6] + qa, vb[2:6] + qb)):
            return False
    return True


def stored_slot(raw):
    """Python reference parser of the flash slot format (see atapp.c): returns (seq, payload bytes) or None if invalid."""
    if len(raw) < 50 or struct.unpack_from('<I', raw, 0)[0] != 0x31465441:
        return None
    nt = struct.unpack_from('<H', raw, 8)[0]
    size = 12 + 36 + 36 * nt + 2
    if nt > 64 or size > len(raw):
        return None
    if P.crc16(bytes(raw[:size - 2])) != struct.unpack_from('<H', raw, size - 2)[0]:
        return None
    return struct.unpack_from('<I', raw, 4)[0], bytes(raw[:size])


def pack_slot(seq, cal_vals, tags, magic=0x31465441, ntags_field=None, fix_crc=True):
    """tags: list of (id, size, pos, quat).  Builds a slot image (padded with 0xFF to 4096)."""
    b = struct.pack('<IIHH', magic, seq, len(tags) if ntags_field is None else ntags_field, 0)
    b += struct.pack('<9f', *cal_vals)
    for tid, size, pos, q in tags:
        b += struct.pack('<HHf3f4f', tid, 0, size, *pos, *q)
    b += struct.pack('<H', P.crc16(b) if fix_crc else 0x1234)
    return b + b'\xff' * (simfw.SLOT_BYTES - len(b))
