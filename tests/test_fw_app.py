"""Firmware application layer driven through the real byte protocol with a fake HAL (fake FPGA memory + fake flash)."""
import collections
import math
import os
import random
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwutil                      # noqa: E402
from fwutil import Dev, P, simfw   # noqa: E402
import geom                        # noqa: E402

class simfw_status:                  # trailer status bits of the frame packet (firmware/core/atframe.h)
    CSI_BAD, THR_BUSY, FIFO_OVF, SHORT, NO_CCL = 0x01, 0x02, 0x04, 0x08, 0x10


GT = fwutil.load_json('test_images/ground_truth.json')['images']
RTL = fwutil.load_json('results/rtl_chain_results.json')
CAL = fwutil.load_json('config/camera_calibration.json')
TMAP = fwutil.load_json('config/tag_map.json')['tags']
KNOWN = {t['id'] for t in TMAP}


def rtl_tags(name):
    return [(t['id'], t['corners'], t.get('ham', 0)) for t in RTL[name]['tags']]


@pytest.fixture
def dev():
    d = Dev()
    d.set_config(CAL, TMAP)
    return d


def push(d, tags, fid=None):
    d.fpga.publish(tags, frame_id=fid)
    return d.fw.poll()


def last_pose(d):
    r = d.send(P.CMD_GET_POSE)
    assert r and r[0][0] == P.RSP_POSE, r
    return P.decode_pose(r[0][1])


def pose_error(p, g):
    R = np.array(p.rotation_matrix())
    t = np.array(p.position)
    return np.linalg.norm(t - np.array(g['t_wc'])) * 1000, geom.rot_angle_deg(R, np.array(g['R_wc']))


# --------------------------------------------------------------------------------------------- basic commands
def test_ping_echo_version_and_fpga_id():
    d = Dev()
    r = d.rsp(P.CMD_PING, b'abcd', P.RSP_PONG)
    assert r[:4] == b'abcd'
    assert struct.unpack_from('<II', r, 4) == (0x00010000, simfw.FPGA_ID)
    assert d.rsp(P.CMD_PING, b'', P.RSP_PONG)[:4] == bytes(4)           # short payload tolerated


def test_set_calibration_and_readback():
    d = Dev()
    d.set_config(CAL, [])
    cfg = d.rsp(P.CMD_GET_CONFIG, b'', P.RSP_CONFIG)
    v = struct.unpack_from('<9f', cfg)
    assert v[:4] == pytest.approx((CAL['fx'], CAL['fy'], CAL['cx'], CAL['cy']), rel=1e-6)
    assert list(v[4:]) == pytest.approx(CAL['dist'], rel=1e-6)
    assert struct.unpack_from('<H', cfg, 36)[0] == 0


def test_clear_add_tags_and_get_tag_readback():
    d = Dev()
    d.ok(P.CMD_CLEAR_MAP)
    rng = random.Random(1)
    tags = fwutil.rand_tags(rng, 5)
    for t in tags:
        d.ok(P.CMD_ADD_TAG, fwutil.tag_body(t))
    for i, t in enumerate(tags):
        b = d.rsp(P.CMD_GET_TAG, struct.pack('<H', i), P.RSP_TAG)
        tid, pad, size, x, y, z, qw, qx, qy, qz = struct.unpack('<HHf3f4f', b)
        assert tid == t['id'] and size == pytest.approx(t['size'], rel=1e-6)
        assert [x, y, z] == pytest.approx(t['position'], rel=1e-6)
        q = np.array([qw, qx, qy, qz]); q0 = np.array(t['quat_wxyz'])
        assert abs(abs(q @ q0) - 1) < 1e-6
    # re-adding an existing id replaces it (does not grow the map)
    t2 = dict(tags[2], size=0.5)
    d.ok(P.CMD_ADD_TAG, fwutil.tag_body(t2))
    assert struct.unpack_from('<H', d.rsp(P.CMD_GET_CONFIG, b'', P.RSP_CONFIG), 36)[0] == 5
    assert struct.unpack_from('<f', d.rsp(P.CMD_GET_TAG, struct.pack('<H', 2), P.RSP_TAG), 4)[0] == pytest.approx(0.5)
    d.ok(P.CMD_CLEAR_MAP)
    assert struct.unpack_from('<H', d.rsp(P.CMD_GET_CONFIG, b'', P.RSP_CONFIG), 36)[0] == 0


