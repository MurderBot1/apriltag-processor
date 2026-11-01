"""End-to-end tests of the host library + CLI on top of SimTransport (native firmware + fake FPGA + fake flash)."""
import io
import json
import os
import struct
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fwutil                      # noqa: E402
from fwutil import P, simfw        # noqa: E402
import geom                        # noqa: E402
from apriltag_cam import Camera, CameraError, CameraTimeout, NakError, SimTransport, Transport, load_rtl_frames   # noqa: E402

sys.path.insert(0, os.path.join(fwutil.ROOT, 'host'))
import atcam                       # noqa: E402

GT = fwutil.load_json('test_images/ground_truth.json')['images']
CAL = fwutil.load_json('config/camera_calibration.json')
TMAP = fwutil.load_json('config/tag_map.json')
SEQ = ['normal_000', 'normal_004', 'normal_007', 'persp_002', 'persp_004', 'persp_000', 'bright_001', 'dark_004', 'grad_000', 'clutter_009', 'noise_003', 'noise_001']


def configured_cam(frames=None, **kw):
    cam = Camera(SimTransport(frames), **kw)
    cam.set_calibration(CAL)
    assert cam.set_field(TMAP) == len(TMAP['tags'])
    return cam


def err(pose, name):
    g = GT[name]
    return (np.linalg.norm(np.array(pose.position) - g['t_wc']) * 1000,
            geom.rot_angle_deg(np.array(pose.rotation_matrix()), np.array(g['R_wc'])))


class DeadTransport(Transport):
    """Accepts writes, never answers."""
    def __init__(self):
        self.written = bytearray()

    def write(self, data):
        self.written += data

    def read(self, n, timeout):
        time.sleep(min(timeout, 0.002))
        return b''


# ------------------------------------------------------------------------------------------ configuration
def test_ping():
    with Camera(SimTransport()) as cam:
        r = cam.ping()
        assert r['firmware_version'] == 0x00010000 and r['fpga_id'] == simfw.FPGA_ID and r['echo'] == b'ping'


def test_configure_commit_reboot_roundtrip():
    st = SimTransport()
    cam = Camera(st)
    cam.set_calibration(CAL)
    cam.set_field(TMAP)
    cam.commit()
    for phase in ('before reboot', 'after reboot'):
        cfg = cam.get_config()
        c = cfg['calibration']
        assert (c['fx'], c['fy'], c['cx'], c['cy']) == pytest.approx((CAL['fx'], CAL['fy'], CAL['cx'], CAL['cy']), rel=1e-6)
        assert c['dist'] == pytest.approx(CAL['dist'], rel=1e-6)
        assert [t['id'] for t in cfg['tags']] == [t['id'] for t in TMAP['tags']], phase
        for got, want in zip(cfg['tags'], TMAP['tags']):
            assert got['size'] == pytest.approx(want['size'], rel=1e-6)
            assert got['position'] == pytest.approx(want['position'], abs=1e-6)
            q, q0 = np.array(got['quat_wxyz']), np.array(want['quat_wxyz'])
            assert abs(abs(q @ q0 / np.linalg.norm(q0)) - 1) < 1e-6
        st.reboot()


def test_set_calibration_accepts_K_matrix_and_kwargs():
    cam = Camera(SimTransport())
    cam.set_calibration({'K': [[700, 0, 600], [0, 710, 400], [0, 0, 1]], 'dist': [0.1, 0.01]})
    c = cam.get_config()['calibration']
    assert (c['fx'], c['fy'], c['cx'], c['cy']) == (700, 710, 600, 400) and c['dist'] == pytest.approx([0.1, 0.01, 0, 0, 0])
    cam.set_calibration(fx=500, fy=500, cx=320, cy=240)
    assert cam.get_config()['calibration']['fx'] == 500


def test_set_field_validation():
    cam = Camera(SimTransport())
    t = TMAP['tags'][0]
    with pytest.raises(ValueError):
        cam.set_field([t, t])
    with pytest.raises(ValueError):
        cam.set_field([dict(t, id=i) for i in range(65)])
    assert cam.set_field(dict(tags=[dict(t, id=i) for i in range(64)])) == 64
    assert cam.get_status().ntags == 64


def test_nak_raises_exception_with_code():
    cam = Camera(SimTransport())
    with pytest.raises(NakError) as e:
        cam.set_calibration(fx=0.0, fy=640, cx=0, cy=0)
    assert e.value.code == P.ERR_RANGE and e.value.cmd == P.CMD_SET_CALIB and 'RANGE' in str(e.value)
    with pytest.raises(NakError) as e:
        cam.set_exposure_gain(0, 0x10)
    assert e.value.code == P.ERR_RANGE
    with pytest.raises(NakError) as e:
        cam.get_pose()
    assert e.value.code == P.ERR_NO_POSE
    with pytest.raises(CameraError):
        cam.get_pose()
    assert cam.ping()                                            # the link is still healthy after NAKs


