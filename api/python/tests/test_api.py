import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from apriltag_camera import (Camera, ClockSync, FrameDecoder, LoopbackTransport, NakError, CameraTimeout, cobs_decode,
                             cobs_encode, crc16, decode_pose, decode_status, decode_time, encode_frame)
from apriltag_camera import protocol as P

GOLDEN = os.path.join(os.path.dirname(__file__), '..', '..', 'testdata', 'golden_frames.json')


def golden():
    with open(GOLDEN) as f:
        return json.load(f)


class VClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeDevice:
    """Protocol-level fake. Device clock = offset + elapsed * (1 + skew); every exchange costs `lat` each way."""

    def __init__(self, clock, offset_us=7_000_000, skew=0.0, lats=(0.001,)):
        self.clock, self.offset_us, self.skew, self.lats = clock, offset_us, skew, lats
        self.t0 = clock()
        self.dec = FrameDecoder()
        self.streaming = False
        self.have_pose = False
        self.calls = 0
        self.seen = []

    def dev_us(self):
        return int(self.offset_us + (self.clock() - self.t0) * (1 + self.skew) * 1e6)

    def pose_frame(self):
        body = struct.pack('<IIBBH', 1, 500, 1, 4, 1) + struct.pack('<8f', 1, 2, 3, 1, 0, 0, 0, .5) + struct.pack('<Q', self.dev_us())
        return encode_frame(P.RSP_POSE, body)

    def handle(self, data):
        out = b''
        for typ, body in self.dec.feed(data):
            self.seen.append(typ)
            lat = self.lats[self.calls % len(self.lats)]
            self.calls += 1
            self.clock.t += lat
            pre = self.pose_frame() if self.streaming else b''
            if typ == P.CMD_GET_TIME:
                rsp = encode_frame(P.RSP_TIME, struct.pack('<QQI', self.dev_us(), self.dev_us() - 1000, 1_000_000))
            elif typ == P.CMD_PING:
                rsp = encode_frame(P.RSP_PONG, body + struct.pack('<II', 0x10000, 0x41544731))
            elif typ == P.CMD_STREAM:
                self.streaming = body[0] == 1
                rsp = encode_frame(P.RSP_ACK, bytes([typ]))
            elif typ == P.CMD_GET_POSE:
                rsp = self.pose_frame() if self.have_pose else encode_frame(P.RSP_NAK, bytes([typ, P.ERR_NO_POSE]))
            elif typ == P.CMD_SET_SENSOR and struct.unpack('<H', body[:2])[0] == 0:
                rsp = encode_frame(P.RSP_NAK, bytes([typ, P.ERR_RANGE]))
            else:
                rsp = encode_frame(P.RSP_ACK, bytes([typ]))
            out += pre + rsp
            self.clock.t += lat
        return out