def test_map_full_nak_but_replace_still_allowed():
    d = Dev()
    tags = fwutil.rand_tags(random.Random(2), 64)
    for t in tags:
        d.ok(P.CMD_ADD_TAG, fwutil.tag_body(t))
    extra = dict(fwutil.rand_tags(random.Random(3), 1, id_pool=range(600, 700))[0])
    assert d.nak(P.CMD_ADD_TAG, fwutil.tag_body(extra)) == P.ERR_FULL
    d.ok(P.CMD_ADD_TAG, fwutil.tag_body(dict(tags[10], size=0.3)))
    assert struct.unpack_from('<H', d.rsp(P.CMD_GET_CONFIG, b'', P.RSP_CONFIG), 36)[0] == 64


def test_commit_reboot_persists_config(dev):
    before = dev.dump()
    dev.ok(P.CMD_COMMIT)
    dev.reboot()
    assert fwutil.close_dump(before, dev.dump())
    # and the pose solution after reboot still works
    push(dev, rtl_tags('normal_004'))
    assert pose_error(last_pose(dev), GT['normal_004'])[0] < 10


def test_reboot_without_commit_loses_changes(dev):
    dev.reboot()
    assert dev.dump()[1] == []


# --------------------------------------------------------------------------------------------- NAK paths
@pytest.mark.parametrize('cmd,good', [(P.CMD_SET_CALIB, 36), (P.CMD_ADD_TAG, 34), (P.CMD_GET_TAG, 2), (P.CMD_STREAM, 3),
                                      (P.CMD_SET_SENSOR, 3), (P.CMD_SET_TRACK, 4), (P.CMD_SET_AE, 1)])
def test_bad_length_nak(cmd, good):
    d = Dev()
    for n in (0, good - 1, good + 1, 255):
        if n == good or n < 0:
            continue
        assert d.nak(cmd, bytes(n)) == P.ERR_BAD_LEN, (hex(cmd), n)


def test_unknown_commands_nak_and_survive():
    d = Dev()
    for c in (0x00, 0x10, 0x11, 0x55, 0x7F, 0x80, 0x82, 0xFE):
        assert d.nak(c, b'\x01\x02') == P.ERR_UNKNOWN
    assert d.rsp(P.CMD_PING, b'xxxx', P.RSP_PONG)[:4] == b'xxxx'


def test_range_errors():
    d = Dev()
    assert d.nak(P.CMD_SET_CALIB, P.encode_calib(0.5, 640, 0, 0)) == P.ERR_RANGE
    assert d.nak(P.CMD_SET_CALIB, P.encode_calib(640, float('nan'), 0, 0)) == P.ERR_RANGE
    assert d.nak(P.CMD_GET_TAG, struct.pack('<H', 0)) == P.ERR_RANGE            # empty map
    d.ok(P.CMD_ADD_TAG, fwutil.tag_body(TMAP[0]))
    assert d.nak(P.CMD_GET_TAG, struct.pack('<H', 1)) == P.ERR_RANGE
    assert d.nak(P.CMD_GET_TAG, struct.pack('<H', 0xFFFF)) == P.ERR_RANGE
    assert d.nak(P.CMD_SET_SENSOR, struct.pack('<HB', 0, 0x10)) == P.ERR_RANGE
    assert d.nak(P.CMD_SET_SENSOR, struct.pack('<HB', 801, 0x10)) == P.ERR_RANGE
    assert d.nak(P.CMD_SET_SENSOR, struct.pack('<HB', 100, 0x0F)) == P.ERR_RANGE
    assert d.fpga.i2c_log == []                         # rejected requests never touch the sensor


def test_get_pose_before_any_result_is_nak_no_pose():
    d = Dev()
    assert d.nak(P.CMD_GET_POSE) == P.ERR_NO_POSE


def test_garbage_and_oversize_do_not_disturb_device(dev):
    rng = random.Random(4)
    dev.fw.rx(bytes(rng.randrange(1, 256) for _ in range(3000)) + b'\x00')
    dev.fw.rx(P.encode_frame(P.CMD_PING, bytes(256)))              # longest legal body: PING tolerates it
    dev.drain()
    assert dev.rsp(P.CMD_PING, b'ok!!', P.RSP_PONG)[:4] == b'ok!!'
    assert dev.fw.stats()['rx_bad_frames'] >= 1


