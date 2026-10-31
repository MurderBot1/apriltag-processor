"""Run the native C AprilTag bench (tools/costdown_c) with several settings on the 100 frames and score id-level accuracy.
    py -3.12 tools/costdown_score.py <bench.exe> <pgm_dir> [bin]  -> results/costdown_native.json (bin: pre-thresholded frames -> costdown_native_bin.json)
A frame passes when every ground-truth-detectable tag id is found (hamming 0) and no id outside the visible set is reported."""
import os, sys, json, subprocess, glob, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import ROOT
exe, pgm = sys.argv[1], sys.argv[2]
G = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))
files = sorted(glob.glob(os.path.join(pgm, '*.pgm')))
out = []
CFG = [(1, 0, 1), (1.5, 0, 1), (2, 0, 1), (1, 0, 2), (1, 0, 4)] if len(sys.argv) > 3 and sys.argv[3] == 'bin' else [(1, 0, 1), (1, 0.6, 1), (1, 0.8, 1), (1, 1.0, 1), (1.5, 0, 1), (1.5, 0.8, 1), (2, 0, 1), (2, 0.8, 1), (1, 0, 2), (1, 0, 4), (1, 0.8, 4), (1, 0.8, 2), (1.5, 0, 4)]
for dec, qs, nt in CFG:
    env = dict(os.environ, DUMP='1', QS=str(qs))
    txt = subprocess.run([exe, str(dec), '1', str(nt)] + files, env=env, capture_output=True, text=True).stdout.splitlines()
    ms = []; ok = nd = ndd = fa = 0; cat = {}
    for ln in txt:
        if not ln.startswith('F '): continue
        p = ln.split(); n = os.path.basename(p[1])[:-4]; t = float(p[2]); ids = {int(x) for x in p[3:]}
        g = G['images'][n]; vis = {int(i) for i, v in g['tags'].items() if v['visible']}
        dtb = {int(i) for i, v in g['tags'].items() if v.get('detectable', v['visible'])}
        a = len(ids & dtb & set(range(10**6))); f = len(ids - vis); good = bool(dtb) and a == len(dtb) and f == 0
        nd += len(dtb); ndd += a; fa += f; ok += good
        if n != os.path.basename(files[0])[:-4]: ms.append(t)    # first file is warm-up, excluded from timing but scored
        cat.setdefault(g['category'], []).append(t)
    ms = np.array(ms)
    r = dict(decimate=dec, quad_sigma=qs, threads=nt, mean_ms=float(ms.mean()), p95_ms=float(np.percentile(ms, 95)), max_ms=float(ms.max()),
             tags=ndd, detectable=nd, false_ids=fa, frames_ok=ok, cat_mean_ms={c: float(np.mean(v)) for c, v in cat.items()})
    out.append(r)
    print(f"dec {dec} sigma {qs} thr {nt}: mean {r['mean_ms']:.1f} p95 {r['p95_ms']:.1f} max {r['max_ms']:.1f} ms | tags {ndd}/{nd} false {fa} frames {ok}/100", flush=True)
json.dump(out, open(os.path.join(ROOT, 'results', 'costdown_native_bin.json' if len(sys.argv) > 3 and sys.argv[3] == 'bin' else 'costdown_native.json'), 'w'), indent=1)
