"""Noise-robustness sweep (golden models + TPU ISS, no RTL sim): which pre-filter / threshold variant removes the CCL overflows
on noisy frames without losing tags.  Overflow model = the rtl/run_ccl.v capacity limits (runs/row, labels, candidates)."""
import os, sys, json, cv2, numpy as np
from multiprocessing import Pool
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import golden, tpu_harness, geom
ROOT = geom.ROOT
GT = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
MAXR, NLAB, MAXC = 64, 1024, 64


def ccl_load(mask):
    """(max runs in a row, labels the streaming labeller would allocate)"""
    m = mask.astype(np.int8)
    d = np.diff(np.pad(m, ((0, 0), (1, 1))), axis=1)
    max_runs = int((d == 1).sum(1).max())
    nlab = 1; prev = []
    for y in range(m.shape[0]):
        st = np.nonzero(d[y] == 1)[0]; en = np.nonzero(d[y] == -1)[0] - 1
        cur = list(zip(st, en))
        for s, e in cur:
            if not any(ps <= e and pe >= s for ps, pe in prev):
                nlab += 1
        prev = cur
    return max_runs, nlab


def smooth(img, k):
    if k <= 1:
        return img
    return np.clip(ndimage.uniform_filter(img.astype(np.float32), size=k, mode='nearest') + 0.5, 0, 255).astype(np.uint8)


def pipeline(img, v):
    img = smooth(img, v.get('smooth', 1))
    mask = golden.binarize(img, v.get('diff', 24), v.get('abs', 64))
    if v.get('despeckle', True):
        mask = golden.despeckle(mask)
    return mask


def one(args):
    name, v = args
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    mask = pipeline(img, v)
    runs, nlab = ccl_load(mask)
    ovf = runs > MAXR or nlab >= NLAB
    keep, _, _ = golden.components(mask, min_area=v.get('min_area', 100), min_dim=v.get('min_dim', 10))
    ovf = ovf or len(keep) >= MAXC
    tags = [] if (ovf and not v.get('partial')) else tpu_harness.run_iss(mask, min_area=v.get('min_area', 100), min_dim=v.get('min_dim', 10))[0]
    vis = {int(t) for t, x in GT[name]['tags'].items() if x.get('detectable', x['visible'])}
    ids = {t['id'] for t in tags}
    known = {int(k) for k in GT[name]['tags']}
    return name, GT[name]['category'], len(vis & ids), len(vis), len(ids - known), bool(ovf), runs, nlab


def evaluate(pool, v, names):
    rows = pool.map(one, [(n, v) for n in names], chunksize=4)
    found = sum(r[2] for r in rows); vis = sum(r[3] for r in rows)
    return rows, found, vis, sum(r[4] for r in rows), sum(r[5] for r in rows)


VARIANTS = {
    'baseline': dict(),
    'diff32': dict(diff=32), 'diff48': dict(diff=48), 'diff64': dict(diff=64),
    'smooth2': dict(smooth=2), 'smooth3': dict(smooth=3),
    'smooth3_d32': dict(smooth=3, diff=32), 'smooth2_d32': dict(smooth=2, diff=32),
    'smooth3_d40': dict(smooth=3, diff=40), 'smooth3_d48': dict(smooth=3, diff=48),
}

if __name__ == '__main__':
    names = sorted(GT)
    sel = sys.argv[1:] or list(VARIANTS)
    with Pool(max(1, (os.cpu_count() or 4) - 1)) as p:
        for k in sel:
            rows, f, vis, fp, ov = evaluate(p, VARIANTS[k], names)
            print(f'{k:14s} found {f}/{vis} ({f / vis:.1%})  false {fp}  overflow frames {ov}', flush=True)