def test_commit_flash_failure_is_reported():
    st = SimTransport()
    cam = Camera(st)
    st.fw.flash.dead = True
    with pytest.raises(NakError) as e:
        cam.commit()
    assert e.value.code == P.ERR_FLASH


def test_sensor_ae_and_tracking_commands():
    st = SimTransport()
    cam = Camera(st)
    assert cam.get_status().ae_enabled
    cam.set_exposure_gain(250, 0x20)
    s = cam.get_status()
    assert (s.exposure, s.gain, s.ae_enabled) == (250, 0x20, False)
    assert (st.fpga.sensor_exposure, st.fpga.sensor_gain) == (250, 0x20)
    cam.set_ae(True)
    assert cam.get_status().ae_enabled
    cam.set_tracking_params(diff=30, abs_black=50, mindim=8, maxham=1)
    assert st.fpga.regs[simfw.REG_THRESH] == 30 | 50 << 8 | 8 << 16 | 1 << 24
    assert cam.get_status().auto_ratio
    cam.set_auto_ratio(False)
    assert not cam.get_status().auto_ratio
    cam.set_auto_ratio(True)
    cam.set_tracking_params(ratio=2)
    st_ = cam.get_status()
    assert (st_.ratio, st_.auto_ratio) == (2, False)
    cam.set_tracking_params(maxham=3)
    assert st.fpga.regs[simfw.REG_THRESH] == 24 | 64 << 8 | 10 << 16 | 3 << 24
    cam.set_tracking_params(ratio=2)
    assert st.fpga.regs[simfw.REG_THRESH] == 24 | 64 << 8 | 10 << 16 | 2 << 24 | 2 << 30     # lowcon setting
    cam.set_tracking_params(ratio=0)
    assert st.fpga.regs[simfw.REG_THRESH] >> 30 == 0
    with pytest.raises(ValueError):
        cam.set_tracking_params(maxham=64)
    with pytest.raises(ValueError):
        cam.set_tracking_params(ratio=4)


def test_status_fields():
    cam = configured_cam()
    s = cam.get_status()
    assert s.ntags == 12 and s.init_done and not s.streaming and not s.pose_valid
    assert s.solved == 0 and s.torn_reads == 0


# ------------------------------------------------------------------------------------------ streaming
def test_stream_sequence_matches_ground_truth():
    frames = load_rtl_frames(SEQ)
    cam = configured_cam(frames)
    poses = list(cam.stream(divider=1, max_frames=len(SEQ)))
    assert len(poses) == len(SEQ)
    assert [p.frame_id for p in poses] == list(range(1, len(SEQ) + 1))
    errs = [err(p, n) for p, n in zip(poses, SEQ)]
    for (et, er), n, p in zip(errs, SEQ, poses):
        assert et < 40 and er < 1.5, (n, et, er)
        assert p.ntags >= 2 and p.processing_us > 0 and p.rms_px < 2
    assert np.median([e[0] for e in errs]) < 5 and np.median([e[1] for e in errs]) < 0.2
    assert not cam.get_status().streaming                       # generator close switched streaming off
    assert cam.get_status().solved == len(SEQ)


def test_stream_divider_and_position_semantics():
    frames = load_rtl_frames(['normal_004'] * 9)
    cam = configured_cam(frames)
    poses = list(cam.stream(divider=3, max_frames=3))
    assert [p.frame_id for p in poses] == [3, 6, 9]
    p = poses[0]
    assert len(p.position) == 3 and len(p.quaternion) == 4
    assert abs(sum(x * x for x in p.quaternion) - 1) < 1e-5
    assert np.allclose(np.array(p.rotation_matrix()) @ np.array(p.rotation_matrix()).T, np.eye(3), atol=1e-5)
    assert err(p, 'normal_004')[0] < 10


def test_stream_stops_cleanly_when_source_ends_or_times_out():
    cam = configured_cam(load_rtl_frames(['normal_004', 'normal_006']), timeout=0.05)
    got = list(cam.stream(timeout=0.05, on_timeout='stop'))
    assert len(got) == 2
    cam = configured_cam(load_rtl_frames(['normal_004']), timeout=0.05)
    with pytest.raises(CameraTimeout):
        list(cam.stream(timeout=0.05))
    assert not cam.get_status().streaming


def test_stream_break_early_turns_streaming_off():
    cam = configured_cam(load_rtl_frames(['normal_004'] * 5))
    g = cam.stream()
    next(g)
    g.close()
    assert not cam.get_status().streaming