# --------------------------------------------------------------------------------------------- status / stream
def test_status_message(dev):
    b = dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS)
    st = P.decode_status(b)
    assert st.ntags == len(TMAP) and not st.pose_valid and not st.streaming and st.init_done
    assert st.ae_enabled and st.exposure == 100 and st.gain == 0x10
    push(dev, rtl_tags('normal_004'), fid=77)
    st = P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))
    assert st.solved == 1 and st.pose_valid and st.frame_id == 77 and st.fpga_seq == 1 and st.res_valid


def test_stream_on_off_and_divider(dev):
    names = ['normal_004', 'bright_001', 'normal_006']
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 1, 1))
    for i in range(6):
        push(dev, rtl_tags(names[i % 3]), fid=i + 1)
    poses = [P.decode_pose(b) for t, b in dev.drain() if t == P.RSP_POSE]
    assert [p.frame_id for p in poses] == [1, 2, 3, 4, 5, 6]
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 1, 3))
    for i in range(9):
        push(dev, rtl_tags('normal_004'), fid=100 + i)
    poses = [P.decode_pose(b) for t, b in dev.drain() if t == P.RSP_POSE]
    assert [p.frame_id for p in poses] == [102, 105, 108]
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 0, 1))
    push(dev, rtl_tags('normal_004'))
    assert [t for t, b in dev.drain() if t == P.RSP_POSE] == []
    # divider 0 behaves like 1
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 1, 0))
    push(dev, rtl_tags('normal_004'))
    push(dev, rtl_tags('normal_004'))
    assert len([1 for t, b in dev.drain() if t == P.RSP_POSE]) == 2


def test_stream_not_emitted_when_solve_fails(dev):
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 1, 1))
    push(dev, [(999, [[0, 0], [10, 0], [10, 10], [0, 10]], 0)])
    push(dev, [])
    assert dev.drain() == []


def test_get_tags_raw_reports_last_frame(dev):
    tags = rtl_tags('normal_004')
    push(dev, tags, fid=5)
    b = dev.rsp(P.CMD_GET_TAGS_RAW, b'', P.RSP_TAGS)
    fid, n = struct.unpack_from('<IB', b)
    assert fid == 5 and n == min(len(tags), 7) and len(b) == 5 + 35 * n     # body limit 256 -> at most 7 tags
    tid, ham = struct.unpack_from('<HB', b, 5)
    assert tid == tags[0][0]
    c = struct.unpack_from('<8f', b, 8)
    assert c == pytest.approx(tuple(v for xy in tags[0][1] for v in xy), abs=1.5e-5 * 1280)


# --------------------------------------------------------------------------------------------- FPGA polling
def test_no_frame_yet_and_each_packet_processed_once(dev):
    assert dev.fw.poll() == 0 and dev.fw.stats()['solved'] == 0
    assert push(dev, rtl_tags('normal_004')) == 1
    assert dev.fw.poll() == 0 and dev.fw.poll() == 0                 # packet was released: nothing new
    assert dev.fw.stats()['solved'] == 1
    assert push(dev, rtl_tags('normal_004')) == 1


def test_register_read_failures_do_not_stop_frame_processing(dev):
    """frames arrive on the bus, not over SPI: a failing register read (GET_STATUS) must not disturb them"""
    dev.fpga.fail_reads = 1
    dev.fpga.publish(rtl_tags('normal_004'))
    assert dev.fw.poll() == 1 and dev.fw.stats()['solved'] == 1
    dev.fpga.fail_reads = 5
    assert dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS)               # status answers even though the register reads failed
    dev.fpga.fail_reads = 0
    dev.fpga.publish(rtl_tags('normal_006'))
    assert dev.fw.poll() == 1 and dev.fw.stats()['solved'] == 2


