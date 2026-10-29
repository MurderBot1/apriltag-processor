"""LEGACY (old 100-frame set, no longer in the repo; kept as the library of camera model, lens-distortion maps and sensor model used by
tools/make_dataset_100.py - run that script to build the current dataset).  Build the test-image dataset: poses -> Blender -> lens distortion -> sensor model.
   test_images/raw/<name>.png    pinhole canvas straight from Blender (1920x1200 RGB)
   test_images/sensor/<name>.png 1280x800 mono 8-bit as the OV9281 would deliver it
   test_images/ground_truth.json camera pose + per-tag projected corners (distorted px)"""
import os, sys, json, math, subprocess, numpy as np, cv2
sys.path.insert(0, os.path.dirname(__file__))
from geom import *

BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
IMG = os.path.join(ROOT, 'test_images')


def make_cases(seed=7):
    rng = np.random.default_rng(seed)
    tmap = load_tag_map()
    cases = []

    def add(name, eye, target, rollDeg=0.0, **kw):
        R = roll(look_at(eye, target), rollDeg)
        cases.append(dict(name=name, R_wc=R.tolist(), t_wc=list(map(float, eye)), **kw))
    for d in (0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        add(f'dist_{int(d*10):02d}', (0.0, d, 1.2), (0.0, 0.0, 1.2))
    for a in (15, 30, 45, 60, 70):
        d = 1.8; add(f'yaw_{a:02d}', (d * math.sin(math.radians(a)), d * math.cos(math.radians(a)), 1.2), (0, 0, 1.2))
    for a in (45, 90, 135, 180, 270):
        add(f'roll_{a:03d}', (0.2, 1.6, 1.2), (0, 0, 1.2), rollDeg=a)
    add('dark_a', (0.0, 1.5, 1.2), (0, 0, 1.2), light_scale=0.12)
    add('dark_b', (0.5, 2.0, 1.0), (0, 0, 1.2), light_scale=0.05)
    add('bright', (0.0, 1.5, 1.2), (0, 0, 1.2), light_scale=3.0)
    add('grad_a', (0.0, 1.5, 1.2), (0, 0, 1.2), light_shift=-3.0)
    add('grad_b', (-0.3, 1.8, 1.0), (0.3, 0, 1.2), light_shift=3.5, light_scale=0.6)
    add('side_a', (-0.5, 2.5, 1.3), (-2.5, 1.5, 1.0))
    add('floor_a', (0.0, 2.4, 1.6), (-0.3, 1.8, 0.0))
    add('floor_b', (-0.7, 3.2, 1.8), (-0.5, 1.9, 0.0), rollDeg=30)
    n = 0
    while n < 30:
        tid = list(tmap)[rng.integers(len(tmap))]
        p, R, _ = tmap[tid]
        nrm = R[:, 2]
        dist = rng.uniform(0.9, 3.2)
        for _ in range(100):
            d = rng.normal(size=3); d /= np.linalg.norm(d)
            if d @ nrm > math.cos(math.radians(65)): break
        eye = p + d * dist
        if not (0.3 < eye[2] < 3.5 and -2.2 < eye[0] < 4.0 and 0.3 < eye[1] < 7.0): continue  # stay inside the room (walls occlude)
        tgt = p + rng.normal(scale=0.4, size=3) * np.array([1, 1, 0.5])
        add(f'rand_{n:02d}', eye, tgt, rollDeg=float(rng.uniform(-180, 180)),
            light_scale=float(rng.uniform(0.5, 1.6)), light_shift=float(rng.uniform(-2.5, 2.5)))
        n += 1
    add('empty', (0.0, 3.0, 1.5), (1.0, 7.0, 1.5))
    # ---- extension to 100 cases (existing names/poses above unchanged)
    for d in (4.0, 4.5, 5.0):
        add(f'dist_{int(d*10):02d}', (0.0, d, 1.2), (0.0, 0.0, 1.2))
    for a in (-20, -45, -65):
        d = 1.8; add(f'yaw_m{-a:02d}', (d * math.sin(math.radians(a)), d * math.cos(math.radians(a)), 1.2), (0, 0, 1.2))
    for a in (20, -30, 315):
        add(f'roll_{a % 360:03d}' if a > 0 else f'roll_m{-a:02d}', (-0.2, 1.7, 1.1), (0, 0, 1.2), rollDeg=a)
    add('dark_c', (0.3, 1.8, 1.2), (0, 0, 1.2), light_scale=0.2, light_shift=-1.5)
    add('dark_d', (-0.4, 1.2, 1.1), (0, 0, 1.2), light_scale=0.08)
    add('bright_b', (0.5, 2.0, 1.3), (0, 0, 1.2), light_scale=2.0)
    add('bright_c', (-0.5, 2.5, 1.0), (0, 0, 1.2), light_scale=4.0, light_shift=1.0)
    add('grad_c', (0.5, 1.6, 1.2), (0, 0, 1.2), light_shift=2.5)
    add('grad_d', (0.0, 2.2, 1.4), (0, 0, 1.0), light_shift=-4.0, light_scale=0.8)
    add('side_b', (0.5, 1.0, 1.2), (-2.5, 1.0, 1.1))
    add('side_c', (-1.0, 3.0, 1.0), (-2.5, 2.0, 0.9))
    add('side_d', (-1.5, 0.8, 1.4), (-2.5, 1.0, 1.2))
    add('side_e', (0.0, 2.0, 1.0), (-2.5, 2.0, 0.9))
    add('floor_c', (0.5, 2.0, 1.5), (0.0, 1.5, 0.0))
    add('floor_d', (-1.0, 1.5, 1.2), (-1.0, 2.5, 0.0))
    add('floor_e', (0.0, 3.0, 2.0), (-0.5, 2.0, 0.0), rollDeg=90)
    add('floor_f', (-2.0, 2.5, 1.5), (-1.0, 2.5, 0.0))
    add('empty_b', (0.0, 3.0, 1.5), (0.0, 8.0, 1.5))
    add('empty_c', (1.0, 2.0, 1.0), (5.0, 2.0, 1.0))
    add('empty_d', (0.0, 2.0, 1.2), (0.0, 2.6, 5.0))
    while n < 48:
        tid = list(tmap)[rng.integers(len(tmap))]
        p, R, _ = tmap[tid]
        nrm = R[:, 2]
        dist = rng.uniform(0.9, 3.2)
        for _ in range(100):
            d = rng.normal(size=3); d /= np.linalg.norm(d)
            if d @ nrm > math.cos(math.radians(65)): break
        eye = p + d * dist
        if not (0.3 < eye[2] < 3.5 and -2.2 < eye[0] < 4.0 and 0.3 < eye[1] < 7.0): continue  # stay inside the room (walls occlude)
        tgt = p + rng.normal(scale=0.4, size=3) * np.array([1, 1, 0.5])
        add(f'rand_{n:02d}', eye, tgt, rollDeg=float(rng.uniform(-180, 180)),
            light_scale=float(rng.uniform(0.5, 1.6)), light_shift=float(rng.uniform(-2.5, 2.5)))
        n += 1
    assert len(cases) == 100 and len({c['name'] for c in cases}) == 100, len(cases)
    return cases


def distortion_maps():
    K = K_matrix()
    u, v = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    pts = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2)
    und = cv2.undistortPoints(pts, K, DIST_TRUE, None, None, None,
                                  (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 30, 1e-10)).reshape(-1, 2)
    src_cx, src_cy = 1920 / 2 - 0.5, 1200 / 2 - 0.5
    mx = (und[:, 0] * FX + src_cx).reshape(H, W).astype(np.float32)
    my = (und[:, 1] * FY + src_cy).reshape(H, W).astype(np.float32)
    return mx, my


