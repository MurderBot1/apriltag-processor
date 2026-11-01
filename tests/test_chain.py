"""System-level tests of cam_core (CSI-2 -> ... -> frame packets on the MCU bus -> C tag unit) at true 120 fps timing: multi-frame streaming,
frame-period accuracy, packet completeness, no drops, bad-CRC frame rejection + recovery, results bit-exact against the golden pipeline,
and a noisy overload frame that must neither hang nor lose the next frame."""
import os, sys, numpy as np, cv2, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import chain, rtlutil, golden, synth_images, tpu_harness
from chain import decode_tags

ROOT = rtlutil.ROOT
FRAME_CLKS = 1041 * 800            # 832,800 clocks @ 100 MHz = 8.328 ms = 120.07 fps


@pytest.fixture(scope='module')
def vvp():
    return chain.build()


def img(name):
    return cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)


def stat_word(st, key): return int(st[key], 16 if key in ('status', 'ecc', 'crc', 'ccl') else 10)


def test_three_frames_back_to_back_at_120fps(vvp):
    frames = [img('normal_004'), img('noise_003'), img('grad_000')]      # (persp_000 / bright_001: RTL and golden pick different tag sets, see docs/verification.md)
    log, res, el = chain.run_frames(vvp, frames, 'sys_three')
    st = res['stats']
    assert 'ID=41544731 VER=00020000' in log and 'REGTEST id_ok=1 scratch=cafef00d' in log      # SPI register read/write path
    assert len(res['results']) == 3, log[-400:]
    assert int(st['total']) == 3 and int(st['processed']) == 3 and int(st['dropped']) == 0
    # frame period: FS-to-FS exactly one sensor frame (832,800 clocks = 120.07 fps)
    assert int(st['fsperiod_min']) == int(st['fsperiod_max']) == FRAME_CLKS, st
    seqs = [r['seq'] for r in res['results']]
    assert seqs == [1, 2, 3]
    assert len(res['packets']) == 3 and all(n == 132128 for _, n, _ in res['packets']), res['packets']       # every packet complete (4+32000+4+1024 words)
    assert all(r['packet']['ok'] and r['packet']['status'] == 0 for r in res['results'])
    assert [r['packet']['seq'] for r in res['results']] == [1, 2, 3]
    ends = [e for _, _, e in res['packets']]
    assert all(b - a > 0 for a, b in zip(ends, ends[1:])) and ends[1] - ends[0] <= FRAME_CLKS + 2000           # one packet per frame period
    # each result set corresponds to its own frame and equals the golden pipeline's tag set
    for f, r in zip(frames, res['results']):
        got = {t['id'] for t in decode_tags(r['words'])}
        want = {t['id'] for t in chain.iss_reference(f, 1)[0]}
        assert got == want and len(got) >= 1, (got, want)
    assert int(st['bad_packets']) == 0 and int(st['stream'], 16) == 0       # no aborted packets, no FIFO overflow


def test_result_matches_golden_pipeline_bit_exact_corners(vvp):
    f = img('shadow_001')
    log, res, el = chain.run_frames(vvp, [f], 'sys_exact')
    got = {t['id']: t for t in decode_tags(res['results'][0]['words'])}
    ref = {t['id']: t for t in chain.iss_reference(f, 1)[0]}
    assert set(got) == set(ref) and got
    for i in got:                                      # candidate tie-break may differ by a pixel -> corners within 0.05 px
        assert np.abs(got[i]['corners'] - ref[i]['corners']).max() < 0.05, i


def test_lowcon_frame_with_ratio_register_bit_exact(vvp):
    """lowcon regression (0/66 on the chip with the reset value).  The tile 'contrasty' test 2*diff >= max rejects every tile of a frame whose
    contrast is compressed to 24 % (black ~69, white ~167: diff 62..98 < max/2).  THRESH bits 31:30 select 3*diff, 4*diff or no ratio test.
    The lowest-contrast frame must give the golden tag set with ratio=2 (and none with the reset value)."""
    f = img('lowcon_009')
    ref = {t['id']: t for t in chain.iss_reference(f, 1, ratio=2)[0]}
    assert len(ref) >= 4
    assert not chain.iss_reference(f, 1)[0]                    # reset value: golden finds nothing either
    log, res, el = chain.run_frames(vvp, [f], 'sys_lowcon', thr=chain.thr_word(ratio=2))
    got = {t['id']: t for t in decode_tags(res['results'][0]['words'])}
    assert set(got) == set(ref), (set(got), set(ref))
    for i in got:
        assert np.abs(got[i]['corners'] - ref[i]['corners']).max() < 0.05, i


def test_bad_crc_frame_is_flagged_and_next_frame_recovers(vvp):
    """the FPGA has no frame store to retract a frame: the packet leaves with the CSI-bad flag set, the MCU discards it; the next frame is clean"""
    frames = [img('normal_004'), img('noise_003')]
    log, res, el = chain.run_frames(vvp, frames, 'sys_badcrc', bad_crc_lines={(0, 100)}, maxcyc=12_000_000)
    st = res['stats']
    assert int(st['total']) == 2
    assert len(res['results']) == 2 and all(n == 132128 for _, n, _ in res['packets'])
    assert res['results'][0]['packet']['status'] & 1 and not res['results'][1]['packet']['status'] & 0x1F       # CSI-bad on frame 0 only
    assert int(st['crc'], 16) & 0xFFFF == 1 and (int(st['crc'], 16) >> 16) == 1       # crc_errors=1, frames_bad=1
    assert len(decode_tags(res['results'][1]['words'])) >= 1


def test_missing_line_frame_is_flagged_complete_packet_and_next_frame_recovers(vvp):
    frames = [img('normal_004'), img('normal_004')]
    log, res, el = chain.run_frames(vvp, frames, 'sys_dropline', drop_lines={(0, 300)}, maxcyc=12_000_000)
    assert int(res['stats']['crc'], 16) >> 16 == 1
    assert [n for _, n, _ in res['packets']] == [132128, 132128], res['packets']           # the short mask is zero padded: the packet length never changes
    p0, p1 = res['results'][0]['packet'], res['results'][1]['packet']
    assert p0['status'] & 1 and p0['status'] & 8, p0['status']                              # CSI bad + mask shorter than 800 rows
    assert p1['status'] == 0 and len(decode_tags(res['results'][1]['words'])) >= 1


def test_noisy_overload_frame_does_not_hang_and_next_frame_is_clean(vvp):
    rng = np.random.default_rng(0)
    noisy = np.clip(rng.normal(90, 40, (800, 1280)), 0, 255).astype(np.uint8)      # pure high-contrast noise
    good = img('normal_004')
    log, res, el = chain.run_frames(vvp, [noisy, good], 'sys_noise')
    assert len(res['results']) == 2, log[-500:]
    fl = (int(res['stats']['ccl'], 16) >> 8) & 15
    assert fl == 0, 'second frame must run clean after an overload frame'            # flags are per frame (latest)
    want = {t['id'] for t in chain.iss_reference(good, 1)[0]}
    assert {t['id'] for t in decode_tags(res['results'][1]['words'])} == want


def test_dark_overloaded_frame_still_reports_tags(vvp):
    log, res, el = chain.run_frames(vvp, [img('dark_004')], 'sys_darkc')
    assert len(res['results']) == 1
    assert len(decode_tags(res['results'][0]['words'])) >= 2
