"""Automatic tile contrast-ratio selection (firmware/core/atratio.c) driven through the real firmware with simulated frame feedback."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from fwutil import Dev, P, simfw   # noqa: E402
import auto_ratio_sim as sim        # noqa: E402

TAG = [(17, [[100.0, 100.0], [160.0, 100.0], [160.0, 160.0], [100.0, 160.0]], 0)]
ROW_DROPPED = 1


def reg_ratio(d):
    return d.fpga.regs.get(simfw.REG_THRESH, sim.THRESH_RESET) >> 30


def frames(d, n, tags=(), flags=0):
    """Process n frames with the given detections / CCL flags; returns the register ratio after each."""
    out = []
    for _ in range(n):
        d.fpga.publish(list(tags), ccl_flags=flags)
        assert d.fw.poll()
        out.append(reg_ratio(d))
    d.drain()
    return out


def status(d):
    return P.decode_status(d.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))


@pytest.fixture
def dev():
    d = Dev()
    d.ok(P.CMD_SET_AE, b'\x00')
    return d


def test_default_is_auto_with_ratio_zero(dev):
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (0, True)
    assert dev.fpga.regs.get(simfw.REG_THRESH) is None        # nothing written until the policy changes the ratio


def test_tags_present_never_switch(dev):
    assert set(frames(dev, 200, TAG)) == {0}
    assert set(frames(dev, 50, TAG, flags=ROW_DROPPED | 8)) == {0}


def test_zero_tag_frames_switch_to_ratio_one_after_three(dev):
    assert frames(dev, 4) == [0, 0, 1, 1]
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (1, True)


def test_interrupted_zero_run_does_not_switch(dev):
    for _ in range(20):
        assert frames(dev, 2) == [0, 0]
        assert frames(dev, 1, TAG) == [0]


def test_switch_keeps_other_threshold_fields(dev):
    dev.ok(P.CMD_SET_TRACK, bytes([30, 50, 8, 3]))
    frames(dev, 3)
    assert dev.fpga.regs[simfw.REG_THRESH] == 30 | 50 << 8 | 8 << 16 | 3 << 24 | 1 << 30


def test_confirmed_ratio_one_stays_with_tags(dev):
    frames(dev, 3)
    assert set(frames(dev, 100, TAG)) == {1}


def test_row_dropped_at_ratio_one_falls_back_and_locks_out(dev):
    frames(dev, 3)
    assert reg_ratio(dev) == 1
    assert frames(dev, 1, TAG, flags=ROW_DROPPED) == [0]
    # locked out for AT_AR_LOCK_MIN = 32 frames even though no tags are found: ratio 1 again in the 32nd frame after the failure
    r = frames(dev, 32)
    assert r[:31] == [0] * 31 and r[31] == 1, r
    # the second failure doubles the lockout (64)
    assert frames(dev, 1, TAG, flags=ROW_DROPPED) == [0]
    r = frames(dev, 64)
    assert r[:63] == [0] * 63 and r[63] == 1, r


def test_flag_other_than_row_dropped_is_ignored(dev):
    frames(dev, 3)
    assert set(frames(dev, 30, TAG, flags=2 | 4 | 8)) == {1}


def test_unconfirmed_trial_without_tags_gives_up(dev):
    r = frames(dev, 12)
    assert r[2] == 1 and r[7] == 1 and r[8] == 0, r        # switched after 3 frames, back after 6 more tagless frames at ratio 1
    assert 1 not in r[8:], r                           # locked out afterwards


def test_confirmed_ratio_one_returns_when_scene_empty(dev):
    frames(dev, 3)
    frames(dev, 10, TAG)
    r = frames(dev, 6)
    assert r[-1] == 0, r


def test_empty_scene_flap_is_bounded(dev):
    r = frames(dev, 2000)
    changes = sum(1 for a, b in zip(r, r[1:]) if a != b)
    assert changes <= 2 * (2000 // 32 + 1)
    assert changes < 40, changes


def test_explicit_ratio_disables_auto(dev):
    dev.ok(P.CMD_SET_TRACK, bytes([24, 64, 10, 2 | 2 << 6]))
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (2, False)
    assert set(frames(dev, 50)) == {2}
    assert dev.fpga.regs[simfw.REG_THRESH] >> 30 == 2


def test_set_track_ratio_zero_keeps_auto_and_current_ratio(dev):
    frames(dev, 3)
    dev.ok(P.CMD_SET_TRACK, bytes([24, 64, 10, 2]))
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (1, True)


def test_set_auto_ratio_off_fixes_ratio_zero(dev):
    frames(dev, 3)
    assert reg_ratio(dev) == 1
    dev.ok(P.CMD_SET_AUTO_RATIO, b'\x00')
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (0, False)
    assert set(frames(dev, 50)) == {0}


def test_set_auto_ratio_on_again_after_explicit(dev):
    dev.ok(P.CMD_SET_TRACK, bytes([24, 64, 10, 2 | 3 << 6]))
    dev.ok(P.CMD_SET_AUTO_RATIO, b'\x01')
    s = status(dev)
    assert (s.ratio, s.auto_ratio) == (0, True)
    assert frames(dev, 3) == [0, 0, 1]


def test_set_auto_ratio_errors(dev):
    assert dev.nak(P.CMD_SET_AUTO_RATIO, b'') == P.ERR_BAD_LEN
    assert dev.nak(P.CMD_SET_AUTO_RATIO, b'\x01\x01') == P.ERR_BAD_LEN
    assert dev.nak(P.CMD_SET_AUTO_RATIO, b'\x02') == P.ERR_RANGE


def test_damaged_frames_do_not_feed_the_policy(dev):
    for _ in range(10):
        dev.fpga.publish([], status=0x01)          # CSI error: rejected before the tag unit
        dev.fw.poll()
    assert reg_ratio(dev) == 0


# ------------------------------------------------------------------------------------------ simulated dataset sequences
@pytest.fixture(scope='module')
def dataset():
    return sim.load()


@pytest.mark.parametrize('lat', [1, 2, 3])
def test_auto_never_below_ratio_zero_per_category_and_recovers_lowcon(dataset, lat):
    gt, res = dataset
    cats = sorted({g['category'] for g in gt.values()})
    for c in cats:
        names = sorted(n for n, g in gt.items() if g['category'] == c) * 4
        r0 = sim.run_sequence(names, gt, res, lat, 0)
        ra = sim.run_sequence(names, gt, res, lat, 'auto')
        assert ra['found'] >= r0['found'], (c, ra['found'], r0['found'])
        if c == 'lowcon':
            assert r0['found'] == 0
            assert ra['found'] >= 0.9 * ra['vis'] * (len(names) - 3 - lat - 1) / len(names)
            assert ra['ratios'].index(1) == 3 + lat - 1       # three tagless frames + register latency
        else:
            assert sum(ra['ratios']) == 0, c              # categories that already work never leave ratio 0


def test_mixed_sequence_recovers_after_noise(dataset):
    gt, res = dataset
    by = lambda c: sorted(n for n, g in gt.items() if g['category'] == c)
    names = by('noise') + by('lowcon') + by('noise')
    ra = sim.run_sequence(names, gt, res, 2, 'auto')
    r0 = sim.run_sequence(names, gt, res, 2, 0)
    assert ra['found'] > r0['found']