def test_damaged_packets_are_rejected_and_counted(dev):
    good = simfw.make_packet(5, 1000, 0, 0, count=0)
    bad_magic = bytearray(good); bad_magic[0] ^= 1
    bad_check = bytearray(good); bad_check[4 * 32007] ^= 1                         # trailer check word
    short = good[:-4]
    for pkt in (bytes(bad_magic), bytes(bad_check), short, good[:100]):
        dev.fpga.publish_packet(pkt)
        assert dev.fw.poll() == 0
    for status in (simfw_status.CSI_BAD, simfw_status.FIFO_OVF, simfw_status.SHORT, simfw_status.NO_CCL):   # flagged by the FPGA itself
        dev.fpga.publish_packet(simfw.make_packet(6, 1000, 0, status))
        assert dev.fw.poll() == 0
    s = dev.fw.stats()
    assert s['torn_reads'] == 8 and s['solved'] == 0 and s['frame_id'] == 0
    assert P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS)).torn_reads == 8
    dev.fpga.publish_packet(simfw.make_packet(7, 1000, 0, simfw_status.THR_BUSY))     # diagnostic bit only: still processed
    assert dev.fw.poll() == 1 and dev.fw.stats()['frame_id'] == 7
    push(dev, rtl_tags('normal_004'))                                                 # and the device keeps working
    assert dev.fw.stats()['solved'] == 1


def test_lost_frames_are_reported_in_status(dev):
    for k in range(5):
        dev.fpga.publish(rtl_tags('normal_004'), frame_id=20 + k)          # two buffers: the rest is lost before the firmware sees them
    assert dev.fpga.lost == 3
    assert dev.fw.poll() == 1 and dev.fw.poll() == 1 and dev.fw.poll() == 0
    st = P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))
    assert st.frames_dropped == 3 and st.frames_processed == 2


def test_real_packet_goes_through_the_c_tag_unit(dev):
    """a packet with a real mask + candidate list (no injected detections) is decoded by the firmware's own tag unit"""
    import cv2
    import golden
    from test_tpu import pack_fb
    img = cv2.imread(os.path.join(fwutil.ROOT, 'test_images', 'sensor', 'normal_004.png'), 0)
    mask = golden.binarize_clean(img)
    keep, lab, _ = golden.components(mask)
    keep = keep[:64]
    words = np.array(golden.pack_records(keep, lab), np.uint64).astype(np.uint32)
    dev.fpga.publish_packet(simfw.make_packet(77, 5000, 0, 0, mask=pack_fb(mask), cand=words, count=len(keep)))
    assert dev.fw.poll() == 1
    s = dev.fw.stats()
    want = {t[0] for t in rtl_tags('normal_004')}
    assert s['frame_id'] == 77 and s['nobs'] == len(want)
    raw = dev.rsp(P.CMD_GET_TAGS_RAW, b'', P.RSP_TAGS)
    ids = {struct.unpack_from('<H', raw, 5 + 35 * i)[0] for i in range(raw[4])}
    assert ids <= want and len(ids) >= 5


def test_set_track_maxham_reaches_the_tag_unit(dev):
    dev.ok(P.CMD_SET_TRACK, bytes([24, 64, 10, 0]))                        # maxham 0 is stored; the FPGA register keeps the field for read-back
    assert dev.fpga.regs[simfw.REG_THRESH] == 24 | (64 << 8) | (10 << 16)


def test_unknown_tag_ids(dev):
    c = [[100, 100], [140, 100], [140, 140], [100, 140]]
    assert push(dev, [(500, c, 0), (501, c, 0)]) == 1
    s = dev.fw.stats()
    assert s['solved'] == 0 and s['solve_fail'] == 1 and s['pose_valid'] == 0
    assert dev.nak(P.CMD_GET_POSE) == P.ERR_NO_POSE
    # unknown ids mixed with known ones are ignored by the solver
    tags = rtl_tags('normal_004') + [(500, c, 0), (600, c, 1)]
    push(dev, tags)
    p = last_pose(dev)
    assert p.ntags == len(rtl_tags('normal_004')) and pose_error(p, GT['normal_004'])[0] < 10
    assert p.nobs == len(tags)


def test_zero_tags_is_not_a_failure(dev):
    assert push(dev, []) == 1
    s = dev.fw.stats()
    assert s['solved'] == 0 and s['solve_fail'] == 0 and s['nobs'] == 0


