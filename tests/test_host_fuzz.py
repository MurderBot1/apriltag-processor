"""Host-side protocol robustness: garbage, split packets, dropped / flipped bytes must never crash and must recover."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwutil                      # noqa: E402
from fwutil import P, simfw        # noqa: E402
from apriltag_cam import Camera, CameraError, CameraTimeout, SimTransport, Transport, load_rtl_frames   # noqa: E402

CAL = fwutil.load_json('config/camera_calibration.json')
TMAP = fwutil.load_json('config/tag_map.json')


class FaultyTransport(Transport):
    """Wraps a transport and damages the byte stream in both directions."""
    def __init__(self, inner, seed=0, drop_rx=0.0, drop_tx=0.0, flip_rx=0.0, garbage_rx=0.0, garbage_tx=0.0, split_rx=0, split_tx=0):
        self.inner, self.rng = inner, random.Random(seed)
        self.drop_rx, self.drop_tx, self.flip_rx = drop_rx, drop_tx, flip_rx
        self.garbage_rx, self.garbage_tx, self.split_rx, self.split_tx = garbage_rx, garbage_tx, split_rx, split_tx
        self._pending = bytearray()
        self.dropped = 0

    def _garbage(self):
        return bytes(self.rng.randrange(256) for _ in range(self.rng.randrange(1, 12)))

    def write(self, data):
        out = bytearray()
        if self.rng.random() < self.garbage_tx:
            out += self._garbage() + b'\x00'
        for b in data:
            if self.rng.random() < self.drop_tx:
                self.dropped += 1
                continue
            out.append(b)
        if self.split_tx:
            for i in range(0, len(out), self.split_tx):
                self.inner.write(bytes(out[i:i + self.split_tx]))
        elif out:
            self.inner.write(bytes(out))

    def read(self, n, timeout):
        data = self.inner.read(n, timeout)
        out = bytearray()
        if data and self.rng.random() < self.garbage_rx:
            out += self._garbage()
        for b in data:
            if self.rng.random() < self.drop_rx:
                self.dropped += 1
                continue
            if self.rng.random() < self.flip_rx:
                b ^= 1 << self.rng.randrange(8)
            out.append(b)
        self._pending += out
        k = self.split_rx or len(self._pending)
        chunk = bytes(self._pending[:k])
        del self._pending[:k]
        return chunk

    def close(self):
        self.inner.close()


def faulty_cam(seed, frames=None, **kw):
    st = SimTransport(frames)
    cam_kw = dict(timeout=0.05, retries=8)
    ft = FaultyTransport(st, seed=seed, **kw)
    return Camera(ft, **cam_kw), st, ft


def configure(cam):
    cam.set_calibration(CAL)
    cam.set_field(TMAP)


def test_split_packets_one_byte_at_a_time_both_directions():
    cam, st, ft = faulty_cam(1, split_rx=1, split_tx=1)
    configure(cam)
    assert cam.ping()['fpga_id'] == simfw.FPGA_ID
    assert len(cam.get_config()['tags']) == 12
    assert cam.dec.bad_frames == 0 and st.fw.stats()['rx_bad_frames'] == 0


def test_split_packets_random_sizes():
    for seed in range(5):
        for k in (2, 3, 5, 7):
            cam, st, ft = faulty_cam(seed, split_rx=k, split_tx=k + 1)
            configure(cam)
            cam.commit()
            assert cam.get_status().ntags == 12


def test_garbage_in_both_directions_is_resynchronised():
    cam, st, ft = faulty_cam(2, garbage_rx=0.5, garbage_tx=0.5)
    configure(cam)
    for _ in range(20):
        assert cam.ping(b'abcd')['echo'] == b'abcd'
    assert cam.get_status().ntags == 12
    assert cam.dec.bad_frames > 0                             # the garbage was noticed and discarded


def test_dropped_bytes_device_to_host_are_retried():
    cam, st, ft = faulty_cam(3, drop_rx=0.004)
    configure(cam)
    for _ in range(30):
        cam.ping()
    assert ft.dropped > 0 and len(cam.get_config()['tags']) == 12


def test_dropped_bytes_host_to_device_are_retried():
    cam, st, ft = faulty_cam(4, drop_tx=0.01)
    configure(cam)
    cam.commit()
    cfg = cam.get_config()
    assert len(cfg['tags']) == 12 and ft.dropped > 0
    assert [t['id'] for t in cfg['tags']] == [t['id'] for t in TMAP['tags']]    # retries are idempotent: no duplicates / gaps
    assert st.fw.stats()['rx_bad_frames'] > 0


def test_bit_flips_on_the_wire_are_caught_by_crc():
    cam, st, ft = faulty_cam(5, flip_rx=0.01)
    configure(cam)
    for _ in range(40):
        assert cam.ping(b'wxyz')['echo'] == b'wxyz'
    assert cam.dec.bad_frames > 0


def test_everything_at_once():
    cam, st, ft = faulty_cam(6, drop_rx=0.005, drop_tx=0.005, flip_rx=0.003, garbage_rx=0.2, garbage_tx=0.2, split_rx=3, split_tx=4)
    cam.retries = 20
    configure(cam)
    cam.commit()
    assert len(cam.get_config()['tags']) == 12
    st.reboot()
    assert len(cam.get_config()['tags']) == 12


def test_stream_survives_corrupted_link():
    names = ['normal_004', 'normal_006', 'persp_002', 'bright_001', 'normal_002'] * 8
    cam, st, ft = faulty_cam(7, frames=load_rtl_frames(names), drop_rx=0.003, flip_rx=0.002, garbage_rx=0.1, split_rx=5)
    configure(cam)
    poses = list(cam.stream(timeout=0.2, on_timeout='stop'))
    assert 25 <= len(poses) <= len(names)                      # some poses may be lost, none are wrong
    ids = [p.frame_id for p in poses]
    assert ids == sorted(set(ids))
    for p in poses:
        assert 0.5 < p.position[1] < 3.0 and p.ntags >= 2
    cam.t = st                                                  # clean link again
    assert not cam.get_status().streaming


def test_random_byte_soup_into_host_decoder_never_raises():
    rng = random.Random(8)
    cam = Camera(SimTransport())
    for _ in range(300):
        junk = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 600)))
        cam.t.inner = None if False else cam.t
        for typ, body in cam.dec.feed(junk):
            pass
    assert cam.ping()
    # long non-zero runs, lone zeros, valid-looking headers with wrong CRC
    cam.dec.feed(b'\xff' * 5000 + b'\x00' + b'\x00' * 10 + P.encode_frame(P.RSP_ACK, b'\x01')[:-2] + b'\x00')
    assert cam.ping()


def test_random_byte_soup_into_firmware_never_corrupts_state():
    st = SimTransport()
    cam = Camera(st)
    configure(cam)
    cam.commit()
    before = cam.get_config()
    rng = random.Random(9)
    for _ in range(400):
        st.write(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 400))))
        st._out.clear()
    assert cam.ping()
    assert cam.get_config() == before
    assert st.fw.stats()['rx_bad_frames'] > 100


def test_wrong_response_types_and_stale_acks_are_ignored():
    """A stale ACK (for another command) or an unexpected message must not satisfy a request."""
    class Scripted(Transport):
        def __init__(self):
            self.out = bytearray(); self.writes = []
        def write(self, data):
            self.writes.append(data)
            self.out += P.encode_frame(P.RSP_ACK, bytes([P.CMD_CLEAR_MAP]))      # stale ACK of something else
            self.out += P.encode_frame(P.RSP_PONG, b'x' * 12)                      # wrong type
            if len(self.writes) >= 2:
                self.out += P.encode_frame(P.RSP_ACK, bytes([P.CMD_SET_AE]))      # the right one, on the retry
        def read(self, n, timeout):
            d = bytes(self.out[:n]); del self.out[:n]; return d
    t = Scripted()
    cam = Camera(t, timeout=0.02, retries=3)
    cam.set_ae(True)
    assert len(t.writes) == 2
    t2 = Scripted()
    cam = Camera(t2, timeout=0.02, retries=0)
    with pytest.raises(CameraTimeout):
        cam.set_ae(True)


def test_malformed_device_messages_do_not_crash_host():
    class Evil(Transport):
        def __init__(self, reply):
            self.reply, self.out = reply, bytearray()
        def write(self, data):
            self.out += self.reply
        def read(self, n, timeout):
            d = bytes(self.out[:n]); del self.out[:n]; return d
    short_pong = P.encode_frame(P.RSP_PONG, b'abc')
    with pytest.raises(CameraError):
        Camera(Evil(short_pong), timeout=0.05).ping()
    short_cfg = P.encode_frame(P.RSP_CONFIG, b'\x00' * 7)
    with pytest.raises(CameraError):
        Camera(Evil(short_cfg), timeout=0.05).get_config()
    bad_status = P.encode_frame(P.RSP_STATUS, b'\x00' * 7)
    with pytest.raises(ValueError):
        Camera(Evil(bad_status), timeout=0.05).get_status()
    bad_pose = P.encode_frame(P.RSP_POSE, b'\x00' * 7)           # dropped silently, so the request times out
    with pytest.raises(CameraTimeout):
        Camera(Evil(bad_pose), timeout=0.02, retries=0).get_pose()
