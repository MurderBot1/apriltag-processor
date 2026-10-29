"""CCL-only sweep of the 500-frame set: golden binary mask -> rtl/run_ccl.v (tb_ccl) at a given line period, compared with the
streaming model golden.stream_components().  Much faster than the full chain (no TPU): reports per frame the status flags, the
slowest row (clocks), dropped rows, label high-water mark and whether the RTL candidate table equals the model's.

    py -3.12 tests/sweep_ccl_rtl.py [line_clocks=686] [name ...]     (default: all frames; 686 = 85.714 MHz, 800 = 100 MHz sim)
Writes results/ccl_sweep_<line>.json and prints a summary."""
import os, sys, json, re, cv2, numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden, ccl_check
ROOT = rtlutil.ROOT
LINE = int(os.environ.get('CCL_LINE', 686))


def one(name):
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    m = golden.binarize_clean(img).astype(np.uint8)
    tag = f'sw{LINE}_{name}'
    mp = os.path.join(rtlutil.SIM, tag + '.mask'); m.tofile(mp)
    vvp = os.path.join(rtlutil.SIM, 'tb_ccl.vvp')
    out = rtlutil.run(vvp, [f'mask={mp}', f'out={rtlutil.SIM}/{tag}.cand', f'line={LINE}', 'minarea=100', 'mindim=10', 'rej=1', 'maxarea=400000'])
    r = re.search(r'flags=(\d+) max_row_cycles=(\d+) done_latency=(\d+) rows_dropped=(\d+) labels_used=(\d+)', out)
    recs = ccl_check.parse_dump(os.path.join(rtlutil.SIM, tag + '.cand'))
    cands, info = golden.stream_components(m.astype(bool))
    same = [c['area'] for c in cands] == [x['area'] for x in recs]
    os.remove(mp)
    return name, dict(flags=r.group(1), max_row_cycles=int(r.group(2)), done_latency=int(r.group(3)), rows_dropped=int(r.group(4)),
                      labels_used=int(r.group(5)), count=len(recs), model_count=len(cands), model_same=bool(same), runs=info['runs'])


if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0].isdigit(): LINE = int(args.pop(0)); os.environ['CCL_LINE'] = str(LINE)
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    names = args or sorted(gt)
    rtlutil.build('tb_ccl', ['rtl/run_ccl.v', 'tb/tb_ccl.v'])
    res = {}
    with Pool(int(os.environ.get('WORKERS', 12))) as p:
        for n, r in p.imap_unordered(one, names):
            res[n] = r
    json.dump(res, open(os.path.join(ROOT, 'results', f'ccl_sweep_{LINE}.json'), 'w'), indent=0, sort_keys=True)
    v = list(res.values())
    print(f'line={LINE}: frames {len(v)}  rows_dropped>0: {sum(x["rows_dropped"] > 0 for x in v)}  total rows dropped {sum(x["rows_dropped"] for x in v)}'
          f'  worst row {max(x["max_row_cycles"] for x in v)} clk  max labels {max(x["labels_used"] for x in v)}'
          f'  flags!=0000: {sum(x["flags"] != "0000" for x in v)}  model==rtl: {sum(x["model_same"] for x in v)}/{len(v)}'
          f'  done_latency max {max(x["done_latency"] for x in v)}')
    bad = [n for n, x in res.items() if not x['model_same']]
    print('model mismatches:', bad[:20])
