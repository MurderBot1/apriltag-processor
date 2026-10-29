"""CSI-2 packet layer: framing, ECC correction, CRC, bad frames."""
import os, sys, numpy as np, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden

S = rtlutil.SIM


@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_csi2', ['rtl/csi2_rx.v', 'tb/tb_csi2.v'])


def beats_from_packets(packets, gap=6):
    out = []
    for p in packets:
        b = bytes(p) + (b'\x00' if len(p) & 1 else b'')
        for i in range(0, len(b), 2): out.append((1, b[i], b[i + 1]))
        out += [(0, 0, 0)] * gap
    return out


def play(vvp, beats, tag):
    p = f'{S}/{tag}.beats'
    with open(p, 'w') as f:
        for v, a, b in beats: f.write(f'{(v << 16) | (b << 8) | a:05x}\n')
    o = f'{S}/{tag}.log'
    rtlutil.run(vvp, [f'in={p}', f'n={len(beats)}', f'out={o}'])
    return open(o).read().splitlines()


def frame(rng, lines=800, w=1280):
    return rng.integers(0, 256, (lines, w), dtype=np.uint8)


def parse(log):
    pix, ev, stat = [], [], None
    for l in log:
        t = l.split()
        if t[0] == 'P': pix.append(tuple(map(int, t[1:])))
        elif t[0] in ('FS', 'FE'): ev.append(tuple(t))
        elif t[0] == 'STAT': stat = dict(x.split('=') for x in t[1:])
    return pix, ev, stat


def test_ecc_function_properties():
    # all 24 single-bit signatures distinct and non-zero, none equal to a one-hot ECC-bit syndrome
    sigs = [golden.csi2_ecc(1 << i & 0xFF, (1 << i) >> 8) for i in range(24)]
    assert len(set(sigs)) == 24 and 0 not in sigs
    assert all(bin(s).count('1') % 2 == 1 for s in sigs)           # odd-weight columns -> SEC-DED
    import itertools
    singles = set(sigs) | {1 << k for k in range(6)}
    assert not any((sigs[i] ^ sigs[j]) in singles for i, j in itertools.combinations(range(24), 2))
    assert not any((sigs[i] ^ (1 << k)) in singles for i in range(24) for k in range(6))
    assert golden.csi2_short(0x01)[3] == 0x07          # known FE packet: 01 00 00 07


def test_clean_frame(vvp):
    rng = np.random.default_rng(1)
    img = frame(rng)
    log = play(vvp, beats_from_packets(golden.csi2_frame_packets(img)), 'clean')
    pix, ev, stat = parse(log)
    assert ev == [('FS',), ('FE', '1')]
    assert len(pix) == 800 * 640
    got = np.array([(p[2], p[3]) for p in pix], np.uint8).reshape(800, 1280)
    assert (got == img).all()
    firsts = [i for i, p in enumerate(pix) if p[0]]; lasts = [i for i, p in enumerate(pix) if p[1]]
    assert firsts == list(range(0, 800 * 640, 640)) and lasts == [i + 639 for i in firsts]
    assert stat == dict(ecc_corrected='0', ecc_dropped='0', crc_errors='0', frames_bad='0')


def test_single_bit_header_errors_are_corrected(vvp):
    rng = np.random.default_rng(2)
    img = frame(rng, 800)
    pk = golden.csi2_frame_packets(img)
    n_flipped = 0
    for li in (1, 100, 400, 800):                       # flip one header bit in a few lines
        b = bytearray(pk[li]); bit = (li * 7) % 32; b[bit // 8] ^= 1 << (bit % 8); pk[li] = bytes(b); n_flipped += 1
    log = play(vvp, beats_from_packets(pk), 'ecc1')
    pix, ev, stat = parse(log)
    assert ev == [('FS',), ('FE', '1')], ev
    assert len(pix) == 800 * 640
    assert int(stat['ecc_corrected']) == n_flipped and stat['ecc_dropped'] == '0'


def test_double_bit_header_error_drops_line_and_flags_frame(vvp):
    rng = np.random.default_rng(3)
    pk = golden.csi2_frame_packets(frame(rng))
    b = bytearray(pk[50]); b[0] ^= 0x01; b[2] ^= 0x10; pk[50] = bytes(b)      # exactly two flipped bits
    pix, ev, stat = parse(play(vvp, beats_from_packets(pk), 'ecc2'))
    assert ev == [('FS',), ('FE', '0')] and len(pix) == 799 * 640
    assert stat['ecc_dropped'] == '1' and stat['frames_bad'] == '1'


def test_crc_error_flags_frame(vvp):
    rng = np.random.default_rng(4)
    img = frame(rng)
    pk = golden.csi2_frame_packets(img)
    pk[300] = golden.csi2_long(0x2A, img[299].tobytes(), bad_crc=True)
    pix, ev, stat = parse(play(vvp, beats_from_packets(pk), 'crc'))
    assert ev[-1] == ('FE', '0') and stat['crc_errors'] == '1' and stat['frames_bad'] == '1'


def test_missing_line_and_truncated_burst(vvp):
    rng = np.random.default_rng(5)
    img = frame(rng)
    pk = golden.csi2_frame_packets(img)
    del pk[10]
    pix, ev, stat = parse(play(vvp, beats_from_packets(pk), 'missing'))
    assert ev[-1] == ('FE', '0')
    pk = golden.csi2_frame_packets(img)
    pk[20] = pk[20][:600]                                  # burst ends early
    pix, ev, stat = parse(play(vvp, beats_from_packets(pk), 'trunc'))
    assert ev[-1] == ('FE', '0')


def test_recovers_after_bad_frame_and_ignores_other_packet_types(vvp):
    rng = np.random.default_rng(6)
    bad = golden.csi2_frame_packets(frame(rng))
    bad[5] = golden.csi2_long(0x2A, frame(rng, 1)[0].tobytes(), bad_crc=True)
    img = frame(rng)
    good = golden.csi2_frame_packets(img, 1)
    # embedded-data packet (DT 0x12) and line start/end short packets in between must be ignored
    good.insert(3, golden.csi2_long(0x12, bytes(range(16))))
    good.insert(4, golden.csi2_short(0x02, 3)); good.insert(5, golden.csi2_short(0x03, 3))
    pix, ev, stat = parse(play(vvp, beats_from_packets(bad + good), 'recover'))
    assert [e for e in ev if e[0] == 'FE'] == [('FE', '0'), ('FE', '1')]
    assert len(pix) == 800 * 640 * 2
    got = np.array([(p[2], p[3]) for p in pix[800 * 640:]], np.uint8).reshape(800, 1280)
    assert (got == img).all()


def test_back_to_back_lines_minimum_gap(vvp):          # minimum supported separation: 2 idle beats
    rng = np.random.default_rng(7)
    img = frame(rng)
    pix, ev, stat = parse(play(vvp, beats_from_packets(golden.csi2_frame_packets(img), gap=2), 'tight'))
    assert ev == [('FS',), ('FE', '1')] and len(pix) == 800 * 640
