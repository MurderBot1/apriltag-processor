"""RTL run_ccl vs golden connected components on adversarial synthetic binary images."""
import os, sys, numpy as np, cv2, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden, ccl_check
S = rtlutil.SIM


@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_ccl', ['rtl/run_ccl.v', 'tb/tb_ccl.v'])


def run_mask(vvp, m, tag, m2=None, minarea=1, mindim=1, rej=0, maxarea=4000000, line=None):
    p = os.path.join(S, f'{tag}.mask'); m.astype(np.uint8).tofile(p)
    args = [f'mask={p}', f'out={S}/{tag}.cand', f'minarea={minarea}', f'mindim={mindim}', f'rej={rej}', f'maxarea={maxarea}']
    if line: args.append(f'line={line}')
    if m2 is not None:
        p2 = os.path.join(S, f'{tag}_2.mask'); m2.astype(np.uint8).tofile(p2)
        args += [f'mask2={p2}', f'out2={S}/{tag}_2.cand']
    return rtlutil.run(vvp, args)


def check(vvp, m, tag, **kw):
    out = run_mask(vvp, m, tag, **kw)
    keep, lab, allc = golden.components(m, min_area=1, min_dim=1, reject_border=False)
    recs = ccl_check.parse_dump(os.path.join(S, f'{tag}.cand'))
    assert 'flags=0000' in out, out
    errs = ccl_check.compare(recs, keep, lab)
    assert not errs, errs[:5]
    return out


def shapes(seed, n=35):
    rng = np.random.default_rng(seed)
    m = np.zeros((800, 1280), np.uint8)
    cells = [(r, c) for r in range(5) for c in range(8)]
    rng.shuffle(cells)
    for (r, c) in cells[:n]:
        cy, cx = 80 + r * 150 + int(rng.integers(-20, 20)), 80 + c * 150 + int(rng.integers(-20, 20))
        k = int(rng.integers(0, 6))
        if k == 0: cv2.rectangle(m, (cx - 30, cy - 20), (cx + 30, cy + 25), 1, -1)
        elif k == 1: cv2.ellipse(m, (cx, cy), (int(rng.integers(5, 50)), int(rng.integers(5, 50))), int(rng.integers(0, 180)), 0, 360, 1, -1)
        elif k == 2: cv2.circle(m, (cx, cy), 35, 1, 6)
        elif k == 3:
            cv2.rectangle(m, (cx - 30, cy - 30), (cx - 20, cy + 30), 1, -1)
            cv2.rectangle(m, (cx + 20, cy - 30), (cx + 30, cy + 30), 1, -1)
            cv2.rectangle(m, (cx - 30, cy + 20), (cx + 30, cy + 30), 1, -1)
        elif k == 4:
            pts = np.array([[cx + int(t * np.cos(t * 1.5)), cy + int(t * np.sin(t * 1.5))] for t in np.linspace(1, 25, 200)])
            cv2.polylines(m, [pts.astype(np.int32)], False, 1, 3)
        else: cv2.line(m, (cx - 40, cy - 40), (cx + 40, cy + 38), 1, 2)
    return m


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_random_shapes(vvp, seed):
    check(vvp, shapes(seed), f'shapes{seed}')


def test_comb_merges(vvp):
    m = np.zeros((800, 1280), np.uint8)
    for k in range(25): m[100:300, 100 + k * 8:104 + k * 8] = 1     # 25 teeth joined at the bottom -> 24 unions
    m[296:310, 100:300] = 1
    m[400:420, 0:1280] = 1                                           # full-width row
    m[500:510, 1270:1280] = 1                                        # right edge
    m[790:800, 600:700] = 1                                          # bottom edge
    m[0:3, 10:20] = 1                                                # top edge
    check(vvp, m, 'comb')


def test_odd_pixel_patterns(vvp):
    m = np.zeros((800, 1280), np.uint8)
    for (y, x) in [(5, 0), (5, 1), (7, 1279), (9, 1278), (11, 640), (13, 3), (200, 1279), (799, 0), (799, 1279)]:
        m[y, x] = 1
    for i in range(40): m[300 + i, 400 + i] = 1                      # diagonal: 40 separate comps
    for i in range(30): m[600 + i, 800 + i] = 1; m[600 + i, 801 + i] = 1   # staircase: one comp
    m[100, 1000:1010] = 1; m[101, 1009:1020] = 1                     # overlap by exactly one column
    m[120, 1000:1010] = 1; m[121, 1010:1020] = 1                     # diagonal touch only -> separate
    check(vvp, m, 'odd')


