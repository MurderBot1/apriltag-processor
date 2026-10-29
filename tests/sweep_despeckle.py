"""Compare speckle suppression options for the binary image: run stats + ISS detection over the whole dataset."""
import os, sys, json, cv2, numpy as np
from multiprocessing import Pool
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import golden, tpu_harness, geom
ROOT = geom.ROOT
GT = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']


def majority(m, k=5):
    s = ndimage.convolve(m.astype(np.int32), np.ones((3, 3), np.int32), mode='constant')
    return s >= k


def binarize_frac(img, frac_num, frac_den, diff_min=24, abs_black=64):
    """like golden.binarize but black = p <= nmin + (nmax-nmin)*num/den (threshold below the midpoint)"""
    p = img.astype(np.int32)
    b = (p[0::2, 0::2] + p[0::2, 1::2] + p[1::2, 0::2] + p[1::2, 1::2] + 2) >> 2
    t = b.reshape(100, 4, 160, 4)
    nmin = ndimage.minimum_filter(t.min(axis=(1, 3)), size=3, mode='nearest')
    nmax = ndimage.maximum_filter(t.max(axis=(1, 3)), size=3, mode='nearest')
    diff = nmax - nmin
    hi = (diff >= diff_min) & (2 * diff >= nmax)
    thr = nmin + (diff * frac_num) // frac_den
    return np.where(np.kron(hi, np.ones((8, 8), bool)), p <= np.kron(thr, np.ones((8, 8), np.int32)), p < abs_black)


def variant(img, v):
    if v == 'base': return golden.binarize(img)
    if v == 'maj5': return majority(golden.binarize(img), 5)
    if v == 'maj4': return majority(golden.binarize(img), 4)
    if v.startswith('keep'):
        k = int(v[4:]); b = golden.binarize(img)
        c = ndimage.convolve(b.astype(np.int32), np.ones((3, 3), np.int32), mode='constant')
        return b & (c >= k)
    if v.startswith('kadd'):
        k, a = [int(x) for x in v[4:].split('_')]; b = golden.binarize(img)
        c = ndimage.convolve(b.astype(np.int32), np.ones((3, 3), np.int32), mode='constant')
        return (b & (c >= k)) | (c >= a)
    if v == 'thr40': return binarize_frac(img, 2, 5)
    if v == 'thr40+maj5': return majority(binarize_frac(img, 2, 5), 5)
    if v == 'thr37': return binarize_frac(img, 3, 8)


def one(args):
    name, v = args
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    m = variant(img, v)
    rr = [int(np.count_nonzero(np.diff(np.concatenate([[0], r.astype(np.int8), [0]])) == 1)) for r in m]
    _, lab, allc = golden.components(m, min_area=1, min_dim=1, reject_border=False)
    tags, mach, nc = tpu_harness.run_iss(m)
    vis = {int(t) for t, g in GT[name]['tags'].items() if g['visible']}
    ids = {t['id'] for t in tags}
    errs = [np.linalg.norm(t['corners'] - np.array(GT[name]['tags'][str(t['id'])]['corners']), axis=1).max()
            for t in tags if str(t['id']) in GT[name]['tags'] and GT[name]['tags'][str(t['id'])]['visible']]
    return dict(found=len(vis & ids), vis=len(vis), spurious=len(ids - {int(k) for k in GT[name]['tags']}), comps=len(allc),
                maxruns=max(rr), over=sum(1 for x in rr if x > 64), errs=errs)


if __name__ == '__main__':
    names = sorted(GT)
    with Pool(12) as p:
        for v in sys.argv[1:] or ['base', 'maj5', 'maj4', 'thr40', 'thr40+maj5', 'thr37']:
            r = p.map(one, [(n, v) for n in names])
            nd = [x for n, x in zip(names, r) if not n.startswith('dark')]
            dk = [x for n, x in zip(names, r) if n.startswith('dark')]
            e = np.array([e for x in nd for e in x['errs']])
            print(f"{v:11s} found {sum(x['found'] for x in nd)}/{sum(x['vis'] for x in nd)} dark {sum(x['found'] for x in dk)}/{sum(x['vis'] for x in dk)} "
                  f"spur {sum(x['spurious'] for x in nd)} | median comps/img {int(np.median([x['comps'] for x in r]))} max {max(x['comps'] for x in r)} "
                  f"| max runs/row {max(x['maxruns'] for x in r)} imgs>64runs {sum(1 for x in r if x['over'])} | corner err mean {e.mean():.3f} p95 {np.percentile(e, 95):.2f}", flush=True)
