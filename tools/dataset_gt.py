"""Per-tag ground truth for the test dataset (v2): projection, occlusion by scene objects (analytic ray casting),
detectability flags.  Used by tools/make_dataset_500.py (case rejection + GT writing) and by the tests.

Detectability (a tag is `detectable` only if NONE of these reasons applies; see DETECT below):
  back_facing  tag normal points away from the camera
  outside_frame  not all 4 corners inside the sensor (2 px margin)         <- same rule as the legacy `visible`
  too_small    mean edge length < 10 px
  grazing      angle between tag normal and the ray to the camera > 75 deg
  occluded     more than 50 % of the tag area hidden behind an occluder object
  washed_out   (image-derived, applied only if the tag was otherwise detectable) >60 % of the tag's pixels saturated at 255
  low_contrast (image-derived) 5..95 percentile spread inside the tag quad < 10 grey levels (below the sensor noise floor)
`visible` keeps its legacy meaning (facing the camera AND all corners in frame) so old consumers are unaffected."""
import os, sys, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import *

DETECT = dict(min_px=10.0, max_incidence_deg=75.0, max_occlusion=0.5, border_px=2)
NSAMP = 20                                   # NSAMP x NSAMP sample grid over the tag for the occlusion / frame-coverage estimate


def occluder_R(oc):
    return np.array(oc.get('R', np.eye(3)), float)


def segment_hits(p0, P1, occluders):
    """bool array: does the segment p0 -> P1[i] (open at the far end) hit any occluder."""
    P1 = np.asarray(P1, float); p0 = np.asarray(p0, float)
    hit = np.zeros(len(P1), bool)
    d = P1 - p0
    for oc in occluders:
        c = np.array(oc['center'], float)
        if oc['kind'] == 'sphere':
            r = float(oc['size'][0])
            f = p0 - c
            a = (d * d).sum(1); b = 2 * (d @ f); cc = f @ f - r * r
            disc = b * b - 4 * a * cc
            ok = disc >= 0
            sq = np.sqrt(np.where(ok, disc, 0))
            t0 = (-b - sq) / (2 * a); t1 = (-b + sq) / (2 * a)
            hit |= ok & (t1 > 0) & (t0 < 0.999)
        else:
            Rm = occluder_R(oc); h = np.array(oc['size'], float) / 2
            lp0 = Rm.T @ (p0 - c); ld = (Rm.T @ d.T).T
            tmin = np.zeros(len(P1)); tmax = np.full(len(P1), 0.999)
            ok = np.ones(len(P1), bool)
            for k in range(3):
                dk = ld[:, k]
                par = np.abs(dk) < 1e-12
                inside = np.abs(lp0[k]) <= h[k]
                ok &= ~(par & ~inside)
                with np.errstate(divide='ignore', invalid='ignore'):
                    t1 = (-h[k] - lp0[k]) / dk; t2 = (h[k] - lp0[k]) / dk
                lo = np.where(par, -np.inf, np.minimum(t1, t2)); hi = np.where(par, np.inf, np.maximum(t1, t2))
                tmin = np.maximum(tmin, lo); tmax = np.minimum(tmax, hi)
            hit |= ok & (tmin <= tmax)
    return hit


def tag_samples(tmap, tid, n=NSAMP):
    p, R, s = tmap[tid]
    g = (np.arange(n) + 0.5) / n - 0.5
    gx, gy = np.meshgrid(g * s, g * s)
    loc = np.stack([gx.ravel(), gy.ravel(), np.zeros(n * n)], 1)
    return (R @ loc.T).T + p


def tag_geometry(R, t, tmap, K, dist, occluders=(), W=W, H=H):
    """Per-tag dict (no image-derived fields).  R,t = camera->world pose."""
    out = {}
    for tid in tmap:
        cw = tag_corners_world(tmap, tid)
        px, z = project(cw, R, t, K, dist)
        nrm = tmap[tid][1][:, 2]; ctr = tmap[tid][0]
        v = t - ctr; dcam = float(np.linalg.norm(v))
        cosang = float(nrm @ v) / dcam
        facing = cosang > 0
        inc = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
        b = DETECT['border_px']
        inimg = bool(np.all(z > 0.05) and np.all((px[:, 0] > b) & (px[:, 0] < W - 1 - b) & (px[:, 1] > b) & (px[:, 1] < H - 1 - b)))
        edges = [np.linalg.norm(px[1] - px[0]), np.linalg.norm(px[2] - px[3]), np.linalg.norm(px[3] - px[0]), np.linalg.norm(px[2] - px[1])]
        px_width = float(np.mean(edges[:2]))
        sm = tag_samples(tmap, tid)
        spx, sz = project(sm, R, t, K, dist)
        inf = (sz > 0.05) & (spx[:, 0] >= 0) & (spx[:, 0] <= W - 1) & (spx[:, 1] >= 0) & (spx[:, 1] <= H - 1)
        occ = segment_hits(t, sm, list(occluders)) if (facing and len(occluders)) else np.zeros(len(sm), bool)
        occ_frac = float(occ.mean()); vis_frac = float((inf & ~occ).mean()) if facing else 0.0
        reasons = []
        if not facing: reasons.append('back_facing')
        if not inimg: reasons.append('outside_frame')
        if px_width < DETECT['min_px']: reasons.append('too_small')
        if facing and inc > DETECT['max_incidence_deg']: reasons.append('grazing')
        if occ_frac > DETECT['max_occlusion']: reasons.append('occluded')
        # nearest-to-border distance of the corners (px), negative when a corner is outside the sensor
        ed = float(min(px[:, 0].min(), px[:, 1].min(), (W - 1) - px[:, 0].max(), (H - 1) - px[:, 1].max()))
        out[str(tid)] = dict(corners=px.tolist(), visible=bool(facing and inimg), px_width=px_width,
                             in_frame=inimg, facing=bool(facing), incidence_deg=round(inc, 3), distance_m=round(dcam, 4),
                             px_min_edge=round(float(min(edges)), 3), edge_dist_px=round(ed, 2),
                             occ_fraction=round(occ_frac, 4), vis_fraction=round(vis_frac, 4),
                             detectable=not reasons, undetectable_reasons=reasons)
    return out


def image_stats(gray, corners):
    """sat_frac / contrast measured inside the tag quad of the final sensor image (None when the quad is off-frame)."""
    q = np.round(np.array(corners)).astype(np.int32)
    m = np.zeros(gray.shape, np.uint8)
    cv2.fillConvexPoly(m, q, 1)
    v = gray[m > 0]
    if v.size < 16:
        return dict(sat_frac=None, contrast=None, mean_level=None)
    return dict(sat_frac=round(float((v >= 250).mean()), 4), contrast=round(float(np.percentile(v, 95) - np.percentile(v, 5)), 1),
                mean_level=round(float(v.mean()), 1))


IMG_LIMITS = dict(max_sat_frac=0.6, min_contrast=10.0)


def apply_image_reasons(t):
    """add the image-derived undetectable reasons (needs sat_frac / contrast from image_stats) and refresh t['detectable']"""
    r = [x for x in t['undetectable_reasons'] if x not in ('washed_out', 'low_contrast')]
    if t['detectable'] or not r:      # only meaningful for tags that are otherwise detectable
        if t.get('sat_frac') is not None and t['sat_frac'] > IMG_LIMITS['max_sat_frac']: r.append('washed_out')
        if t.get('contrast') is not None and t['contrast'] < IMG_LIMITS['min_contrast']: r.append('low_contrast')
    t['undetectable_reasons'] = r; t['detectable'] = not r