def test_all_black_and_empty(vvp):
    m = np.ones((800, 1280), np.uint8)
    run_mask(vvp, m, 'allblack')
    recs = ccl_check.parse_dump(os.path.join(S, 'allblack.cand'))
    assert len(recs) == 1 and recs[0]['area'] == 1280 * 800
    assert (recs[0]['x0'], recs[0]['x1'], recs[0]['y0'], recs[0]['y1']) == (0, 1279, 0, 799)
    run_mask(vvp, np.zeros((800, 1280), np.uint8), 'empty')
    assert ccl_check.parse_dump(os.path.join(S, 'empty.cand')) == []


def test_overflow_flags_and_recovery(vvp):
    chk = np.indices((800, 1280)).sum(0) % 2                          # checkerboard: 640 runs per row
    good = shapes(9, 20)
    out = run_mask(vvp, chk, 'chk', m2=good)
    lines = [l for l in out.splitlines() if l.startswith('RESULT')]
    assert len(lines) == 2, out
    f1 = lines[0].split('flags=')[1][:4]; f2 = lines[1].split('flags=')[1][:4]
    assert f1 != '0000', 'overflow must be reported'
    assert f2 == '0000', 'next frame must recover cleanly'
    keep, lab, allc = golden.components(good, min_area=1, min_dim=1, reject_border=False)
    errs = ccl_check.compare(ccl_check.parse_dump(os.path.join(S, 'chk_2.cand')), keep, lab)
    assert not errs, errs[:3]


def test_row_budget_on_realistic_density(vvp):
    out = run_mask(vvp, shapes(5, 40), 'budget')
    mrc = int(out.split('max_row_cycles=')[1].split()[0])
    assert mrc < 700, mrc


# ---------------------------------------------------------------- capacity / noise robustness (run_ccl: MAXR 256, label recycling, top-64 by area)
def rtl_result(out, n=0):
    l = [x for x in out.splitlines() if x.startswith('RESULT')][n]
    import re
    d = dict(re.findall(r'(\w+)=(\S+)', l))
    return dict(done=int(d['done']), count=int(d['count']), flags=d['flags'], max_row=int(d['max_row_cycles']),
                dropped=int(d['rows_dropped']), labels=int(d['labels_used']))


def topn_check(vvp, m, tag, maxc=64, min_area=1, min_dim=1, nlab=1024, line=None, **kw):
    """RTL candidate table == streaming model (same order) and every RTL record is an exact golden component"""
    out = run_mask(vvp, m, tag, minarea=min_area, mindim=min_dim, line=line, **kw)
    recs = ccl_check.parse_dump(os.path.join(S, f'{tag}.cand'))
    cands, info = golden.stream_components(m.astype(bool), min_area=min_area, min_dim=min_dim, reject_border=False, nlab=nlab, max_cand=maxc)
    assert [r['area'] for r in recs] == [c['area'] for c in cands], (len(recs), len(cands))
    assert all(tuple(r['scores']) == tuple(c['scores']) for r, c in zip(recs, cands))
    return out, recs, cands, info


