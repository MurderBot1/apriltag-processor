"""Analyse results/rtl_chain_results.json: detection, corner error and firmware pose error versus ground truth and
versus the reference pipeline (pupil-apriltags + solvePnP, results/reference_baseline.json)."""
import os, sys, json, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import geom, atcore
ROOT = geom.ROOT


def load():
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    rtl = json.load(open(os.environ.get('CHAIN_OUT') or os.path.join(ROOT, 'results', 'rtl_chain_results.json')))
    ref = json.load(open(os.path.join(ROOT, 'results', 'reference_baseline.json')))        # 100-image baseline (tools/reference_pipeline.py)
    return gt, rtl, ref


def analyse():
    gt, rtl, ref = load()
    tmap = geom.load_tag_map()
    sol = atcore.Solver(False); sol.set_field(tmap)
    rows = {}
    for name, g in gt.items():
        # score over the detectable tags (GT schema v2); legacy ground truth without the flag falls back to `visible`
        vis = {int(t) for t, v in g['tags'].items() if v.get('detectable', v['visible'])}
        det = {t['id']: np.array(t['corners']) for t in rtl[name]['tags']}
        found = vis & set(det); false = {t for t in det if t not in {int(k) for k in g['tags']}}
        wrong_pos = [t for t in det if str(t) in g['tags'] and not g['tags'][str(t)]['visible']]
        cerr = [np.linalg.norm(det[t] - np.array(g['tags'][str(t)]['corners']), axis=1).max() for t in found]
        rd = ref['per_image'].get(name, {})
        pose = sol.solve([(t, det[t]) for t in det if t in tmap]) if det else None
        pe = None
        if pose:
            pe = (np.linalg.norm(pose[1] - np.array(g['t_wc'])) * 1000, geom.rot_angle_deg(pose[0], np.array(g['R_wc'])), pose[2], pose[3])
        rows[name] = dict(cat=g['category'], vis=len(vis), found=len(found), false=len(false), unseen_det=len(wrong_pos),
                          cerr=cerr, pose=pe, dropped=rtl[name]['stats'].get('dropped'), ccl=rtl[name]['stats'].get('ccl'), ref_found=rd.get('n_detected'), ref_t=rd.get('t_err_mm'), stats=rtl[name]['stats'])
    return rows, ref


def report(rows, ref):
    cats = sorted({r['cat'] for r in rows.values()})
    out = ['| category | images | GT-visible tags | detected | false pos | corner err mean/max (px) | pose t median/max (mm) | rot median/max (deg) | reference t median (mm) |',
           '|---|---|---|---|---|---|---|---|---|']
    for c in cats:
        rs = [r for k, r in rows.items() if r['cat'] == c]
        v, f = sum(r['vis'] for r in rs), sum(r['found'] for r in rs)
        ce = np.array([e for r in rs for e in r['cerr']]) if any(r['cerr'] for r in rs) else np.array([np.nan])
        pe = np.array([r['pose'][:2] for r in rs if r['pose']]) if any(r['pose'] for r in rs) else np.array([[np.nan, np.nan]])
        rf = []
        for k, r in rows.items():
            if r['cat'] != c: continue
            if r['ref_t'] is not None: rf.append(r['ref_t'])
        out.append(f"| {c} | {len(rs)} | {v} | {f} ({(f / v if v else float('nan')):.0%}) | {sum(r['false'] for r in rs)} | "
                   f"{np.nanmean(ce):.2f} / {np.nanmax(ce):.2f} | {np.nanmedian(pe[:, 0]):.1f} / {np.nanmax(pe[:, 0]):.1f} | "
                   f"{np.nanmedian(pe[:, 1]):.3f} / {np.nanmax(pe[:, 1]):.2f} | {np.median(rf) if rf else float('nan'):.1f} |")
    return '\n'.join(out)


if __name__ == '__main__':
    rows, ref = analyse()
    print(report(rows, ref))
    print()
    allv = sum(r['vis'] for r in rows.values()); allf = sum(r['found'] for r in rows.values())
    nd = [r for r in rows.values() if r['cat'] != 'dark']
    print('overall detection', allf, '/', allv, ' non-dark:', sum(r['found'] for r in nd), '/', sum(r['vis'] for r in nd))
    print('false positives', sum(r['false'] for r in rows.values()), ' detections of GT-invisible tags', sum(r['unseen_det'] for r in rows.values()))
    print('frames dropped total', sum(int(r['dropped'] or 0) for r in rows.values() if int(r['dropped'] or 0) < 1000))
    print('reference detections (same images):', sum(r['ref_found'] or 0 for r in rows.values()), ' rtl:', allf)
    worse = [(k, r['found'], r['ref_found']) for k, r in rows.items() if r['ref_found'] is not None and r['found'] < r['ref_found']]
    print('rtl found fewer than reference:', worse)
    miss = [(k, r['vis'], r['found']) for k, r in rows.items() if r['found'] < r['vis']]
    print('images with misses:', miss[:40])