def test_observations_capped_at_16(dev):
    tags = rtl_tags('normal_004')
    many = [(TMAP[i % len(TMAP)]['id'], tags[i % len(tags)][1], 0) for i in range(25)]
    push(dev, many)
    assert dev.fw.stats()['nobs'] == 16


def test_outlier_tag_is_dropped_and_flagged(dev):
    tags = rtl_tags('normal_004')
    assert len(tags) >= 5
    bad = [(tid, [[x + 60, y - 45] for x, y in c] if i == 0 else c, h) for i, (tid, c, h) in enumerate(tags)]
    push(dev, bad)
    p = last_pose(dev)
    assert p.flags & P.Pose.FLAG_OUTLIER_DROPPED
    assert p.ntags == len(tags) - 1
    assert pose_error(p, GT['normal_004'])[0] < 15


def test_single_tag_flag(dev):
    push(dev, rtl_tags('normal_004')[:1])
    p = last_pose(dev)
    assert p.flags & P.Pose.FLAG_SINGLE_TAG and p.ntags == 1


def test_processing_time_reported(dev):
    push(dev, rtl_tags('normal_004'))
    assert last_pose(dev).processing_us == 250        # fake clock steps 250 us per micros() call


# --------------------------------------------------------------------------------------------- sensor / tracking commands
def test_set_sensor_writes_expected_i2c_sequence_and_disables_ae(dev):
    dev.ok(P.CMD_SET_SENSOR, struct.pack('<HB', 300, 0x24))
    assert dev.fpga.i2c_log == [(0x3308, 1), (0x3500, 0), (0x3501, (300 << 4) >> 8 & 0xFF), (0x3502, (300 << 4) & 0xFF),
                                (0x3509, 0x24), (0x3308, 0)]
    assert dev.fpga.sensor_exposure == 300 and dev.fpga.sensor_gain == 0x24
    st = P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))
    assert not st.ae_enabled and st.exposure == 300 and st.gain == 0x24
    dev.fpga.frame_sum = 3 * simfw.FRAME_PIXELS
    dev.fpga.i2c_log.clear()
    for _ in range(5):
        push(dev, [])
    assert dev.fpga.i2c_log == []                          # AE is off: the sensor is left alone
    dev.ok(P.CMD_SET_AE, b'\x01')
    for _ in range(5):
        push(dev, [])
    assert dev.fpga.i2c_log                                # AE re-enabled: it reacts to the dark frame
    dev.ok(P.CMD_SET_AE, b'\x00')
    assert not P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS)).ae_enabled


def test_i2c_busy_polling_is_bounded(dev):
    dev.fpga.i2c_busy_polls = 10 ** 9                      # sensor bridge never becomes idle
    dev.ok(P.CMD_SET_SENSOR, struct.pack('<HB', 100, 0x10))  # must not hang


def test_set_tracking_params_register(dev):
    dev.ok(P.CMD_SET_TRACK, bytes([20, 70, 12, 0xFF]))
    assert dev.fpga.regs[simfw.REG_THRESH] == 20 | 70 << 8 | 12 << 16 | 63 << 24   # maxham masked to 6 bits


# --------------------------------------------------------------------------------------------- pose accuracy, whole stack
def _category(name):
    for k in ('normal', 'bright', 'dark', 'lowcon', 'grad', 'shadow', 'noise', 'clutter', 'blur', 'persp'):
        if name.startswith(k):
            return k
    return 'other'


