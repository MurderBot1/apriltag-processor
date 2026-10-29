"""Reference (PC) pipeline: undistort -> pupil-apriltags -> multi-tag solvePnP. Baseline for the FPGA/firmware result.
CLI: py -3.12 tools/reference_pipeline.py   -> results/reference_baseline.{json,md}"""
import os, sys, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import *

_DET = None


def detector():
    global _DET
    if _DET is None:
        from pupil_apriltags import Detector
        _DET = Detector(families='tag36h11', quad_decimate=1.0, refine_edges=True, decode_sharpening=0.25)
    return _DET


PAD = 400  # undistorted canvas is padded so tags that the lens pulls outside the sensor area (wide FOV) still get detected


def undistort_img(gray, K, dist):
    h, w = gray.shape
    K2 = K.copy(); K2[0, 2] += PAD; K2[1, 2] += PAD
    mx, my = cv2.initUndistortRectifyMap(K, np.asarray(dist, float), None, K2, (w + 2 * PAD, h + 2 * PAD), cv2.CV_32FC1)
    return cv2.remap(gray, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def undistort_pts(px, K, dist):
    return cv2.undistortPoints(np.asarray(px, np.float64).reshape(-1, 1, 2), K, np.asarray(dist, float), P=K).reshape(-1, 2)


def reference_pose(image_path, tag_map, K, dist):
    """Returns dict(detections={id: 4x2 corners TL,TR,BR,BL in UNDISTORTED px}, pose=None|dict(R_wc,t_wc,rms,n_tags))."""
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    und = undistort_img(gray, K, dist)
    dets = detector().detect(und)
    out = {}
    for d in dets:
        if d.tag_id in tag_map and d.hamming == 0:
            out[int(d.tag_id)] = (np.asarray(d.corners, float)[[1, 0, 3, 2]] - 0.5 - PAD)  # lib order TR,TL,BL,BR -> TL,TR,BR,BL; lib puts the image origin at the top-left pixel CORNER, geom.py at the pixel CENTRE -> -0.5
    res = dict(detections=out, pose=None)
    if out:
        obj = np.concatenate([tag_corners_world(tag_map, i) for i in out]).astype(np.float64)
        img = np.concatenate([out[i] for i in out]).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_SQPNP)
        if ok:
            rvec, tvec = cv2.solvePnPRefineLM(obj, img, K, None, rvec, tvec)
            Rcw, _ = cv2.Rodrigues(rvec)
            proj = cv2.projectPoints(obj, rvec, tvec, K, None)[0].reshape(-1, 2)
            res['pose'] = dict(R_wc=Rcw.T, t_wc=(-Rcw.T @ tvec).ravel(),
                               rms=float(np.sqrt(np.mean(np.sum((proj - img) ** 2, 1)))), n_tags=len(out))
    return res


def evaluate(gt_path=None, img_dir=None):
    gt_path = gt_path or os.path.join(ROOT, 'test_images', 'ground_truth.json')
    img_dir = img_dir or os.path.join(ROOT, 'test_images', 'sensor')
    G = json.load(open(gt_path))
    K = np.array(G['K']); dist = np.array(G['dist']); tmap = load_tag_map()
    rows = {}
    for name, g in G['images'].items():
        r = reference_pose(os.path.join(img_dir, name + '.png'), tmap, K, dist)
        vis = [int(i) for i, t in g['tags'].items() if t['visible']]
        # detectable (GT schema v2, see tools/dataset_gt.py); older ground truth without the flag: detectable == visible
        dtb = [int(i) for i, t in g['tags'].items() if t.get('detectable', t['visible'])]
        errs = []
        for i in vis:
            if i in r['detections']:
                gtc = undistort_pts(g['tags'][str(i)]['corners'], K, dist)
                errs += list(np.linalg.norm(gtc - r['detections'][i], axis=1))
        row = dict(category=g['category'], n_visible=len(vis), n_detected=sum(i in r['detections'] for i in vis),
                   n_false=sum(i not in vis for i in r['detections']), corner_errs=[float(e) for e in errs],
                   n_detectable=len(dtb), n_det_detectable=sum(i in r['detections'] for i in dtb),
                   missed=[dict(id=i, px_width=round(g['tags'][str(i)]['px_width'], 1), incidence_deg=g['tags'][str(i)].get('incidence_deg'),
                                occ_fraction=g['tags'][str(i)].get('occ_fraction'), sat_frac=g['tags'][str(i)].get('sat_frac'),
                                contrast=g['tags'][str(i)].get('contrast')) for i in dtb if i not in r['detections']],
                   n_undetectable_found=sum(i in r['detections'] and i not in dtb for i in vis),
                   n_hidden_found=sum(i in r['detections'] and i not in vis for i in r['detections']),
                   t_err_mm=None, rot_err_deg=None, rms_px=None)
        if r['pose'] is not None:
            p = r['pose']
            row['t_err_mm'] = float(np.linalg.norm(p['t_wc'] - np.array(g['t_wc'])) * 1000)
            row['rot_err_deg'] = float(rot_angle_deg(p['R_wc'], np.array(g['R_wc'])))
            row['rms_px'] = p['rms']; row['n_tags_used'] = p['n_tags']
        rows[name] = row
    return rows


