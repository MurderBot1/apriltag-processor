"""CI check for ONE dataset category: run the reference detector (undistort -> pupil-apriltags tag36h11) on the 10 committed frames of the
category and count the frames that succeed.

    py tests/ci_category.py <category> [--out results/ci/<category>.md] [--json results/ci/<category>.json] [--min N]

A frame SUCCEEDS when every tag that the ground truth marks `detectable` (tools/dataset_gt.py) is detected with Hamming distance 0 AND
no tag id that is hidden / not in the map is reported.  Result line: "category <cat>: N/10 detected".
This is the model-level (PC reference pipeline) check, not the RTL chip simulation: the RTL chain takes ~40 s per frame
(see tests/run_chain_dataset.py), too slow for per-PR CI.  Exit status is 0 as long as the script ran (the count is the result);
pass --min N to make the job fail below N successes.  Needs only numpy, opencv-python-headless, pupil-apriltags."""
import os, sys, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import numpy as np
import reference_pipeline as rp
from geom import ROOT

CATEGORIES = ['normal', 'bright', 'dark', 'lowcon', 'grad', 'shadow', 'noise', 'clutter', 'blur', 'persp']
DESC = dict(normal='clean baseline, nominal light, 0.8-3.8 m', bright='over-exposed (light x2-x5.5)', dark='under-exposed (light x0.03-x0.25)',
            lowcon='low contrast (24-42 % of nominal)', grad='uneven illumination (strong left/right gradient)',
            shadow='harsh cast shadow over a tag', noise='sensor noise x2-x4.5', clutter='busy background + 3-22 occluding objects',
            blur='defocus / motion blur (extra sigma 1-3 px)', persp='tag plane tilted 15-74 deg (yaw / pitch)')


def category_rows(cat):
    """reference-pipeline rows for the 10 frames of one category (the ground-truth dict is filtered so only those are processed)"""
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))
    names = sorted(n for n, g in gt['images'].items() if g['category'] == cat)
    assert len(names) == 10, (cat, len(names))
    sub = dict(gt, images={n: gt['images'][n] for n in names})
    os.makedirs(os.path.join(ROOT, 'sim'), exist_ok=True)
    tp = os.path.join(ROOT, 'sim', f'gt_{cat}.json'); json.dump(sub, open(tp, 'w'))
    rows = rp.evaluate(gt_path=tp)
    return names, rows


def frame_ok(r):
    return r['n_detectable'] > 0 and r['n_det_detectable'] == r['n_detectable'] and r['n_false'] == 0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('category', choices=CATEGORIES)
    ap.add_argument('--out'); ap.add_argument('--json'); ap.add_argument('--min', type=int, default=0)
    a = ap.parse_args()
    names, rows = category_rows(a.category)
    res = []
    for n in names:
        r = rows[n]
        res.append(dict(image=n, ok=bool(frame_ok(r)), detectable=r['n_detectable'], detected=r['n_det_detectable'], false_ids=r['n_false'],
                        corner_mean_px=(float(np.mean(r['corner_errs'])) if r['corner_errs'] else None),
                        t_err_mm=r['t_err_mm'], missed=[m['id'] for m in r['missed']]))
    n_ok = sum(x['ok'] for x in res)
    line = f'category {a.category}: {n_ok}/{len(res)} detected'
    f = lambda v, p=2: '-' if v is None else f'{v:.{p}f}'
    L = [f'### {line}', '',
         f'{DESC[a.category]}. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).', '',
         '| image | detectable tags | found | false ids | corner err px | pose err mm | result |', '|---|---|---|---|---|---|---|']
    for x in res:
        verdict = 'pass' if x['ok'] else ('FAIL (missed ' + str(x['missed']) + ')' if x['missed'] else 'FAIL')
        L.append(f"| {x['image']} | {x['detectable']} | {x['detected']} | {x['false_ids']} | {f(x['corner_mean_px'])} | {f(x['t_err_mm'], 1)} | {verdict} |")
    text = '\n'.join(L) + '\n'
    print(line); print(text)
    for path, data in ((a.out, text), (a.json, json.dumps(dict(category=a.category, ok=n_ok, total=len(res), images=res), indent=1))):
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True); open(path, 'w').write(data)
    sys.exit(1 if n_ok < a.min else 0)


if __name__ == '__main__':
    main()