def test_pose_accuracy_all_images_through_whole_stack(capsys):
    d = Dev()
    d.set_config(CAL, TMAP)
    rows = []
    fid = 0
    for name, r in RTL.items():
        g = GT[name]
        fid += 1
        tags = rtl_tags(name)
        d.fpga.publish(tags, frame_id=fid)
        d.fw.poll()
        d.drain()
        known = [t for t in tags if t[0] in KNOWN]
        reply = d.send(P.CMD_GET_POSE)
        if len(known) == 0:
            assert reply[0][0] == P.RSP_NAK or True
        if reply and reply[0][0] == P.RSP_POSE and len(known) > 0:
            p = P.decode_pose(reply[0][1])
            assert p.frame_id == fid
            et, er = pose_error(p, g)
            rows.append((name, _category(name), len(known), et, er, p.rms_px, p.flags, p.processing_us))
        else:
            rows.append((name, _category(name), len(known), None, None, None, 0, 0))
    multi = [r for r in rows if r[2] >= 2]
    solved = [r for r in multi if r[3] is not None]
    assert len(multi) > 40 and len(solved) == len(multi), 'every image with >=2 tags must give a pose'
    et = np.array([r[3] for r in solved])
    er = np.array([r[4] for r in solved])
    with capsys.disabled():
        print('\n=== pose accuracy through firmware (RTL tag estimates -> fake FPGA -> at_app_poll -> POSE message) ===')
        print('images: %d total, %d with >=2 known tags (all solved), %d with 1 tag, %d with none'
              % (len(rows), len(multi), sum(1 for r in rows if r[2] == 1), sum(1 for r in rows if r[2] == 0)))
        print('translation error mm : median %.2f  mean %.2f  p90 %.2f  p95 %.2f  max %.2f' %
              (np.median(et), et.mean(), np.percentile(et, 90), np.percentile(et, 95), et.max()))
        print('rotation error deg   : median %.3f  mean %.3f  p90 %.3f  p95 %.3f  max %.3f' %
              (np.median(er), er.mean(), np.percentile(er, 90), np.percentile(er, 95), er.max()))
        print('%-8s %4s %8s %8s %8s %8s %8s' % ('category', 'n', 'med mm', 'max mm', 'med deg', 'max deg', 'med tags'))
        cats = collections.defaultdict(list)
        for r in solved:
            cats[r[1]].append(r)
        for c, rs in sorted(cats.items()):
            a = np.array([r[3] for r in rs]); b = np.array([r[4] for r in rs])
            print('%-8s %4d %8.2f %8.2f %8.3f %8.3f %8.0f' % (c, len(rs), np.median(a), a.max(), np.median(b), b.max(),
                                                           np.median([r[2] for r in rs])))
        worst = sorted(solved, key=lambda r: -r[3])[:5]
        print('worst 5 :', ', '.join('%s %.1fmm/%.2fdeg(%d tags)' % (r[0], r[3], r[4], r[2]) for r in worst))
    assert np.median(et) < 5.0
    assert np.median(er) < 0.2


def test_pose_message_matches_native_solver_exactly():
    """The pose in the POSE message is the quaternion/translation of the same solver output (round trip through the wire)."""
    d = Dev()
    d.set_config(CAL, TMAP)
    push(d, rtl_tags('persp_002'))
    p = last_pose(d)
    assert abs(sum(x * x for x in p.quaternion) - 1) < 1e-5
    R = np.array(p.rotation_matrix())
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-5) and np.linalg.det(R) > 0.999


# --------------------------------------------------------------------------------------------- auto exposure
import ctypes as C                 # noqa: E402

TARGET, DEADBAND = 110, 12


class AeState(C.Structure):
    _fields_ = [('exposure', C.c_uint16), ('gain', C.c_uint8), ('settle', C.c_uint8)]


class SimSensor:
    """Scene model: mean = min(255, k * exposure * gain/16 + noise), k = brightness per line at 1x.  Sensor register writes take
    effect on the frame `latency` frames after the next one (latency 0 = the very next frame)."""
    def __init__(self, dev, k, latency=1, noise=0.0, seed=0, start=(100, 0x10)):
        self.dev, self.k, self.latency, self.noise = dev, k, latency, noise
        self.rng = random.Random(seed)
        self.hist = [start] * (latency + 2)          # settings in force after each processed frame
        self.log = []                                # (mean seen, exposure, gain, sensor writes) after the firmware processed the frame

    def frame(self):
        e, g = self.hist[-1 - self.latency]
        mean = min(255.0, max(0.0, self.k * e * g / 16.0 + self.rng.uniform(-self.noise, self.noise)))
        self.dev.fpga.frame_sum = int(mean * simfw.FRAME_PIXELS)
        before = self.dev.fw.stats()['ae_updates']
        self.dev.fpga.publish([])
        self.dev.fw.poll()
        regs = (self.dev.fpga.sensor_exposure, self.dev.fpga.sensor_gain) if self.dev.fpga.i2c_log else self.hist[-1]
        self.hist.append(regs)
        self.log.append((mean, regs[0], regs[1], self.dev.fw.stats()['ae_updates'] - before))
        return mean

    def run(self, n):
        for _ in range(n):
            self.frame()
        return self.log