def sensor_model(bgr, rng):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 0.55)
    sig = np.sqrt(np.maximum(g, 1) * 0.35) + 1.5
    g = g + rng.normal(size=g.shape).astype(np.float32) * sig + 4
    return np.clip(g, 0, 255).astype(np.uint8)


def main():
    cases = make_cases()
    os.makedirs(os.path.join(IMG, 'raw'), exist_ok=True); os.makedirs(os.path.join(IMG, 'sensor'), exist_ok=True)
    only_new = [c for c in cases if not os.path.exists(os.path.join(IMG, 'raw', c['name'] + '.png'))]
    if only_new:
        cj = os.path.join(IMG, 'cases.json'); json.dump(only_new, open(cj, 'w'))
        subprocess.run([BLENDER, '-b', '-P', os.path.join(ROOT, 'tools', 'blender_render.py'), '--', cj,
                        os.path.join(IMG, 'raw')], check=True)
    mx, my = distortion_maps()
    tmap = load_tag_map(); rng = np.random.default_rng(1234)
    gt = {}
    K = K_matrix()
    for c in cases:
        raw = cv2.imread(os.path.join(IMG, 'raw', c['name'] + '.png'))
        und = cv2.remap(raw, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        img = sensor_model(und, rng)
        cv2.imwrite(os.path.join(IMG, 'sensor', c['name'] + '.png'), img)
        R = np.array(c['R_wc']); t = np.array(c['t_wc'])
        tags = {}
        for tid in tmap:
            cw = tag_corners_world(tmap, tid)
            px, z = project(cw, R, t, K, DIST_TRUE)
            nrm = tmap[tid][1][:, 2]; ctr = tmap[tid][0]
            facing = float(nrm @ (t - ctr)) > 0
            inimg = bool(np.all(z > 0.05) and np.all((px[:, 0] > 2) & (px[:, 0] < W - 3) & (px[:, 1] > 2) & (px[:, 1] < H - 3)))
            tags[str(tid)] = dict(corners=px.tolist(), visible=bool(facing and inimg),
                                  px_width=float(np.mean([np.linalg.norm(px[1] - px[0]), np.linalg.norm(px[2] - px[3])])))
        gt[c['name']] = dict(R_wc=R.tolist(), t_wc=t.tolist(), tags=tags, category=c['name'].split('_')[0])
    json.dump(dict(width=W, height=H, K=K.tolist(), dist=DIST_TRUE.tolist(), images=gt),
              open(os.path.join(IMG, 'ground_truth.json'), 'w'), indent=1)
    print('dataset ok:', len(gt), 'images')


if __name__ == '__main__':
    main()