def summarize(rows):
    cats = {}
    for n, r in rows.items():
        cats.setdefault(r['category'], []).append(r)
    s = {}
    for c, rs in cats.items():
        e = np.array([x for r in rs for x in r['corner_errs']])
        te = [r['t_err_mm'] for r in rs if r['t_err_mm'] is not None]
        re_ = [r['rot_err_deg'] for r in rs if r['rot_err_deg'] is not None]
        nv = sum(r['n_visible'] for r in rs); nd = sum(r['n_detected'] for r in rs)
        ndt = sum(r.get('n_detectable', r['n_visible']) for r in rs); ndd = sum(r.get('n_det_detectable', r['n_detected']) for r in rs)
        s[c] = dict(images=len(rs), visible=nv, detected=nd, rate=(nd / nv if nv else None),
                    detectable=ndt, det_detectable=ndd, rate_detectable=(ndd / ndt if ndt else None),
                    false=sum(r['n_false'] for r in rs),
                    corner_mean=float(e.mean()) if e.size else None, corner_med=float(np.median(e)) if e.size else None,
                    corner_max=float(e.max()) if e.size else None,
                    pose_images=len(te), t_mean=float(np.mean(te)) if te else None, t_max=float(np.max(te)) if te else None,
                    r_mean=float(np.mean(re_)) if re_ else None, r_max=float(np.max(re_)) if re_ else None)
    return s


def f(x, p=2):
    return '-' if x is None else f'{x:.{p}f}'


def main():
    rows = evaluate(); s = summarize(rows)
    suffix = '' if len(rows) == 100 else f'_{len(rows)}'      # the 100-image baseline files are kept as they are
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    json.dump(dict(per_image=rows, per_category=s), open(os.path.join(ROOT, 'results', f'reference_baseline{suffix}.json'), 'w'), indent=1)
    tot = lambda k: sum(v[k] for v in s.values())
    L = ['# Reference pipeline baseline' + (f' ({len(rows)} images)' if suffix else ''), '',
         'undistort -> pupil-apriltags tag36h11 -> SQPnP + LM over all detected tag corners.', '',
         'A tag is *detectable* when it faces the camera, is fully inside the frame, is >= 10 px wide, is within 75 deg of the camera axis, is <= 50 % occluded and is not washed out / flat in the image (tools/dataset_gt.py). '
         'Rates are detected / detectable; `vis` = legacy geometric visibility (facing + inside the frame) is kept for comparison with the 100-image baseline.', '',
         f"Overall: {tot('det_detectable')} / {tot('detectable')} detectable tags detected ({tot('det_detectable') / max(1, tot('detectable')):.1%}); legacy vis: {tot('detected')} / {tot('visible')}; false-ID detections {tot('false')}.", '',
         '## Per category', '', '| cat | imgs | detectable | det | rate (detectable) | vis | rate (vis) | false | corner mean/med/max px | pose imgs | t mean/max mm | rot mean/max deg |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for c, v in s.items():
        L.append(f"| {c} | {v['images']} | {v['detectable']} | {v['det_detectable']} | {f(v['rate_detectable'])} | {v['visible']} | {f(v['rate'])} | {v['false']} | {f(v['corner_mean'])}/{f(v['corner_med'])}/{f(v['corner_max'])} | {v['pose_images']} | {f(v['t_mean'],1)}/{f(v['t_max'],1)} | {f(v['r_mean'],3)}/{f(v['r_max'],3)} |")
    miss = [(n, m) for n, r in rows.items() for m in r.get('missed', [])]
    L += ['', f'## Detectable tags the reference missed ({len(miss)})', '', '| image | tag | px width | incidence deg | occ | sat | contrast |', '|---|---|---|---|---|---|---|']
    for n, m in miss:
        L.append(f"| {n} | {m['id']} | {m['px_width']} | {f(m['incidence_deg'],1)} | {f(m['occ_fraction'])} | {f(m['sat_frac'])} | {f(m['contrast'],0)} |")
    fl = [(n, r['n_false']) for n, r in rows.items() if r['n_false']]
    L += ['', f'## Detections of tags not geometrically visible / unknown ids (n_false > 0): {fl}', '',
          f"Tags flagged undetectable but still found by the reference: {tot('undetectable_found') if 'undetectable_found' in list(s.values())[0] else sum(r.get('n_undetectable_found', 0) for r in rows.values())}", '',
          '## Per image', '', '| image | vis | detectable | det | corner mean px | rms px | t err mm | rot err deg |', '|---|---|---|---|---|---|---|---|']
    for n, r in rows.items():
        ce = np.mean(r['corner_errs']) if r['corner_errs'] else None
        L.append(f"| {n} | {r['n_visible']} | {r.get('n_detectable', r['n_visible'])} | {r['n_detected']} | {f(ce)} | {f(r['rms_px'])} | {f(r['t_err_mm'],1)} | {f(r['rot_err_deg'],3)} |")
    open(os.path.join(ROOT, 'results', f'reference_baseline{suffix}.md'), 'w').write(chr(10).join(L) + chr(10))
    print(chr(10).join(L[:12 + len(s)]))


if __name__ == '__main__':
    main()