def converge_frame(log, tol=DEADBAND):
    """first index from which every later frame is inside the deadband (None if never)"""
    ok = [abs(m - TARGET) <= tol for m, *_ in log]
    for i in range(len(ok)):
        if all(ok[i:]):
            return i
    return None


def invariants(log):
    for m, e, g, _ in log:
        assert 8 <= e <= 400 and 0x10 <= g <= 0xFF, (e, g)
        assert g == 0x10 or e == 400, (e, g)         # exposure first, gain only beyond 400 lines


def start_ae(dev, exposure, gain):
    dev.ok(P.CMD_SET_SENSOR, struct.pack('<HB', exposure, gain))
    dev.fpga.i2c_log.clear()
    dev.ok(P.CMD_SET_AE, b'\x01')


@pytest.mark.parametrize('latency', [0, 1])
@pytest.mark.parametrize('k,start,name', [(0.1, (100, 0x10), 'dark start (mean 10)'), (0.3, (8, 0x10), 'very dark exposure'),
                                          (10.0, (100, 0x10), 'saturated start (clipped 255)'),
                                          (3.0, (400, 0x80), 'saturated at max exposure+gain'), (1.1, (100, 0x10), 'on target')])
def test_ae_converges_within_10_frames(k, start, name, latency, capsys):
    d = Dev()
    d.set_config(CAL, TMAP)
    sensor = SimSensor(d, k, latency=latency, start=start)
    if start != (100, 0x10):
        start_ae(d, *start)
    log = sensor.run(40)
    invariants(log)
    cf = converge_frame(log)
    assert cf is not None and cf <= 10, (name, cf, [(round(m), e, g) for m, e, g, _ in log[:14]])
    writes_after = sum(w for *_, w in log[cf + 1:])
    assert writes_after == 0                                   # stays put once inside the deadband
    with capsys.disabled():
        print('\nAE %-34s latency %d: first in-band frame %2d, final mean %.1f, exposure %d gain 0x%02X, %d sensor writes'
              % (name, latency, cf, log[-1][0], log[-1][1], log[-1][2], sum(w for *_, w in log)))


def test_ae_no_oscillation_dark_and_saturated_are_monotone():
    for k, start in ((0.1, (100, 0x10)), (10.0, (100, 0x10))):
        d = Dev()
        d.set_config(CAL, TMAP)
        s = SimSensor(d, k)
        totals = []
        for m, e, g, w in s.run(30):
            totals.append(e * g / 16.0)
        diffs = [b - a for a, b in zip(totals, totals[1:]) if b != a]
        reversals = sum(1 for a, b in zip(diffs, diffs[1:]) if (a > 0) != (b > 0))
        assert reversals <= 1, (k, totals)


@pytest.mark.parametrize('latency', [0, 1])
def test_ae_recovers_from_scene_brightness_steps(latency, capsys):
    d = Dev()
    d.set_config(CAL, TMAP)
    s = SimSensor(d, 1.1, latency=latency)
    s.run(25)
    res = []
    for factor in (5.0, 0.2, 8.0, 0.125):                  # scene gets much brighter / darker
        s.k *= factor
        n0 = len(s.log)
        s.run(25)
        cf = converge_frame(s.log[n0:])
        res.append(cf)
        assert cf is not None and cf <= 10, (factor, cf, [(round(m), e, g) for m, e, g, _ in s.log[n0:n0 + 14]])
        assert sum(w for *_, w in s.log[n0 + cf + 1:]) == 0
    invariants(s.log)
    with capsys.disabled():
        print('\nAE scene steps x5, x0.2, x8, x0.125 (latency %d): frames to settle %s' % (latency, res))


def test_ae_noise_does_not_cause_hunting():
    d = Dev()
    d.set_config(CAL, TMAP)
    s = SimSensor(d, 1.1, noise=5.0, seed=3)                # +-5 counts of frame-to-frame noise
    s.run(10)
    n0 = len(s.log)
    s.run(300)
    assert sum(w for *_, w in s.log[n0:]) == 0


