"""Cost-down study benchmark: software AprilTag detection time and id-level accuracy on the 100-image dataset.
    py -3.12 tools/costdown_bench.py            -> results/costdown_bench.json
Single thread (nthreads=1) so the numbers can be scaled per core. Variants: input (raw 1280x800 / padded undistorted 2080x1600 as the
reference pipeline does), quad_decimate (1, 1.5, 2), refine_edges.  Accuracy = a frame passes when every ground-truth-detectable tag is
found with hamming 0 and no id outside the visible set is reported (same rule as tests/ci_category.py; id-level only, no pose)."""
import os, sys, json, time
import numpy as np, cv2
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import reference_pipeline as rp
from geom import ROOT
from pupil_apriltags import Detector

G = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))
K = np.array(G['K']); dist = np.array(G['dist']); tmap = rp.load_tag_map()
names = sorted(G['images'])
imgs = {n: cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), cv2.IMREAD_GRAYSCALE) for n in names}
und = {n: rp.undistort_img(imgs[n], K, dist) for n in names}
t0 = time.perf_counter()
for n in names: rp.undistort_img(imgs[n], K, dist)
undist_ms = (time.perf_counter() - t0) / len(names) * 1e3

def run(label, src, decimate, refine, sharpen=0.25, blur=0.0):
    det = Detector(families='tag36h11', nthreads=1, quad_decimate=decimate, quad_sigma=blur, refine_edges=refine, decode_sharpening=sharpen)
    det.detect(src[names[0]])  # warm up
    ms = []; ok = 0; nd = 0; ndd = 0; fa = 0; per = {}
    for n in names:
        g = G['images'][n]
        t = time.perf_counter(); d = det.detect(src[n]); ms.append((time.perf_counter() - t) * 1e3)
        found = {int(x.tag_id) for x in d if x.tag_id in tmap and x.hamming == 0}
        vis = {int(i) for i, t_ in g['tags'].items() if t_['visible']}
        dtb = {int(i) for i, t_ in g['tags'].items() if t_.get('detectable', t_['visible'])}
        a = len(found & dtb); f = len(found - vis)
        nd += len(dtb); ndd += a; fa += f; good = bool(dtb) and a == len(dtb) and f == 0; ok += good
        per.setdefault(g['category'], []).append((ms[-1], good))
    ms = np.array(ms)
    r = dict(label=label, decimate=decimate, refine=refine, size=list(src[names[0]].shape), mean_ms=float(ms.mean()), median_ms=float(np.median(ms)),
             p95_ms=float(np.percentile(ms, 95)), max_ms=float(ms.max()), detectable=nd, found=ndd, false_ids=fa, frames_ok=ok,
             by_cat={c: dict(mean_ms=float(np.mean([x[0] for x in v])), ok=sum(x[1] for x in v)) for c, v in per.items()})
    print(f"{label:34s} mean {r['mean_ms']:7.2f} med {r['median_ms']:7.2f} p95 {r['p95_ms']:7.2f} max {r['max_ms']:7.2f} ms | tags {ndd}/{nd} false {fa} frames {ok}/100", flush=True)
    return r

res = []
for lab, src in (('raw1280x800', imgs), ('padded2080x1600 (reference)', und)):
    for dec in (1.0, 1.5, 2.0):
        for ref in (True, False):
            if dec != 1.0 and not ref and src is und: continue
            res.append(run(f'{lab} dec{dec} refine{int(ref)}', src, dec, ref))
json.dump(dict(cpu='AMD Ryzen 9 7900X (Zen4, boost to ~4.7-5.6 GHz), Windows 11, pupil-apriltags 1.0.4 (apriltag C lib), single thread', undistort_image_ms=undist_ms, results=res),
          open(os.path.join(ROOT, 'results', 'costdown_bench.json'), 'w'), indent=1)
print('undistort(remap, padded) ms/frame', undist_ms)
