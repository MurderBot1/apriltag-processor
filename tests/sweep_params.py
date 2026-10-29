"""Parameter sweep of the FPGA-side thresholds using the bit-exact golden models + TPU ISS (fast, no RTL sim)."""
import os, sys, json, itertools, cv2, numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import golden, tpu_harness, geom
ROOT = geom.ROOT
GT = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']


def one(args):
    name, diff, absb, mina, mind = args
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    mask = golden.binarize(img, diff, absb)
    tags, mach, nc = tpu_harness.run_iss(mask, min_area=mina, min_dim=mind)
    vis = {int(t) for t, v in GT[name]['tags'].items() if v['visible']}
    ids = {t['id'] for t in tags}
    return len(vis & ids), len(ids - set(int(k) for k in GT[name]['tags'])), len(vis), nc, mach.cycles


if __name__ == '__main__':
    grid = [(24, 64, 100, 10), (24, 64, 40, 6), (16, 64, 40, 6), (16, 64, 25, 5), (20, 64, 40, 6), (12, 64, 30, 6)]
    names = [n for n in sorted(GT) if not n.startswith('dark')]
    dark = [n for n in sorted(GT) if n.startswith('dark')]
    with Pool(12) as p:
        for g in grid:
            r = p.map(one, [(n,) + g for n in names + dark])
            nd = r[:len(names)]; dk = r[len(names):]
            print(f'diff={g[0]} abs={g[1]} minarea={g[2]} mindim={g[3]}: non-dark found {sum(x[0] for x in nd)}/{sum(x[2] for x in nd)} '
                  f'spurious {sum(x[1] for x in nd)} dark {sum(x[0] for x in dk)}/{sum(x[2] for x in dk)} '
                  f'max cands {max(x[3] for x in nd)} max cycles {max(x[4] for x in nd)}', flush=True)