def test_row_with_200_runs(vvp):
    m = np.zeros((800, 1280), np.uint8)
    for k in range(200):                                              # 200 bars (2 px wide, pitch 4) of different heights: 200 runs on the busiest rows
        m[100:100 + 20 + k % 37 + k // 37 * 3, 4 * k + 10:4 * k + 12] = 1
    out, recs, cands, info = topn_check(vvp, m, 'runs200')
    r = rtl_result(out)
    assert r['flags'][-2] == '0' and info['runs'] > 200 * 20             # no run overflow with 200 runs per row
    # top-64 by area of the full golden decomposition (areas 2*h are not all distinct, compare the area multiset)
    keep, lab, allc = golden.components(m, min_area=1, min_dim=1, reject_border=False)
    top = sorted((c['area'] for c in keep), reverse=True)[:64]
    assert sorted((r['area'] for r in recs), reverse=True) == top
    assert r['count'] == 64 and r['flags'][0] == '1'                    # candidate table full: diagnostic bit only
    assert rtl_result(out)['done'] == 1


def test_label_recycling_3000_dots_then_a_tag(vvp):
    m = np.zeros((800, 1280), np.uint8)
    for yy in range(2, 2 + 4 * 19, 4):
        for xx in range(4, 4 + 8 * 160, 8): m[yy, xx] = 1                # 3040 one-pixel components (no neighbours)
    m[300:340, 400:440] = 1; m[310:330, 410:430] = 0                     # a real ring (area 1200 - 400)
    out, recs, cands, info = topn_check(vvp, m, 'dots3000', min_area=10, min_dim=1)
    r = rtl_result(out)
    assert info['labels_allocated'] >= 3040 and info['peak_labels'] < 400  # recycling is what keeps the 1024-entry table sufficient
    assert r['flags'][1] == '0', 'label table must not overflow'
    assert r['count'] == 1 and recs[0]['area'] == 40 * 40 - 20 * 20
    assert r['labels'] < 400                                             # label high-water mark of the RTL
    keep, lab, allc = golden.components(m, min_area=10, min_dim=1, reject_border=False)
    assert not ccl_check.compare(recs, keep, lab)


def test_100_components_keep_the_64_largest(vvp):
    m = np.zeros((800, 1280), np.uint8)
    for k in range(100):
        r_, c_ = divmod(k, 10)
        m[20 + r_ * 78:20 + r_ * 78 + 30, 10 + c_ * 125:10 + c_ * 125 + 12 + k] = 1     # area 30*(12+k): all distinct
    out, recs, cands, info = topn_check(vvp, m, 'big100')
    r = rtl_result(out)
    assert r['count'] == 64 and r['flags'][0] == '1' and r['flags'][1:] == '000'
    assert sorted(x['area'] for x in recs) == [30 * (12 + k) for k in range(36, 100)]
    keep, lab, allc = golden.components(m, min_area=1, min_dim=1, reject_border=False)
    top = [c for c in keep if c['area'] >= 30 * (12 + 36)]
    assert not ccl_check.compare(recs, top, lab)


def test_every_resource_overflows_and_the_frame_still_completes(vvp):
    m = np.zeros((800, 1280), np.uint8)
    m[0:60] = (np.indices((60, 1280)).sum(0) % 2)                        # checkerboard: 640 runs/row (> 256), thousands of 1-px components
    for yy in range(70, 70 + 4 * 19, 4):
        for xx in range(4, 4 + 8 * 160, 8): m[yy, xx] = 1                # 3040 dots
    for k in range(100):
        r_, c_ = divmod(k, 10)
        m[160 + r_ * 60:160 + r_ * 60 + 25, 10 + c_ * 125:10 + c_ * 125 + 12 + k] = 1
    m[700:740, 600:640] = 1; m[710:730, 610:630] = 0                     # a tag-sized ring, found among the 64 largest
    out, recs, cands, info = topn_check(vvp, m, 'allovf', min_area=100, min_dim=10)
    r = rtl_result(out)
    assert r['done'] == 1 and r['count'] > 0
    assert r['flags'][2] == '1' and r['flags'][0] == '1'                 # run overflow and candidate overflow reported (as diagnostics)
    assert any(x['area'] == 1200 for x in recs) or any(x['area'] >= 25 * 12 for x in recs)


def test_label_table_exhaustion_loses_components_not_the_frame():
    """small label table (16 entries): the runs that find no label stay background; model and RTL agree, frame completes"""
    v = rtlutil.build('tb_ccl_small', ['rtl/run_ccl.v', 'tb/tb_ccl.v'], defines=['P_NLAB=16', 'P_LB=4'])
    m = np.zeros((800, 1280), np.uint8)
    for k in range(40): m[100:140, 20 + k * 30:30 + k * 30] = 1          # 40 simultaneously live components
    m[300:330, 100:130] = 1                                              # one more, after the bars finished -> labelled again
    out, recs, cands, info = topn_check(v, m, 'smalltab', nlab=16)
    r = rtl_result(out)
    assert r['done'] == 1 and r['flags'][1] == '1' and info['flags']['ovf_lab'] == 1
    assert len(recs) == 16                                              # 15 bars labelled + the late one
    assert any(x['area'] == 900 for x in recs)


def test_realtime_line_timing_busy_rows(vvp):
    """200-run rows at the real 686-clock line period: nothing dropped, row sequencer keeps up"""
    m = np.zeros((800, 1280), np.uint8)
    for k in range(200): m[50:300 + 2 * k, 4 * k + 10:4 * k + 12] = 1     # 200 long vertical bars ending on different rows: ~200 runs on every line
    out, recs, cands, info = topn_check(vvp, m, 'rt686', line=686)
    r = rtl_result(out)
    assert r['dropped'] == 0 and r['max_row'] < 686, r