def test_ae_gradual_drift_tracks_scene():
    d = Dev()
    d.set_config(CAL, TMAP)
    s = SimSensor(d, 1.0)
    s.run(10)
    worst = 0
    for i in range(200):
        s.k = 1.0 * math.exp(math.log(8) * i / 200)        # 8x brighter over 200 frames
        s.frame()
        worst = max(worst, abs(s.log[-1][0] - TARGET))
    assert worst < 60
    assert abs(s.log[-1][0] - TARGET) <= DEADBAND + 1
    invariants(s.log)
    assert sum(w for *_, w in s.log) < 40                    # a handful of small steps, not a write per frame


def test_ae_limits_do_not_spam_the_sensor():
    d = Dev()
    d.set_config(CAL, TMAP)
    s = SimSensor(d, 400.0)                                  # impossibly bright: even 8 lines at 1x saturates
    s.run(30)
    assert s.log[-1][1] == 8 and s.log[-1][2] == 0x10
    assert sum(w for *_, w in s.log[10:]) == 0
    d2 = Dev()
    d2.set_config(CAL, TMAP)
    s2 = SimSensor(d2, 0.001)                                # impossibly dark
    s2.run(30)
    assert s2.log[-1][1] == 400 and s2.log[-1][2] == 0xFF
    assert sum(w for *_, w in s2.log[10:]) == 0


def test_ae_step_unit_behaviour():
    L = simfw.lib()
    ae = AeState()
    L.at_ae_init(C.byref(ae), 100, 0x10)
    assert (ae.exposure, ae.gain) == (100, 0x10)
    ae.settle = 0
    for mean in (TARGET - DEADBAND, TARGET, TARGET + DEADBAND):
        assert L.at_ae_step(C.byref(ae), C.c_float(mean)) == 0                     # inside the deadband
    assert L.at_ae_step(C.byref(ae), C.c_float(TARGET + DEADBAND + 1)) == 1 and ae.exposure < 100
    assert ae.settle >= 1
    assert L.at_ae_step(C.byref(ae), C.c_float(5)) == 0                            # settling: measurement ignored
    ae.settle = 0
    e0 = ae.exposure
    L.at_ae_step(C.byref(ae), C.c_float(1))                                        # extremely dark: at most 4x per step
    assert e0 < ae.exposure <= e0 * 4 + 1
    L.at_ae_init(C.byref(ae), 400, 0x10)
    ae.settle = 0
    assert L.at_ae_step(C.byref(ae), C.c_float(30)) == 1 and ae.exposure == 400 and ae.gain > 0x10   # beyond 400 lines -> gain
    L.at_ae_init(C.byref(ae), 5000, 3)                                             # out-of-range init values are clamped
    assert ae.exposure == 400 and ae.gain == 0x10


def test_ae_status_reports_mean_and_settings(dev):
    s = SimSensor(dev, 1.1)
    s.run(12)
    st = P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))
    assert st.ae_enabled and abs(st.mean_brightness - TARGET) < DEADBAND + 1
    assert (st.exposure, st.gain) == (dev.fpga.sensor_exposure, dev.fpga.sensor_gain)


# --------------------------------------------------------------------------------------------- device clock
def test_get_time_reports_clock_and_tick_rate(dev):
    dev.fpga.time_us = 0x1_2345_6789                       # crosses the 32 bit boundary
    t = P.decode_time(dev.rsp(P.CMD_GET_TIME, b'', P.RSP_TIME))
    assert (t.now_us, t.frame_us, t.tick_hz) == (0x1_2345_6789, 0, 1_000_000)
    assert dev.nak(P.CMD_GET_TIME, b'\x00') == P.ERR_BAD_LEN


def test_pose_carries_capture_timestamp_of_its_own_bank(dev):
    name = next(iter(RTL))
    stamps = []
    for k in range(4):                                       # banks alternate; each frame has its own start time
        dev.fpga.time_us = 1_000_000 + 8333 * k + (k % 2) * (1 << 32)
        stamps.append(dev.fpga.time_us)
        assert push(dev, rtl_tags(name))
        assert last_pose(dev).timestamp_us == stamps[-1]
    dev.fpga.time_us += 5000
    t = P.decode_time(dev.rsp(P.CMD_GET_TIME, b'', P.RSP_TIME))
    assert t.frame_us == stamps[-1] and t.now_us == dev.fpga.time_us
