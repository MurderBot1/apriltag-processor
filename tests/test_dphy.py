"""MIPI D-PHY receiver (LVDS DDR gearing, SoT sync hunt, lane deskew, CDC) + CSI-2 layer, bit-level simulation."""
import os, sys, numpy as np, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden, dphy_stream
S = rtlutil.SIM
LINES = 20


@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_dphy', ['rtl/dphy_lane.v', 'rtl/async_fifo.v', 'rtl/dphy_rx.v', 'rtl/csi2_rx.v', 'tb/tb_dphy.v'],
                         top='tb_dphy')


def frame(rng, lines=LINES):
    return rng.integers(0, 256, (lines, 1280), dtype=np.uint8)


def packets(img, fn=0):
    pk = [golden.csi2_short(0x00, fn)]
    pk += [golden.csi2_long(0x2A, img[y].tobytes()) for y in range(img.shape[0])]
    pk += [golden.csi2_short(0x01, fn)]
    return pk


def run(vvp, pk, tag, extra=(), **kw):
    n = dphy_stream.write_lanes(pk, f'{S}/{tag}', **kw)
    out = f'{S}/{tag}.log'
    rtlutil.run(vvp, [f'l0={S}/{tag}.l0.hex', f'l1={S}/{tag}.l1.hex', f'nui={n}', f'out={out}', *extra], timeout=3000)
    pix, ev, stat = [], [], None
    for l in open(out).read().splitlines():
        t = l.split()
        if t[0] == 'P': pix.append((int(t[3]), int(t[4])))
        elif t[0] in ('FS', 'FE'): ev.append(tuple(t))
        elif t[0] == 'STAT': stat = dict(x.split('=') for x in t[1:])
    return pix, ev, stat


@pytest.mark.parametrize('skew', [0, 1, 3, 5, 8, 13, 21])
def test_frame_through_dphy_with_lane_skew(vvp, skew):
    rng = np.random.default_rng(skew)
    img = frame(rng)
    pix, ev, stat = run(vvp, packets(img), f'dp_skew{skew}', skew=skew, rng=np.random.default_rng(100 + skew))
    assert ev == [('FS',), ('FE', '1')], (ev, stat)
    got = np.array(pix, np.uint8).reshape(LINES, 1280)
    assert (got == img).all()
    assert stat['ecc_dropped'] == '0' and stat['crc_errors'] == '0'


def test_clock_ppm_offset_does_not_underrun(vvp):
    rng = np.random.default_rng(7)
    img = frame(rng)
    for per in (9.998, 10.002):                      # +/- 200 ppm core clock vs the sensor byte clock
        pix, ev, stat = run(vvp, packets(img), f'dp_ppm{per}', extra=[f'cperiod={per}'], skew=2, rng=np.random.default_rng(9))
        assert ev == [('FS',), ('FE', '1')], (per, ev, stat)
        assert (np.array(pix, np.uint8).reshape(LINES, 1280) == img).all()


def test_noise_between_bursts_and_slot_jitter(vvp):
    rng = np.random.default_rng(11)
    img = frame(rng)
    pix, ev, stat = run(vvp, packets(img), 'dp_jitter', skew=4, rng=np.random.default_rng(12), jitter_slots=True, lp_ui=500)
    assert ev == [('FS',), ('FE', '1')], (ev, stat)
    assert (np.array(pix, np.uint8).reshape(LINES, 1280) == img).all()


def test_header_bit_error_in_burst_is_corrected_and_recovers(vvp):
    rng = np.random.default_rng(13)
    img = frame(rng)
    pk = packets(img)
    b = bytearray(pk[3]); b[1] ^= 0x04; pk[3] = bytes(b)                  # single bit flip in a long-packet header
    pix, ev, stat = run(vvp, pk, 'dp_ecc', skew=3, rng=np.random.default_rng(14))
    assert ev == [('FS',), ('FE', '1')] and stat['ecc_corrected'] == '1'
    assert (np.array(pix, np.uint8).reshape(LINES, 1280) == img).all()


def test_two_frames_back_to_back(vvp):
    rng = np.random.default_rng(15)
    a, b = frame(rng), frame(rng)
    pix, ev, stat = run(vvp, packets(a, 0) + packets(b, 1), 'dp_two', skew=6, rng=np.random.default_rng(16))
    assert [e for e in ev if e[0] == 'FE'] == [('FE', '1'), ('FE', '1')]
    got = np.array(pix, np.uint8).reshape(2 * LINES, 1280)
    assert (got[:LINES] == a).all() and (got[LINES:] == b).all()


def test_reversed_gearbox_bit_order_still_locks():
    """if the real IDDRX2F presents Q3..Q0 in the opposite time order, the dual-engine lane aligner must still lock"""
    v = rtlutil.build('tb_dphy_rev', ['rtl/dphy_lane.v', 'rtl/async_fifo.v', 'rtl/dphy_rx.v', 'rtl/csi2_rx.v', 'tb/tb_dphy.v'],
                      defines=['GEARREV=1'], top='tb_dphy')
    rng = np.random.default_rng(21)
    img = frame(rng)
    pix, ev, stat = run(v, packets(img), 'dp_rev', skew=5, rng=np.random.default_rng(22))
    assert ev == [('FS',), ('FE', '1')], (ev, stat)
    assert (np.array(pix, np.uint8).reshape(LINES, 1280) == img).all()


def test_core_clock_slower_than_sensor_byte_clock(vvp):
    """The core runs at 85.714 MHz (11.667 ns) while the sensor byte clock is 100 MHz: the 128-deep receive FIFO must absorb
    each 640-beat burst and a full multi-line frame must still arrive intact (line period 8.0 us at the sensor)."""
    rng = np.random.default_rng(31)
    img = frame(rng)
    pix, ev, stat = run(vvp, packets(img), 'dp_slowcore', extra=['cperiod=11.667'], skew=3, rng=np.random.default_rng(32))
    assert ev == [('FS',), ('FE', '1')], (ev, stat)
    assert (np.array(pix, np.uint8).reshape(LINES, 1280) == img).all()
    assert stat['ecc_dropped'] == '0' and stat['crc_errors'] == '0'
