#!/usr/bin/env py -3.12
"""Run the chip's RTL in Icarus Verilog for short, meaningful scenarios and write the waveform data for the site.

    py -3.12 site/sim/gen_sim.py            # all scenarios (about a minute)
    py -3.12 site/sim/gen_sim.py csi2_clean tpu_tag

Output: site/simout/waves.js  (window.WAVES = [...scenarios...]), loaded by site/assets/sim.js.
Testbenches live in site/sim/tb/ (adapted copies of tb/*.v with $dump statements; the DUT RTL is unmodified).
Simulations run in site/sim/work/ and the big intermediates are deleted at the end.
"""
import os, sys, json, re, shutil, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import simlib, vcd_to_json
from simlib import WORK, ROOT, build, run, tb
import golden, dphy_stream, tpu_harness
from PIL import Image

OUT = os.path.join(os.path.dirname(HERE), 'simout')
SCEN = []          # finished scenario dicts
KEEP_VCD = False


def W(name):
    return os.path.join(WORK, name)


def beats_of(packets, gap=4):
    out = []
    for p in packets:
        b = bytes(p) + (b'\x00' if len(p) & 1 else b'')
        for i in range(0, len(b), 2):
            out.append((1 << 16) | (b[i + 1] << 8) | b[i]) if True else None
        out += [0] * gap
    return out


def sig(src, group, fmt='h', desc='', names=None, default=True, label=None):
    return dict(src=src, name=label or src, group=group, fmt=fmt, desc=desc, names=names or {}, default=default)


