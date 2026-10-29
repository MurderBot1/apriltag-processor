"""RTL run_ccl vs golden connected components on adversarial synthetic binary images."""
import os, sys, numpy as np, cv2, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden, ccl_check
S = rtlutil.SIM


@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_ccl', ['rtl/run_ccl.v', 'tb/tb_ccl.v'])


def run_mask(vvp, m, tag, m2=None, minarea=1, mindim=1, rej=0, maxarea=4000000):
    p = os.path.join(S, f'{tag}.mask'); m.astype(np.uint8).tofile(p)
    args = [f'mask={p}', f'out={S}/{tag}.cand', f'minarea={minarea}', f'mindim={mindim}', f'rej={rej}', f'maxarea={maxarea}']
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
