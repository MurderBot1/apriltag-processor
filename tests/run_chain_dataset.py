"""Run every dataset image through the full RTL chain (CSI-2 @120fps -> cam_core -> SPI results) in parallel.
Writes results/rtl_chain_results.json: per image the tag estimates the MCU would receive over SPI.

Full 100-frame set (the long job):   py -3.12 tests/run_chain_dataset.py          (WORKERS=12 by default; env WORKERS=n to change)
  Expected runtime: measured 377 s wall-clock for the original 100 frames with 12 workers (~30-40 s per frame per worker, see
  results/chain_dataset.log) => ~6-8 min for all 100 with 10-12 workers; allow longer if other CPU-heavy jobs are running.
  NOT run in CI (too slow); CI scores the dataset at reference-detector level, see docs/verification.md.
Subset / resume:  py -3.12 tests/run_chain_dataset.py name1 name2 ...   (only those frames; NOTE: the output file is overwritten with
  just that subset - merge with a previous run yourself, or use --merge below)
  py -3.12 tests/run_chain_dataset.py --merge [names...]   keep existing entries of results/rtl_chain_results.json, simulate only
  the frames that are missing from it (or the names given) and write the union: this is how to resume an interrupted full run.
Score it with tests/analyze_chain.py (detection is scored over GT `detectable` tags; reference = results/reference_baseline.json)."""
import os, sys, json, time, cv2, numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import chain, rtlutil
ROOT = rtlutil.ROOT


def work(name):
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    vvp = os.path.join(rtlutil.SIM, 'tb_cam.vvp')
    log, res, el = chain.run_frames(vvp, [img], 'ds_' + name)
    tags = []
    if res['results']:
        for t in chain.decode_tags(res['results'][0]['words']):
            tags.append(dict(id=t['id'], ham=t['ham'], corners=t['corners'].tolist()))
    st = res['stats'] or {}
    return name, dict(tags=tags, stats=st, seconds=el, n_results=len(res['results']))


if __name__ == '__main__':
    chain.build()
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))
    names = sorted(gt['images'])
    args = sys.argv[1:]; merge = '--merge' in args; args = [a for a in args if a != '--merge']
    path = os.path.join(ROOT, 'results', 'rtl_chain_results.json')
    out = json.load(open(path)) if merge and os.path.exists(path) else {}
    only = args or ([n for n in names if n not in out] if merge else names)
    t0 = time.time()
    with Pool(int(os.environ.get('WORKERS', 12))) as p:
        for n, r in p.imap_unordered(work, only):
            out[n] = r; print(f'{n}: {len(r["tags"])} tags  {r["seconds"]:.0f}s', flush=True)
            if merge: json.dump(out, open(path, 'w'))        # checkpoint after every frame so an interrupted run can resume
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    json.dump(out, open(path, 'w'))
    print('done', len(out), 'images in', round(time.time() - t0), 's')