def finish(sc, vcd, sigs, marks=(), squeeze=200):
    d = vcd_to_json.convert(vcd, sigs, squeeze_gap_ns=squeeze, marks=list(marks))
    sc['tmax'] = d['tmax']; sc['breaks'] = d['breaks']; sc['marks'] = d['marks']
    sc['signals'] = [dict(name=s['name'], w=s['w'], group=s['group'], fmt=s['fmt'], desc=s['desc'],
                          names={str(k): v for k, v in s['names'].items()}, on=s['default'], ch=s['ch']) for s in d['signals']]
    sc['vcd_bytes'] = os.path.getsize(vcd)
    SCEN.append(sc)
    n = sum(len(s['ch']) // 2 for s in sc['signals'])
    print('  %-14s %d signals, %d changes, %.0f ns, vcd %d B' % (sc['id'], len(sc['signals']), n, d['tmax'], sc['vcd_bytes']))


# ------------------------------------------------------------------------------------------------- CSI-2
CSI_STATES = {0: 'IDLE', 1: 'HDR1', 2: 'PAY', 3: 'CRC', 4: 'DROP', 5: 'HDR2'}


def csi2_sigs():
    return [
        sig('hs_valid', 'D-PHY side input', 'b', 'high during an HS burst (from the D-PHY receiver)'),
        sig('lane0', 'D-PHY side input', 'h', 'byte on lane 0 (even bytes of the packet)'),
        sig('lane1', 'D-PHY side input', 'h', 'byte on lane 1 (odd bytes of the packet)'),
        sig('state', 'packet FSM', 'd', 'csi2_rx state machine', CSI_STATES),
        sig('hdr_di', 'header', 'h', 'captured data identifier byte (VC[7:6] | data type[5:0]); 0x00 = frame start, 0x01 = frame end, 0x2A = RAW8 line'),
        sig('hdr_wc0', 'header', 'h', 'word count low byte (payload bytes) / frame number'),
        sig('hdr_wc1', 'header', 'h', 'word count high byte'),
        sig('hdr_ecc', 'header', 'h', 'ECC byte received in the header'),
        sig('ecc_syndrome', 'header', 'h', 'computed ECC xor received ECC; 0 = good, non-zero single-bit pattern = corrected'),
        sig('hdr_ok', 'header', 'b', 'header ECC matched exactly'),
        sig('hdr_1bit', 'header', 'b', 'single-bit header error, being corrected'),
        sig('beats_left', 'payload', 'd', 'payload beats (2 bytes) still to come in this line'),
        sig('crc_run', 'payload', 'h', 'running CRC-16 (init 0xFFFF), compared with the 2 CRC bytes after the payload'),
        sig('pix_valid', 'video out (2 px / clock)', 'b', 'output beat valid'),
        sig('pix0', 'video out (2 px / clock)', 'd', 'even pixel'),
        sig('pix1', 'video out (2 px / clock)', 'd', 'odd pixel'),
        sig('line_first', 'video out (2 px / clock)', 'b'),
        sig('line_last', 'video out (2 px / clock)', 'b'),
        sig('fs', 'frame events', 'b', 'frame-start pulse'),
        sig('fe', 'frame events', 'b', 'frame-end pulse (frame_ok is valid with it)'),
        sig('frame_ok', 'frame events', 'b', 'frame had exactly LINES good lines'),
        sig('line_count', 'frame events', 'd', 'good lines counted in this frame'),
        sig('frame_err', 'frame events', 'b', 'a line in this frame was bad'),
        sig('ecc_corrected', 'statistics', 'd', 'single-bit header errors corrected so far'),
        sig('ecc_dropped', 'statistics', 'd', 'packets dropped for uncorrectable header'),
        sig('crc_errors', 'statistics', 'd', 'payload CRC mismatches'),
        sig('frames_bad', 'statistics', 'd', 'frames flagged bad'),
        sig('clk', 'clock', 'b', 'core clock (10 ns here; 11.67 ns on the real chip)', default=False),
    ]


def scen_csi2():
    img = (np.arange(48).reshape(3, 16) * 5 + 20).astype(np.uint8)       # 3 lines x 16 px ramp
    marks = [dict(sig='fs', label='frame start'), dict(sig='fe', label='frame end (frame_ok=%d)' if False else 'frame end', max=2),
             dict(sig='line_first', label='line start', max=4), dict(sig='ecc_corrected', label='ECC corrected', edge='any', max=1)]
    v = build('csi2', ['rtl/csi2_rx.v', tb('tb_csi2_wave.v')])
    # (a) clean frame
    pk = [golden.csi2_short(0x00, 5)] + [golden.csi2_long(0x2A, img[y].tobytes()) for y in range(3)] + [golden.csi2_short(0x01, 5)]
    bt = beats_of(pk)
    open(W('csi_a.hex'), 'w').write('\n'.join('%05x' % x for x in bt) + '\n')
    log = run(v, ['in=csi_a.hex', 'n=%d' % len(bt), 'vcd=csi_a.vcd'])
    sc = dict(id='csi2_clean', group='CSI-2 packet layer', title='CSI-2 receive: frame start, 3 lines, frame end',
              desc='csi2_rx fed a tiny RAW8 frame (3 lines x 16 pixels, frame number 5) as the D-PHY receiver would deliver it: two bytes per clock '
                   '(lane0 = even bytes, lane1 = odd bytes). Each packet is a 4-byte header (data id, word count, ECC) followed, for lines, by the payload and a CRC-16. '
                   'Watch the FSM (state) walk IDLE - HDR1 - HDR2 - PAY - CRC, pix_valid/pix0/pix1 emit two pixels per clock, and fs / fe / frame_ok pulse at the frame boundaries.',
              steps=['Header: lane0/lane1 carry DI, WC0 | WC1, ECC. hdr_ok goes high when the ECC syndrome is 0.',
                     'Payload: beats_left counts down from 8 (16 px / 2), crc_run accumulates the CRC-16.',
                     'After the last payload beat the two CRC bytes are compared; line_count increments.',
                     'FE packet: frame_ok = 1 because exactly LINES=3 good lines were seen.'],
              module='csi2_rx.v', tb='site/sim/tb/tb_csi2_wave.v (from tb/tb_csi2.v)')
    finish(sc, W('csi_a.vcd'), csi2_sigs(), marks)
    # check
    # (b) with a 1-bit header error and a CRC error
    pk = [golden.csi2_short(0x00, 6)] + [golden.csi2_long(0x2A, img[y].tobytes()) for y in range(3)] + [golden.csi2_short(0x01, 6)]
    b = bytearray(pk[2]); b[1] ^= 0x04; pk[2] = bytes(b)                                  # line 1: one flipped header bit (WC), correctable
    pk[3] = golden.csi2_long(0x2A, img[2].tobytes(), bad_crc=True)                        # line 2: bad CRC
    bt = beats_of(pk)
    open(W('csi_b.hex'), 'w').write('\n'.join('%05x' % x for x in bt) + '\n')
    run(v, ['in=csi_b.hex', 'n=%d' % len(bt), 'vcd=csi_b.vcd'])
    sc = dict(id='csi2_errors', group='CSI-2 packet layer', title='CSI-2 receive: corrected header bit and a CRC error',
              desc='Same frame, but line 1 has one flipped bit in its header (the SEC-DED ECC corrects it: hdr_1bit, ecc_syndrome != 0, ecc_corrected becomes 1 and the line still decodes) '
                   'and line 2 has a corrupted payload CRC (crc_errors becomes 1, the frame is flagged bad: frame_ok = 0 at the frame-end packet, frames_bad = 1).',
              steps=['Line 1: ecc_syndrome is a non-zero single-bit pattern, hdr_ok = 0, hdr_1bit = 1; the corrected word count is used.',
                     'Line 2: the CRC compare fails in state CRC -> crc_errors and frame_err go high.',
                     'FE: frame_ok = 0 and frames_bad increments; downstream logic discards the frame.'],
              module='csi2_rx.v', tb='site/sim/tb/tb_csi2_wave.v (from tb/tb_csi2.v)')
    finish(sc, W('csi_b.vcd'), csi2_sigs(), marks + [dict(sig='frame_err', label='frame flagged bad', max=1), dict(sig='crc_errors', label='CRC error', edge='any', max=1)])


# ------------------------------------------------------------------------------------------------- D-PHY
def scen_dphy():
    img = (np.arange(32).reshape(2, 16) * 7 + 30).astype(np.uint8)
    pk = [golden.csi2_short(0x00, 1)] + [golden.csi2_long(0x2A, img[y].tobytes()) for y in range(2)] + [golden.csi2_short(0x01, 1)]
    n = dphy_stream.write_lanes(pk, W('dp'), skew=2, rng=np.random.default_rng(3))
    v = build('dphy', ['rtl/dphy_lane.v', 'rtl/async_fifo.v', 'rtl/dphy_rx.v', 'rtl/csi2_rx.v', tb('tb_dphy_wave.v')])
    out = run(v, ['l0=dp.l0.hex', 'l1=dp.l1.hex', 'nui=%d' % n, 'vcd=dp.vcd', 'w0=0', 'w1=1', 'w2=3'])
    g = 'D-PHY lanes (400 MHz DDR, 1.25 ns / bit)'
    sigs = [
        sig('clk_lane', g, 'b', 'sensor clock lane: 400 MHz DDR, one edge per bit; the data eye is centred on each edge'),
        sig('data_lane0', g, 'b', 'serial data lane 0 (LP noise, HS-zero, sync byte 0xB8, packet bytes LSB first)'),
        sig('data_lane1', g, 'b', 'serial data lane 1 (delayed by 2 UI relative to lane 0 in this run)'),
        sig('sclk', 'receiver (rx.*)', 'b', 'divided clock after the DDR input gearing'),
        sig('gear_q0', 'receiver (rx.*)', 'h', '4 bits per sclk, lane 0 (after 4:1 DDR gearing)'),
        sig('gear_q1', 'receiver (rx.*)', 'h', '4 bits per sclk, lane 1'),
        sig('lane_locked', 'receiver (rx.*)', 'b', 'per-lane flag: sync pattern found (3 zero bytes + 0xB8 at any bit alignment)'),
        sig('byte_valid', 'receiver (rx.*)', 'b', 'per-lane byte-aligned data valid'),
        sig('byte_l0', 'receiver (rx.*)', 'h', 'byte-aligned data, lane 0 (before the deskew FIFO)'),
        sig('byte_l1', 'receiver (rx.*)', 'h', 'byte-aligned data, lane 1'),
        sig('fifo_empty', 'receiver (rx.*)', 'b', 'async FIFO empty flags (clock-domain crossing and 2-lane deskew)'),
        sig('resyncs', 'receiver (rx.*)', 'd', 'resync counter'),
        sig('rx_status', 'receiver (rx.*)', 'b', '{lane1 locked, lane0 locked, resync lsb, clock seen}', default=False),
        sig('core_clock', 'core clock domain', 'b', 'core clock'),
        sig('hs_valid', 'core clock domain', 'b', 'HS burst in progress, in the core clock domain'),
        sig('lane0', 'core clock domain', 'h', 'deskewed byte, lane 0'),
        sig('lane1', 'core clock domain', 'h', 'deskewed byte, lane 1'),
        sig('csi_state', 'core clock domain', 'd', 'csi2_rx FSM', CSI_STATES),
        sig('pix_valid', 'video out', 'b'),
        sig('pix0', 'video out', 'd'), sig('pix1', 'video out', 'd'),
        sig('line_first', 'video out', 'b'), sig('line_last', 'video out', 'b'),
        sig('line_count', 'video out', 'd'), sig('frame_ok', 'video out', 'b'),
        sig('ecc_corrected', 'statistics', 'd', default=False), sig('ecc_dropped', 'statistics', 'd', default=False),
        sig('crc_errors', 'statistics', 'd', default=False), sig('frames_bad', 'statistics', 'd', default=False),
    ]
    sc = dict(id='dphy_burst', group='D-PHY receive', title='D-PHY receive: serial lanes to pixels (frame start, line 0, frame end)',
              desc='A bit-level model of the sensor link: a 400 MHz DDR clock lane and two data lanes (1.25 ns per bit), driven into dphy_rx -> csi2_rx exactly as in tb/tb_dphy.v. '
                   'Lane 1 is skewed by 2 bits to show deskew. Three packet bursts are shown (frame start, first line, frame end); the quiet time between them is cut out (grey gaps). '
                   'Zoom in on the first burst to see the HS-zero run followed by the sync byte 0xB8, then the bytes appear on byte_l0/byte_l1 (aligned) and, a little later, on lane0/lane1 in the core clock domain.',
              steps=['Wide view: zoom out to see the three burst windows; zoom into a burst to see single bits on data_lane0/1 against clk_lane edges.',
                     'After the sync byte the receiver reports lane_locked and byte_valid; gear_q0/q1 carry 4 bits per sclk.',
                     'The async FIFO moves bytes into the core clock domain (hs_valid, lane0, lane1) and csi2_rx decodes them like the first scenario.',
                     'In the last window frame_ok = 1 after the frame-end packet: both lines were received intact through the whole analog-side path.'],
              module='dphy_rx.v', tb='site/sim/tb/tb_dphy_wave.v (from tb/tb_dphy.v)')
    finish(sc, W('dp.vcd'), sigs, [dict(sig='lane_locked', label='lane locked', edge='any', max=6), dict(sig='frame_ok', label='frame_ok', max=2)], squeeze=300)


# ------------------------------------------------------------------------------------------------- threshold
def load_img(name):
    return np.array(Image.open(os.path.join(ROOT, 'test_images', 'sensor', name + '.png')).convert('L'))


def scen_thresh(name='normal_000'):
    img = load_img(name)
    m = golden.binarize(img)
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images'][name]
    # a row through the middle of the largest visible tag, window across its left border
    best = max((t for t in gt['tags'].values() if t['visible']), key=lambda t: t['px_width'])
    c = np.array(best['corners']); cx, cy = c.mean(axis=0)
    y = int(round(cy)) | 1 if False else int(round(cy))
    row = m[y]
    xs = np.nonzero(np.diff(row.astype(np.int8)) != 0)[0]
    x0 = int(min(c[:, 0])) - 10
    wc0 = max(0, x0 // 2 - 6); wc1 = wc0 + 72
    img.tofile(W('img.raw'))
    v = build('thresh', ['rtl/thresh_binarize.v', tb('tb_thresh_wave.v')])
    t = time.time()
    out = run(v, ['img=img.raw', 'vcd=th.vcd', 'wy=%d' % y, 'wc0=%d' % wc0, 'wc1=%d' % wc1])
    print('  thresh sim %.0fs' % (time.time() - t), out.strip().splitlines()[-1] if out.strip() else '')
    g = 'Output stage (row %d)' % y
    sigs = [
        sig('in_valid', 'sensor stream in (row %d + 17)' % y, 'b', 'incoming pixel beat; the ring buffer holds the newest 32 rows, output lags the input by 17 rows'),
        sig('in_pix0', 'sensor stream in (row %d + 17)' % y, 'd'), sig('in_pix1', 'sensor stream in (row %d + 17)' % y, 'd'),
        sig('s2_valid', g, 'b', 'delayed-pixel pipeline stage valid'),
        sig('delayed_pix0', g, 'd', 'even pixel read back from the 17-row delay ring'),
        sig('delayed_pix1', g, 'd', 'odd pixel read back from the ring'),
        sig('tile_thr', g, 'd', 'tile threshold = (min + max)/2 over the 3x3 tile neighbourhood (8x8-pixel tiles)'),
        sig('tile_contrasty', g, 'b', 'tile neighbourhood has enough contrast (diff >= 24 and 2*diff >= max); otherwise the absolute black level (64) is used'),
        sig('out_valid', 'binary stream out', 'b'),
        sig('out_row', 'binary stream out', 'd'),
        sig('out_beat', 'binary stream out', 'd', 'beat index within the row (2 pixels per beat)'),
        sig('out_black0', 'binary stream out', 'b', 'even pixel is black (pixel <= threshold)'),
        sig('out_black1', 'binary stream out', 'b'),
        sig('out_first', 'binary stream out', 'b', default=False), sig('out_last', 'binary stream out', 'b', default=False),
    ]
    sc = dict(id='thresh_tile', group='Threshold / binarize', title='Adaptive threshold across a tag border (%s, row %d)' % (name, y),
              desc='thresh_binarize on a real rendered frame (%s, 1280x800) at 120 fps line timing; only output row %d, beats %d..%d (pixels x=%d..%d) are dumped. '
                   'This window crosses the left border of the largest tag. out_black0/out_black1 follow the pixel against tile_thr: where tile_contrasty is high the tile is classified with (min+max)/2, '
                   'otherwise with the fixed black level. The threshold changes every 4 beats (one 8-pixel tile).' % (name, y, wc0, wc1, 2 * wc0, 2 * wc1),
              steps=['delayed_pix0/1 are the grey values leaving the 17-row ring; tile_thr is looked up for the tile containing the pixel.',
                     'out_black = 1 when pixel <= tile_thr (contrasty tile). Cross-check: the RTL output was compared with tools/golden.py on the full frame (see pipeline page).',
                     'Note in_pix0/in_pix1 is a different row (y+17): the input side runs 17 rows ahead of the output.'],
              module='thresh_binarize.v', tb='site/sim/tb/tb_thresh_wave.v (from tb/tb_thresh.v)')
    finish(sc, W('th.vcd'), sigs, [dict(sig='tile_contrasty', label='contrasty tile', edge='any', max=3)], squeeze=300)
    # consistency of dumped data with golden: black decision for dumped beats
    s = {q['name']: q for q in SCEN[-1]['signals']}
    return y


# ------------------------------------------------------------------------------------------------- despeckle
def find_speckle(names=('noise_000', 'dark_000', 'normal_000', 'clutter_000', 'persp_000', 'blur_000')):
    for n in names:
        img = load_img(n)
        m = golden.binarize(img)
        d = golden.despeckle(m)
        diff = np.argwhere(m != d)
        for y, x in diff:
            if 8 <= y < 780 and 20 <= x < 1250:
                # prefer places with a nearby real feature (a black neighbourhood) so the crop is not only isolated dots
                crop = m[y - 5:y + 7, x - 16:x + 16]
                if crop.sum() > 40 and (crop != d[y - 5:y + 7, x - 16:x + 16]).sum() >= 2:
                    return n, y, x
    for n in names:
        img = load_img(n)
        m = golden.binarize(img); d = golden.despeckle(m)
        diff = np.argwhere(m != d)
        for y, x in diff:
            if 8 <= y < 780 and 20 <= x < 1250:
                return n, y, x
    return None


def scen_despeckle():
    f = find_speckle()
    assert f, 'no speckle found'
    name, y, x = f
    m = golden.binarize(load_img(name))
    x0 = (x - 16) // 2 * 2; y0 = y - 5
    crop = m[y0:y0 + 12, x0:x0 + 32]
    exp = golden.despeckle(crop)
    open(W('mask.hex'), 'w').write('\n'.join('%02x' % v for v in crop.astype(np.uint8).reshape(-1)) + '\n')
    v = build('despeckle', ['rtl/despeckle.v', tb('tb_despeckle_wave.v')])
    out = run(v, ['mask=mask.hex', 'vcd=ds.vcd'])
    got = np.zeros((12, 32), bool)
    for l in open(W('despeckle_out.txt')).read().split('\n'):
        if l.strip():
            r, cc, a, b = map(int, l.split()); got[r, 2 * cc] = a; got[r, 2 * cc + 1] = b
    ok = bool((got == exp).all())
    print('  despeckle RTL == golden on crop:', ok)
    assert ok
    ndiff = int((crop != exp).sum())
    ascii_in = '\n'.join(''.join('#' if p else '.' for p in r) for r in crop)
    ascii_out = '\n'.join(''.join('#' if p else '.' for p in r) for r in exp)
    g = 'stream in'
    sigs = [
        sig('in_valid', g, 'b'), sig('in_black0', g, 'b', 'incoming even pixel (1 = black)'), sig('in_black1', g, 'b'),
        sig('in_row', g, 'd', 'row being streamed in (row r is produced while r+1 arrives)'), sig('in_beat', g, 'd', 'beat (column pair) index'),
        sig('win_prev_row', '3x3 window', 'b', '2-bit {odd,even} pixel pair of the previous row at the window column'),
        sig('win_this_row', '3x3 window', 'b'), sig('win_next_row', '3x3 window', 'b'),
        sig('sum_px0', '3x3 window', 'd', 'black pixels in the 3x3 window around the even pixel (>= 4 -> output black)'),
        sig('sum_px1', '3x3 window', 'd', 'same for the odd pixel'),
        sig('out_valid', 'stream out', 'b'), sig('out_row', 'stream out', 'd'),
        sig('out_black0', 'stream out', 'b', 'despeckled even pixel'), sig('out_black1', 'stream out', 'b'),
        sig('out_first', 'stream out', 'b', default=False), sig('out_last', 'stream out', 'b', default=False), sig('out_frame_end', 'stream out', 'b', default=False),
        sig('in_frame_start', g, 'b', default=False),
    ]
    sc = dict(id='despeckle_tile', group='Despeckle', title='Despeckle: 3x3 majority filter on a 32x12 crop of %s' % name,
              desc='despeckle (COLS=16 beats, ROWS=12) on a 32x12 pixel crop of the real thresholded mask of %s around (x=%d, y=%d), where the filter removes %d pixel(s) (isolated speckle) and fills holes. '
                   'Each output pixel is black iff at least 4 of the 9 pixels in its 3x3 neighbourhood (including itself) are black; sum_px0/sum_px1 show those counts. '
                   'The RTL output equals tools/golden.py despeckle() on this crop. Input crop (# = black):\n%s\nOutput:\n%s' % (name, x, y, ndiff, ascii_in, ascii_out),
              steps=['A row is produced one row late, while the next row streams in (so the window has three rows).',
                     'Isolated black pixels have sum 1 -> output 0; solid black regions keep sums >= 4.',
                     'Compare in_black0/1 with out_black0/1 one row later: the differing beats are the speckle removed.'],
              module='despeckle.v', tb='site/sim/tb/tb_despeckle_wave.v (from tb/tb_despeckle.v)', pre=True)
    finish(sc, W('ds.vcd'), sigs, [dict(sig='out_first', label='output row start', max=12)], squeeze=300)


# ------------------------------------------------------------------------------------------------- CCL
def ccl_mask():
    m = np.zeros((40, 64), bool)
    m[4:30, 4:10] = True; m[4:30, 20:26] = True; m[24:30, 4:26] = True       # U shape: two arms joined at the bottom (merge)
    m[8:30, 40:58] = True                                                     # solid block
    m[34:36, 36:38] = True                                                    # 2x2 speckle (below min area)
    return m


def scen_ccl():
    m = ccl_mask()
    open(W('cclmask.hex'), 'w').write('\n'.join('%02x' % v for v in m.astype(np.uint8).reshape(-1)) + '\n')
    v = build('ccl', ['rtl/run_ccl.v', tb('tb_ccl_wave.v')])
    out = run(v, ['mask=cclmask.hex', 'vcd=ccl.vcd'])
    lines = open(W('ccl_out.txt')).read().split()
    n = int(lines[0]); words = [int(x, 16) for x in lines[1:]]
    recs = [words[16 * i:16 * i + 16] for i in range(n)]
    keep, lab, allc = golden.components(m, min_area=40, min_dim=6, reject_border=False)
    gold = sorted((c['area'], c['x0'], c['y0'], c['x1'], c['y1']) for c in keep)
    rtl = sorted((r[0], r[10] & 0xFFFF, r[11] & 0xFFFF, r[10] >> 16, r[11] >> 16) for r in recs)
    print('  ccl RTL candidates', rtl, 'golden', gold, rtl == gold)
    assert rtl == gold
    cands = ['label %d: area %d, bbox x %d..%d, y %d..%d' % (r[9], r[0], r[10] & 0xFFFF, r[10] >> 16, r[11] & 0xFFFF, r[11] >> 16) for r in recs]
    st = simlib.localparams('rtl/run_ccl.v', 'S_')
    names = {v_: k[2:] for k, v_ in st.items()}
    g1, g2, g3 = 'binary stream in', 'labelling sequencer', 'candidate output'
    sigs = [
        sig('frame_start', g1, 'b'), sig('in_valid', g1, 'b'), sig('in_black0', g1, 'b', 'even pixel is black'), sig('in_black1', g1, 'b'),
        sig('in_row_first', g1, 'b'), sig('in_row_last', g1, 'b'), sig('frame_end', g1, 'b'),
        sig('seq_state', g2, 'd', 'run-labelling state machine; the S_U_* states are union-find merges (the U-shape arms joining)', names),
        sig('labelling_row', g2, 'd', 'row being labelled (runs of the previous row are compared against it)'),
        sig('runs_in_row', g2, 'd', 'number of runs found in the row being labelled'), sig('runs_in_prev_row', g2, 'd'), sig('cur_run_index', g2, 'd', 'index of the run the walker is working on'),
        sig('cur_run_start', g2, 'd', 'x of the first pixel of the current run'), sig('cur_run_end', g2, 'd'),
        sig('prev_run_start', g2, 'd', 'head of the previous-row run FIFO: start x'), sig('prev_run_end', g2, 'd'),
        sig('cur_label_w', g2, 'd', 'label of the current run'), sig('prev_label', g2, 'd', 'label of the overlapping previous-row run (follows parent links while hopping to its root)'),
        sig('root_label', g2, 'd', 'root label found by the termination check'),
        sig('labels_allocated', g2, 'd', 'next free label (labels allocated so far + 1)'),
        sig('stats_idle_w', g2, 'b', 'statistics pipeline drained (unions and terminations wait for it)', default=False),
        sig('cand_write', g3, 'b', 'candidate RAM write'), sig('cand_addr', g3, 'h', '{candidate index[5:0], word[3:0]}'),
        sig('cand_data', g3, 'h', 'record words: area, 8 directional extremes, label, bbox'),
        sig('cand_total', g3, 'd'), sig('frame_done', g3, 'b'), sig('ccl_flags', g3, 'b'), sig('worst_row_clocks', g3, 'd', 'worst per-row labelling time in clocks'),
        sig('clk', 'clock', 'b', default=False),
    ]
    sc = dict(id='ccl_labels', group='Connected components', title='Connected-components labelling: a U shape (merge), a block and a speckle',
              desc='run_ccl on a 64x40 binary frame at 150 clocks per line: a U-shaped component (two separate arms that are first labelled as different components, then merged where the bottom bar joins them), '
                   'a solid 18x22 block, and a 2x2 speckle that is dropped (area < 40). Black runs are captured per row; the sequencer then labels each run against the previous row '
                   '(S_CMP merge-walk, S_FSET/S_FW/S_FU follow parent links to the root), allocates new labels or merges two roots (S_U0..S_UB3). When a component has no run in the current row it is finished by the termination check (S_T, S_TF*, S_TR*, S_TC*, S_TOP) and, after the frame end, the surviving candidates are written out as 16-word records (S_EM*, S_WR; cand_write). '
                   'The RTL candidates equal tools/golden.py components(): ' + '; '.join(cands) + '.',
              steps=['Rows 4..23: the arms are separate runs and get separate labels (labels_allocated rises).',
                     'Row 24: the bottom bar overlaps both arms: the S_U* states perform the union; one root label survives.',
                     'Termination and frame end: finished components are filtered (area, size) and the survivors are written as 16-word records (cand_data); cand_total = 2.'],
              module='run_ccl.v', tb='site/sim/tb/tb_ccl_wave.v (from tb/tb_ccl.v)')
    finish(sc, W('ccl.vcd'), sigs, [dict(sig='in_row_first', label='row start', max=0), dict(sig='cand_write', label='candidate word', max=1), dict(sig='frame_done', label='done', max=1)], squeeze=600)


# ------------------------------------------------------------------------------------------------- TPU
def scen_tpu(name='normal_000'):
    import tpu_prog
    from tpu_isa import s32
    img = load_img(name)
    mask = golden.binarize_clean(img)
    tags, mach, nc = tpu_harness.run_iss(mask, frame_id=1)
    t0 = min(tags, key=lambda t: t['area'])                       # the smallest decoded tag: shortest run
    keep, lab, allc = golden.components(mask)
    ci = [i for i, c in enumerate(keep) if c['label'] == t0['label']][0]
    words = golden.pack_records(keep, lab)
    rec = words[16 * ci:16 * ci + 16]
    cand = rec + [0] * (1024 - len(rec))
    fb = mask.astype(np.uint8).reshape(800, 40, 32)
    fbw = (fb.astype(np.uint64) << np.arange(32, dtype=np.uint64)).sum(axis=2).reshape(-1).astype(np.uint32)
    open(W('cand.hex'), 'w').write('\n'.join('%08x' % (x & 0xFFFFFFFF) for x in cand) + '\n')
    open(W('fb.hex'), 'w').write('\n'.join('%08x' % x for x in fbw) + '\n')
    prog, asm = tpu_prog.program()
    code = asm.link()
    hexp = W('tpu_prog.hex')
    open(hexp, 'w').write('\n'.join('%08x' % w for w in code) + '\n')
    repo_hex = open(os.path.join(ROOT, 'ref', 'tpu', 'tpu_prog.hex')).read().split()
    same = repo_hex[:len(code)] == ['%08x' % w for w in code]
    print('  ref/tpu/tpu_prog.hex == assembled program:', same)
    taghex = os.path.join(ROOT, 'ref', 'tpu', 'tag36h11.hex')
    v = build('tpu', ['ref/tpu/tpu_core.v', tb('tb_tpu_wave.v')], params=['PROG="%s"' % hexp.replace('\\', '/')])
    # TAG_HEX is a tpu_core parameter: patch through a defparam-free route -> run with cwd=ROOT-independent copy
    shutil.copy(taghex, W('tag36h11.hex'))
    os.makedirs(W('ref/tpu'), exist_ok=True); shutil.copy(taghex, W('ref/tpu/tag36h11.hex'))
    t = time.time()
    out = run(v, ['cand=cand.hex', 'fb=fb.hex', 'n=1', 'vcd=tpu.vcd', 'frame=1'], timeout=3000)
    print('  tpu sim %.0fs:' % (time.time() - t), out.strip().splitlines()[-1])
    res = [int(x, 16) for x in open(W('tpu_res.txt')).read().split()]
    rt = tpu_harness.parse_results(res)
    exp = tpu_harness.run_iss(mask, frame_id=1)[0]
    exp1 = [t for t in exp if t['label'] == t0['label']]
    ok = len(rt) == 1 and exp1 and rt[0]['id'] == exp1[0]['id'] and np.allclose(rt[0]['corners'], exp1[0]['corners'], atol=1 / 65536.0)
    print('  TPU RTL result matches ISS:', ok, rt[0]['id'], rt[0]['rot'], rt[0]['ham'])
    assert ok
    cycles = int(re.search(r'cycles=(\d+)', out).group(1))
    ops = simlib.localparams('ref/tpu/tpu_core.v')
    opnames = {}
    txt = open(os.path.join(ROOT, 'ref', 'tpu', 'tpu_core.v')).read()
    blk = re.search(r'localparam \[5:0\]\s*(.*?);', txt, re.S).group(1)
    for nm, val in re.findall(r'(\w+)=(\d+)', blk):
        opnames[int(val)] = nm
    states = {v_: k[2:] for k, v_ in simlib.localparams('ref/tpu/tpu_core.v', 'S_').items()}
    inv = {}
    for k, a in asm.labels.items():
        inv.setdefault(a, k)
    pcnames = {}
    cur, off = None, 0
    for i, w in enumerate(code):
        if i in inv: cur, off = inv[i], 0
        pcnames[i] = '%s+%d  %s' % (cur or '?', off, asm.src[i] or opnames.get(w >> 26, '?')); off += 1
    g1, g2, g3, g4 = 'sequencer', 'registers', 'memories', 'result'
    sigs = [
        sig('tpu_start', g1, 'b'), sig('tpu_busy', g1, 'b'), sig('tpu_done', g1, 'b'),
        sig('pc', g1, 'd', 'program counter = word index in the baked 574-word instruction ROM. Hover/cursor shows label+offset and mnemonic.', pcnames),
        sig('fsm_state', g1, 'd', 'internal FSM: FETCH/FD (ROM read), RD (register read), EXEC, MUL, DIV, MEMW, PIX*, TAG* ...', states),
        sig('opcode', g1, 'd', 'opcode of the current instruction', opnames),
        sig('instr', g1, 'h', 'current 32-bit instruction word'),
        sig('operand_A', g2, 'd', 'operand A latched from the register file', ), sig('operand_B', g2, 'd'),
        sig('r1', g2, 'd', 'register r1 (Q16.16 fixed point / integer depending on the phase)'), sig('r2', g2, 'd'), sig('r3', g2, 'd'), sig('r4', g2, 'd'),
        sig('r5', g2, 'd', default=False), sig('r6', g2, 'd', default=False),
        sig('r20', g2, 'd', 'candidate count', default=False), sig('r21', g2, 'd', 'candidate index', default=False),
        sig('r22', g2, 'd', 'tags written', default=False), sig('r23', g2, 'd', 'result record base word', default=False),
        sig('cand_read_addr', g3, 'd', 'candidate RAM read address'), sig('cand_read_data', g3, 'h', 'candidate record word (area, extremes, ...)'),
        sig('frame_word_addr', g3, 'd', 'binary-frame RAM address: y*40 + x/32'), sig('frame_word', g3, 'h', '32 binary pixels of that word'),
        sig('result_we', g4, 'b'), sig('result_addr', g4, 'd', 'result RAM word address (16 + 16*i = record i)'),
        sig('result_data', g4, 'h', 'w0 = 0x80000000 | ham<<12 | rot<<10 | id; w1..w8 = corners Q16.16; w9 label; w10 area; w11 frame; w12 quad area'),
        sig('clocks', g4, 'd', 'cycle counter since start'),
        sig('clk', 'clock', 'b', default=False),
    ]
    corners = ', '.join('(%.2f, %.2f)' % tuple(c) for c in rt[0]['corners'])
    sc = dict(id='tpu_tag', group='Tag unit (reference RTL)', title='Reference TPU RTL running its baked program on one tag (%s, tag id %d)' % (name, rt[0]['id']),
              desc='Architecture A3 runs the tag unit as C code on the RP2350 (firmware/core/attpu.c, a bit-exact port); this scenario simulates the former FPGA processor ref/tpu/tpu_core.v, which is the reference that port is checked against and is no longer in the FPGA. tpu_core executes the baked 574-instruction program (coarse quad from the 8 candidate extremes -> sub-pixel edge refinement on the binary frame -> homography -> 6x6 sampling -> TAGMATCH against the 587-code ROM) '
                   'for the smallest candidate of %s: component label %d, area %d. The full run is %d clocks (%.1f us at 85.7 MHz); three windows are dumped: start-up (candidate load, first instructions), '
                   'the first TAGMATCH (ROM scan), and the result write-back. Result (matches the Python ISS bit-exactly): tag id %d, rotation %d, hamming distance %d, corners %s.'
                   % (name, t0['label'], t0['area'], cycles, cycles / 85.714, rt[0]['id'], rt[0]['rot'], rt[0]['ham'], corners),
              steps=['Start-up: cand_read_addr/data load the candidate; pc advances 2 clocks per simple instruction (FETCH -> FD -> RD -> EXEC), longer for MUL, DIV and PIX.',
                     'pc names show where in the program you are (e.g. coarse+3, refine..., decode...), opcode shows the mnemonic.',
                     'frame_word_addr/frame_word show the binary-pixel fetches used by the edge refinement and the 6x6 sampling.',
                     'End: result_we pulses 16 times writing the record; result_data w0 contains the tag id, rotation and hamming distance.'],
              module='tpu_core.v', tb='site/sim/tb/tb_tpu_wave.v (from tb/tb_tpu.v)',
              result=dict(id=rt[0]['id'], rot=rt[0]['rot'], ham=rt[0]['ham'], corners=[[round(float(a), 3), round(float(b), 3)] for a, b in rt[0]['corners']], cycles=cycles, image=name, program_words=len(code), matches_repo_hex=same))
    finish(sc, W('tpu.vcd'), sigs, [dict(sig='tpu_start', label='start', max=1), dict(sig='result_we', label='result write', max=2), dict(sig='tpu_done', label='done', max=1)], squeeze=300)


# ------------------------------------------------------------------------------------------------- mask streamer
def scen_mstream():
    v = build('mstream', ['rtl/mask_stream.v', tb('tb_mstream_wave.v')])
    t = time.time()
    out = run(v, ['frames=1'], timeout=3000)
    print('  mstream sim %.0fs:' % (time.time() - t), out.strip().splitlines()[-1] if out.strip() else '')
    assert 'PASS' in out, out[-500:]
    g1, g2, g3, g4 = 'binary stream in (from despeckle)', 'candidates in (from run_ccl)', 'packet state', 'MCU frame bus out'
    names = {0: 'IDLE', 1: 'HDR', 2: 'MASK', 3: 'WAIT', 4: 'TRL', 5: 'CAND'}
    sigs = [
        sig('frame_start_in', g1, 'b', 'd_fs: pulse shortly before the first beat of the frame'), sig('in_valid', g1, 'b', 'beat valid (640 beats per 686-clock line)'),
        sig('in_black0', g1, 'b'), sig('in_black1', g1, 'b'), sig('in_row_last', g1, 'b', default=False), sig('frame_end_in', g1, 'b', default=False),
        sig('cand_write', g2, 'b', 'run_ccl writes the candidate RAM'), sig('labeller_done', g2, 'b', 'run_ccl finished: the streamer may send the trailer and the candidate list'), sig('labeller_count', g2, 'd'),
        sig('pkt_state', g3, 'd', 'packet writer: HDR (4 words), MASK (32,000 words), WAIT (for run_ccl), TRL (4 words), CAND (1024 words)', names),
        sig('word_index', g3, 'd', 'word counter inside the current section'), sig('fifo_fill', g3, 'd', '16-word FIFO between the packer and the bus transmitter'),
        sig('mcu_fs', g4, 'b', 'high for the whole packet'), sig('mcu_clk', g4, 'b', 'strobe: high for 2 of the 4 clocks of a byte slot; the RP2350 samples mcu_d on the rising edge'),
        sig('mcu_d', g4, 'h', 'byte, changes one clock before the strobe rises, little-endian words'),
        sig('streamer_busy', g4, 'b', default=False), sig('pkt_done', g4, 'b', 'pulse when the packet is fully sent'),
        sig('clk', 'clock', 'b', default=False),
    ]
    sc = dict(id='mask_stream', group='Mask streamer', title='mask_stream: one frame packet to the MCU (header, mask, trailer, candidates)',
              desc='rtl/mask_stream.v with the stimulus of tb/tb_mstream.v: one frame of 800 rows x 640 beats at the real 686-clock line timing, a pseudo-random binary pattern (not a real image; the point is the protocol), 7 candidate records, followed by the full self-check of all 132,128 bytes of the packet (the testbench printed PASS). '
                   'Architecture A3 has no frame store in the FPGA: the mask leaves at the pixel rate, one byte per 4 core clocks, over the 8-bit bus that the RP2350 captures with a PIO state machine and DMA. '
                   'Only short windows are dumped: the frame start, the 16-byte header and first mask words, the last mask words, the wait for run_ccl, the trailer and the first candidate words.',
              steps=['mcu_fs rises, then HDR sends the magic 0x4D335441 ("AT3M"), the sequence number and the device time, one byte per strobe.',
                     'MASK: 40 words per row; fifo_fill shows the packer running ahead of the transmitter.',
                     'WAIT ends when run_ccl pulses labeller_done; TRL sends candidate count, flags, frame sum, max row clocks and ~sequence; CAND sends the 1024-word record RAM; pkt_done ends the packet.'],
              module='mask_stream.v', tb='site/sim/tb/tb_mstream_wave.v (from tb/tb_mstream.v)')
    finish(sc, W('ms.vcd'), sigs, [dict(sig='mcu_fs', label='packet start/end', edge='any', max=4), dict(sig='labeller_done', label='labeller done', max=2)], squeeze=300)


SCENARIOS = {'csi2': scen_csi2, 'dphy': scen_dphy, 'thresh': scen_thresh, 'despeckle': scen_despeckle, 'ccl': scen_ccl, 'mstream': scen_mstream, 'tpu': scen_tpu}


def main():
    sel = sys.argv[1:] or list(SCENARIOS)
    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    for k in sel:
        print('scenario group', k)
        SCENARIOS[k]()
    if sys.argv[1:]:        # partial run: merge with existing
        p = os.path.join(OUT, 'waves.js')
        if os.path.exists(p):
            old = json.loads(open(p).read()[len('window.WAVES='):-1])
            new_ids = {s['id'] for s in SCEN}
            SCEN[:0] = [s for s in old if s['id'] not in new_ids]
    order = ['CSI-2 packet layer', 'D-PHY receive', 'Threshold / binarize', 'Despeckle', 'Connected components', 'Mask streamer', 'Tag unit (reference RTL)']
    SCEN.sort(key=lambda s: order.index(s['group']))
    js = 'window.WAVES=' + json.dumps(SCEN, separators=(',', ':')) + ';'
    open(os.path.join(OUT, 'waves.js'), 'w').write(js)
    print('waves.js %.0f KB' % (len(js) / 1e3))
    if not KEEP_VCD:
        for f in os.listdir(WORK):
            fp = os.path.join(WORK, f)
            if f.endswith(('.vcd', '.raw', '.vvp', '.hex')) and os.path.isfile(fp):
                os.remove(fp)
        shutil.rmtree(os.path.join(WORK, 'rtl'), ignore_errors=True)


if __name__ == '__main__':
    main()
