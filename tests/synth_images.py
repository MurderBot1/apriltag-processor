"""Synthetic frames for RTL / TPU tests (no Blender needed). Returns image + ground-truth tag corners."""
import numpy as np, cv2, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from make_tags import tag_image

def tag_scene(seed=0, ntags=3, noise=4.0, wall=150, smin=70, smax=160, rot=True):
    rng = np.random.default_rng(seed)
    img = np.full((800, 1280), wall, np.float32)
    img += cv2.GaussianBlur(rng.normal(size=img.shape).astype(np.float32), (0, 0), 40) * 400
    ids = rng.choice(587, ntags, replace=False)
    gt = []
    for k, tid in enumerate(ids):
        t = tag_image(int(tid)).astype(np.float32)
        t = 40 + t * (215 - 40) / 255.0
        s = rng.uniform(smin, smax)
        src = np.float32([[0, 0], [640, 0], [640, 640], [0, 640]])
        cx = 150 + (k % 3) * 360 + rng.uniform(-40, 40); cy = 180 + (k // 3) * 300 + rng.uniform(-40, 40)
        a = rng.uniform(0, 6.28) if rot else rng.uniform(-0.05, 0.05)
        sc = s / 640
        R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        dst = (R @ (src - 320).T).T * sc + [cx, cy] + rng.normal(scale=s * 0.04, size=(4, 2))
        Hm = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
        w = cv2.warpPerspective(t, Hm, (1280, 800), flags=cv2.INTER_AREA, borderValue=-1)
        m = cv2.warpPerspective(np.full_like(t, 1), Hm, (1280, 800), flags=cv2.INTER_NEAREST) > 0
        img[m] = w[m]
        # outer black square = 8 cells of 64 px starting at 64 (cell edges at 63.5 / 575.5 in pixel-centre coords)
        q = np.float32([[63.5, 63.5], [575.5, 63.5], [575.5, 575.5], [63.5, 575.5]]).reshape(-1, 1, 2)
        gt.append(dict(id=int(tid), corners=cv2.perspectiveTransform(q, Hm).reshape(4, 2)))
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    img += rng.normal(size=img.shape) * noise
    return np.clip(img, 0, 255).astype(np.uint8), gt