class Protocol(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(crc16(b'123456789'), 0x29B1)

    def test_cobs_roundtrip(self):
        cases = [b'', b'\x00', b'\x00\x00', b'abc', bytes(range(1, 255)), bytes(range(1, 256)), bytes([1] * 253),
                 bytes([1] * 254), bytes([1] * 255), bytes([1] * 508), b'\x00' + bytes([7] * 254) + b'\x00', bytes(300)]
        for c in cases:
            e = cobs_encode(c)
            self.assertNotIn(0, e)
            self.assertEqual(cobs_decode(e), c)
        self.assertEqual(cobs_encode(bytes([1] * 254))[0], 0xFF)

    def test_golden(self):
        g = golden()
        self.assertEqual(crc16(g['crc16_check']['input'].encode()), g['crc16_check']['value'])
        for f in g['frames']:
            body, frame = bytes.fromhex(f['body']), bytes.fromhex(f['frame'])
            self.assertEqual(encode_frame(f['type'], body), frame, f['name'])
            self.assertEqual(FrameDecoder().feed(frame), [(f['type'], body)], f['name'])

    def test_decode_messages(self):
        by = {f['name']: f for f in golden()['frames']}
        typ, body = FrameDecoder().feed(bytes.fromhex(by['pose']['frame']))[0]
        p = decode_pose(body)
        self.assertEqual((typ, p.frame_id, p.processing_us, p.ntags, p.flags, p.nobs), (0x82, 1234, 777, 2, 1, 5))
        self.assertEqual(p.position, (1.5, -2.25, 0.5))
        self.assertEqual(p.timestamp_us, 0x0123456789AB)
        t = decode_time(bytes.fromhex(by['time']['body']))
        self.assertEqual((t.now_us, t.frame_us, t.tick_hz), (5_000_000_000, 4_999_000_000, 1_000_000))
        s = decode_status(bytes.fromhex(by['status']['body']))
        self.assertEqual((s.frame_id, s.ntags, s.pose_valid, s.streaming, s.exposure, s.gain, s.ae_enabled),
                         (4242, 3, True, True, 400, 0x20, True))
        self.assertEqual(s.mean_brightness, 110.0)
        self.assertEqual(s.fpga_seq, 5)
        with self.assertRaises(ValueError):
            decode_pose(b'\0' * 44)

    def test_decoder_resilience(self):
        fr = bytes.fromhex(next(f['frame'] for f in golden()['frames'] if f['name'] == 'pose'))
        bad = bytearray(fr)
        bad[3] ^= 0x55
        d = FrameDecoder()
        out = d.feed(b'\x13\x37garbage' + b'\x00' + bytes(bad) + b'\x00\x00' + fr + b'\x01' * 400 + b'\x00' + fr[:5])
        out += d.feed(fr[5:])
        self.assertEqual([o[0] for o in out], [0x82, 0x82])
        self.assertGreaterEqual(d.bad_frames, 3)


class CameraTests(unittest.TestCase):
    def make(self, **kw):
        clk = VClock()
        dev = FakeDevice(clk, **kw)
        t = LoopbackTransport(dev.handle)
        return Camera(t, clock=clk), dev, t, clk

    def test_sends_leading_zero_and_ping(self):
        cam, dev, t, _ = self.make()
        self.assertEqual(t.written[0], b'\x00')
        r = cam.ping(b'abcd')
        self.assertEqual((r['echo'], r['firmware_version'], r['fpga_id']), (b'abcd', 0x10000, 0x41544731))

    def test_nak(self):
        cam, dev, *_ = self.make()
        with self.assertRaises(NakError) as e:
            cam.get_pose()
        self.assertEqual(e.exception.code, P.ERR_NO_POSE)
        with self.assertRaises(NakError) as e:
            cam.set_sensor(0)
        self.assertEqual(e.exception.code, P.ERR_RANGE)

    def test_interleaved_stream(self):
        cam, dev, t, _ = self.make()
        cam.stream(True, 2)
        cam.set_ae(True)
        cam.set_track()
        cam.add_tag(1, 0.1, (0, 0, 0), (1, 0, 0, 0))
        self.assertEqual(cam.get_time().tick_hz, 1_000_000)
        poses = []
        while True:
            p = cam.poll_pose()
            if p is None:
                break
            poses.append(p)
        self.assertEqual(len(poses), 4)                       # one POSE ahead of each response while streaming
        self.assertTrue(all(p.timestamp_us > 0 for p in poses))
        t.inject(dev.pose_frame())
        self.assertIsNotNone(cam.poll_pose(0.01))

    def test_pose_iterator(self):
        cam, dev, t, _ = self.make()
        got = list(cam.poses(max_frames=0))
        self.assertEqual(got, [])
        self.assertFalse(dev.streaming)                       # stream disabled again
        gen = cam.poses(max_frames=2)
        t.inject(dev.pose_frame() * 3)
        self.assertEqual(len(list(gen)), 2)

    def test_timeout_and_retry(self):
        t = LoopbackTransport()
        cam = Camera(t, timeout=0.02, retries=1)
        with self.assertRaises(CameraTimeout):
            cam.ping()
        self.assertEqual(len(t.written), 3)                   # leading zero + 2 attempts
        drops = [True]

        def h(data):
            if drops and drops.pop():
                return b''
            return encode_frame(P.RSP_PONG, b'ping' + bytes(8))
        cam = Camera(LoopbackTransport(h), timeout=0.02, retries=2)
        self.assertEqual(cam.ping()['echo'], b'ping')

    def test_clock_sync_offset_and_skew(self):
        cam, dev, t, clk = self.make(offset_us=7_000_000, skew=200e-6, lats=(0.001, 0.0003, 0.002, 0.0003))
        cs = ClockSync()
        for _ in range(40):
            cs.sample(cam, 1)
            clk.t += 0.1
        self.assertAlmostEqual(cs.best_rtt, 0.0006, places=6)
        # skew: host seconds per device second = 1/(1+200e-6)
        self.assertAlmostEqual(cs.skew_ppm, (1 / (1 + 200e-6) - 1) * 1e6, delta=5)
        dev_us = dev.dev_us()
        host_true = clk.t
        self.assertAlmostEqual(cs.to_host(dev_us), host_true, delta=50e-6)
        self.assertAlmostEqual(cs.to_device_us(host_true), dev_us, delta=50)
        # no-fit variant still within RTT/2 right after the best sample
        cs2 = ClockSync(fit=False).sample(cam, 8)
        self.assertAlmostEqual(cs2.to_host(dev.dev_us()), clk.t, delta=cs2.best_rtt / 2 + 1e-6)

    def test_clock_sync_pose_timestamp(self):
        cam, dev, t, clk = self.make(offset_us=123_456_789)
        cs = ClockSync().sample(cam, 8)
        clk.t += 0.5
        p = decode_pose(P.FrameDecoder().feed(dev.pose_frame())[0][1])
        self.assertAlmostEqual(cs.pose_host_time(p), clk.t, delta=1e-5)

    def test_synthetic_samples_with_jitter(self):
        cs = ClockSync()
        rnd = __import__('random').Random(1)
        for i in range(50):
            h = 10.0 + i * 0.05
            rtt = 0.0004 + rnd.random() * 0.004
            skew = 1 - 50e-6
            dev_s = 3.0 + (h - 10.0) / skew
            cs.add_sample(h - rtt / 2, h + rtt / 2, round(dev_s * 1e6))
        self.assertAlmostEqual(cs.to_host(round((3.0 + 5.0 / (1 - 50e-6)) * 1e6)), 15.0, delta=0.002)


if __name__ == '__main__':
    unittest.main()