def test_commands_work_while_streaming_and_poses_are_not_lost():
    st = SimTransport(load_rtl_frames(['normal_004'] * 6))
    cam = Camera(st)
    cam.set_calibration(CAL); cam.set_field(TMAP)
    g = cam.stream()
    first = next(g)
    assert cam.ping()['fpga_id'] == simfw.FPGA_ID               # interleaved request/response while poses flow
    assert cam.get_status().streaming
    rest = [next(g) for _ in range(3)]
    ids = [first.frame_id] + [p.frame_id for p in rest]
    assert ids == sorted(set(ids))
    g.close()


def test_get_pose_and_raw_tags():
    st = SimTransport()
    cam = configured_cam()
    cam = Camera(st)
    cam.set_calibration(CAL); cam.set_field(TMAP)
    st.capture(load_rtl_frames(['persp_002'])[0])
    p = cam.get_pose()
    assert p.frame_id == 1 and err(p, 'persp_002')[0] < 10
    raw = cam.get_raw_tags()
    assert raw['frame_id'] == 1 and 1 <= len(raw['tags']) <= 7
    assert all(len(t['corners']) == 4 for t in raw['tags'])


def test_ae_through_host_api_with_sim_frames():
    frames = [dict(load_rtl_frames(['normal_004'])[0], mean=30.0)] * 6
    st = SimTransport(frames)
    cam = Camera(st)
    cam.set_calibration(CAL); cam.set_field(TMAP)
    list(cam.stream(max_frames=6))
    s = cam.get_status()
    assert s.exposure > 100 and s.ae_enabled and abs(s.mean_brightness - 30) < 0.1       # reacted to a dark frame


# ------------------------------------------------------------------------------------------ timeouts
def test_timeout_when_device_silent():
    dead = DeadTransport()
    cam = Camera(dead, timeout=0.05, retries=2)
    t0 = time.monotonic()
    with pytest.raises(CameraTimeout):
        cam.ping()
    dt = time.monotonic() - t0
    assert 0.14 <= dt < 1.5
    assert len(dead.written) == 3 * len(P.encode_frame(P.CMD_PING, b'ping'))      # initial try + 2 retries
    with pytest.raises(TimeoutError):                                               # CameraTimeout is a TimeoutError
        cam.get_status()


def test_transport_errors_propagate():
    st = SimTransport()
    cam = Camera(st)
    st.close()
    with pytest.raises(IOError):
        cam.ping()


def test_serial_loopback_transport():
    pytest.importorskip('serial')
    from apriltag_cam import SerialTransport
    t = SerialTransport('loop://')
    t.write(b'hello')
    got = b''
    for _ in range(100):
        got += t.read(16, 0.01)
        if len(got) >= 5:
            break
    assert got == b'hello' and t.read(4, 0.01) == b''
    t.close()


# ------------------------------------------------------------------------------------------ CLI
def run_cli(capsys, *argv):
    rc = atcam.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_configure_status_stream(tmp_path, capsys):
    state = str(tmp_path / 'flash.bin')
    base = ['--sim', '--sim-state', state]
    rc, out, _ = run_cli(capsys, *base, 'ping')
    assert rc == 0 and '0x41544731' in out
    rc, out, _ = run_cli(capsys, *base, 'configure', '--map', os.path.join(fwutil.ROOT, 'config', 'tag_map.json'),
                         '--calib', os.path.join(fwutil.ROOT, 'config', 'camera_calibration.json'))
    assert rc == 0 and 'configured 12 tags and committed' in out
    rc, out, _ = run_cli(capsys, *base, 'status')
    assert rc == 0 and 'ntags' in out and '12' in out                  # config persisted across CLI invocations (flash file)
    rc, out, _ = run_cli(capsys, *base, '--sim-images', 'normal_004,bright_001', 'stream', '--count', '2', '--json')
    lines = [json.loads(l) for l in out.strip().splitlines()]
    assert rc == 0 and [l['frame_id'] for l in lines] == [1, 2] and lines[0]['ntags'] >= 4
    rc, out, _ = run_cli(capsys, *base, 'config')
    assert rc == 0 and len(json.loads(out)['tags']) == 12
    rc, out, _ = run_cli(capsys, *base, 'exposure', '200', '0x20')
    assert rc == 0
    rc, out, _ = run_cli(capsys, *base, 'ae', 'on')
    assert rc == 0


def test_cli_errors_return_nonzero(capsys):
    rc, out, err_ = run_cli(capsys, '--sim', 'exposure', '0')
    assert rc == 2 and 'RANGE' in err_
    with pytest.raises(SystemExit):
        atcam.main(['ping'])                                           # neither --port nor --sim
