"""Extend the test-image dataset from 100 to 500 frames (the original 100 are never re-rendered or touched).

  py -3.12 tools/make_dataset_500.py            # generate cases -> render missing frames (Blender, GPU) -> sensor model -> ground truth
  py -3.12 tools/make_dataset_500.py --gen      # only (re)write test_images/cases_500.json
  py -3.12 tools/make_dataset_500.py --gt       # only rebuild ground_truth.json from the frames that exist
  options: --limit N (render at most N frames this run)  --batch N (frames per Blender process, default 40)  --cpu

Resumable: a frame whose test_images/raw/<name>.png exists is skipped; raw frames are written atomically.  Progress -> results/dataset_500.log.
Deterministic: cases come from numpy seeds (CASE_SEED + category index) and are cached in cases_500.json; sensor noise of frame k uses
SeedSequence([SENSOR_SEED, k]).  New frames are named <category>_x###; category = name.split('_')[0] as before.
New categories vs the original 100: pitch occl edge shadow glare clutter."""
import os, sys, json, math, time, subprocess, argparse
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import *
from dataset_gt import tag_geometry, image_stats, apply_image_reasons, segment_hits, tag_samples, DETECT
import make_dataset as md

CASE_SEED, SENSOR_SEED = 20261028, 20261029
IMG = md.IMG
LOG = os.path.join(ROOT, 'results', 'dataset_500.log')
CASES_500 = os.path.join(IMG, 'cases_500.json')
ROOM_X, ROOM_Y, ROOM_Z = (-2.3, 4.2), (0.35, 7.4), (0.25, 4.6)
COUNTS = dict(dist=35, yaw=35, pitch=15, roll=35, dark=20, bright=20, grad=20, shadow=25, glare=20, side=15, floor=15,
              occl=35, edge=25, clutter=25, rand=52, empty=8)
assert sum(COUNTS.values()) == 400


def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a') as f: f.write(line + '\n')


# ------------------------------------------------------------------ helpers
def in_room(e, margin=0.0):
    return (ROOM_X[0] + margin < e[0] < ROOM_X[1] - margin and ROOM_Y[0] + margin < e[1] < ROOM_Y[1] - margin and ROOM_Z[0] < e[2] < ROOM_Z[1])


def unit(v): v = np.asarray(v, float); return v / np.linalg.norm(v)


def rot_about_z(a):
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1.0]])


def box(center, size, R, albedo):
    return dict(kind='box', center=[float(x) for x in center], size=[float(x) for x in size], R=np.asarray(R, float).tolist(), albedo=float(albedo))


def sphere(center, r, albedo):
    return dict(kind='sphere', center=[float(x) for x in center], size=[float(r)] * 3, R=np.eye(3).tolist(), albedo=float(albedo))


def point_in_occluder(p, ocs, pad=0.12):
    for oc in ocs:
        c = np.array(oc['center'])
        if oc['kind'] == 'sphere':
            if np.linalg.norm(p - c) < oc['size'][0] + pad: return True
        else:
            lp = np.array(oc['R']).T @ (p - c)
            if np.all(np.abs(lp) < np.array(oc['size']) / 2 + pad): return True
    return False


def clutter(rng, n, eye):
    ocs = []
    for _ in range(n):
        for _ in range(20):
            alb = float(rng.uniform(0.05, 0.9))
            if rng.random() < 0.65:
                s = (rng.uniform(0.1, 0.5), rng.uniform(0.1, 0.5), rng.uniform(0.1, 0.9))
                c = np.array([rng.uniform(-2.2, 4.0), rng.uniform(0.15, 5.5), s[2] / 2 if rng.random() < 0.7 else rng.uniform(0.3, 2.5)])
                oc = box(c, s, rot_about_z(rng.uniform(0, math.pi)), alb)
            else:
                r = rng.uniform(0.07, 0.3)
                c = np.array([rng.uniform(-2.2, 4.0), rng.uniform(0.15, 5.5), r if rng.random() < 0.7 else rng.uniform(0.3, 2.5)])
                oc = sphere(c, r, alb)
            if not point_in_occluder(eye, [oc], pad=0.35):
                ocs.append(oc); break
    return ocs


def rand_bg(rng, p=0.3, force=False):
    if not force and rng.random() > p: return None
    kind = str(rng.choice(['dark', 'light', 'checker', 'stripes', 'busy', 'brick']))
    sc = dict(dark=1, light=1, checker=rng.uniform(4, 14), stripes=rng.uniform(3, 10), busy=rng.uniform(20, 80), brick=rng.uniform(2, 5))[kind]
    fl = str(rng.choice(['default', 'checker', 'busy', 'dark', 'light'])) if kind != 'dark' else 'default'
    return dict(kind=kind, scale=float(sc), floor_kind=fl)


def aim_at_tag(rng, tmap, tid, dist, max_ang, min_ang=0.0):
    p, R, _ = tmap[tid]; nrm = R[:, 2]
    for _ in range(200):
        d = unit(rng.normal(size=3))
        a = math.degrees(math.acos(max(-1, min(1, d @ nrm))))
        if min_ang <= a <= max_ang:
            eye = p + d * dist
            if in_room(eye, 0.1): return eye, p + rng.normal(scale=0.12, size=3) * np.array([1, 1, 0.5])
    return None, None


def walltags(tmap): return [t for t in tmap if abs(tmap[t][1][1, 2]) > 0.9]
def sidetags(tmap): return [t for t in tmap if abs(tmap[t][1][0, 2]) > 0.9]
def floortags(tmap): return [t for t in tmap if abs(tmap[t][1][2, 2]) > 0.9]


def pose_with_center_at(eye, center, uv, rollDeg):
    """camera->world rotation that looks at `center` but puts it at the DISTORTED pixel uv"""
    R0 = roll(look_at(eye, center), rollDeg)
    K = K_matrix()
    n = cv2.undistortPoints(np.array([[uv]], np.float64), K, DIST_TRUE).reshape(2)
    dc = unit([n[0], n[1], 1.0])
    ax = np.cross(dc, [0, 0, 1.0]); s = np.linalg.norm(ax)
    if s < 1e-9: return R0
    Rot, _ = cv2.Rodrigues(ax / s * math.acos(dc[2]))
    return R0 @ Rot


# ------------------------------------------------------------------ per-category generators.  Each returns a partial case or None
def base_light(rng):
    return dict(light_scale=float(rng.uniform(0.7, 1.4)), light_shift=float(rng.uniform(-1.5, 1.5)))


def finish(rng, c, eye, R, p_bg=0.3, p_clutter=0.35, level=(2, 8)):
    c['R_wc'] = np.asarray(R).tolist(); c['t_wc'] = [float(x) for x in eye]
    if 'bg' not in c: c['bg'] = rand_bg(rng, p_bg)
    if c['bg'] is None: del c['bg']
    c.setdefault('occluders', [])
    if rng.random() < p_clutter: c['occluders'] = c['occluders'] + clutter(rng, int(rng.integers(level[0], level[1] + 1)), eye)
    return c


def gen_dist(rng, i, tm):
    d = float(np.exp(rng.uniform(math.log(0.5), math.log(4.6))))
    tgt = np.array(tm[int(rng.choice(walltags(tm)))][0]) + rng.normal(scale=0.12 if d < 1.2 else 0.5, size=3) * np.array([1, 0, 0.6])
    eye = np.array([tgt[0] + rng.normal(scale=0.25), d, tgt[2] + rng.normal(scale=0.2)])
    if not in_room(eye): return None
    return finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(rng.choice([0, 0, 0, rng.uniform(-12, 12)]))))


def gen_yaw(rng, i, tm):
    a = float(rng.choice([-1, 1]) * (rng.uniform(76, 86) if i % 7 == 6 else rng.uniform(8, 76)))
    d = float(rng.uniform(1.0, 3.2)); pitch = math.radians(rng.uniform(-18, 18))
    tgt = np.array(tm[int(rng.choice(walltags(tm)))][0]) + rng.normal(scale=0.2, size=3) * np.array([1, 0, 0.5])
    eye = tgt + np.array([d * math.cos(pitch) * math.sin(math.radians(a)), d * math.cos(pitch) * math.cos(math.radians(a)), d * math.sin(pitch)])
    if not in_room(eye, 0.1): return None
    c = finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(rng.uniform(-8, 8))))
    c['allow_none'] = abs(a) > 76
    return c


def gen_pitch(rng, i, tm):
    d = float(rng.uniform(1.0, 3.0)); pitch = math.radians(rng.choice([-1, 1]) * rng.uniform(20, 62))
    tgt = np.array(tm[int(rng.choice(walltags(tm)))][0]) + rng.normal(scale=0.2, size=3) * np.array([1, 0, 0.5])
    yaw = math.radians(rng.uniform(-35, 35))
    eye = tgt + np.array([d * math.cos(pitch) * math.sin(yaw), d * math.cos(pitch) * math.cos(yaw), d * math.sin(pitch)])
    if not in_room(eye, 0.1): return None
    return finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(rng.uniform(-10, 10))))


def gen_roll(rng, i, tm):
    d = float(rng.uniform(0.9, 3.0)); r = -180 + 360 * ((i + rng.random()) / COUNTS['roll'])
    tgt = np.array([rng.uniform(-0.8, 0.8), 0, rng.uniform(0.9, 1.5)])
    eye = np.array([tgt[0] + rng.uniform(-0.8, 0.8), d, tgt[2] + rng.uniform(-0.4, 0.4)])
    if not in_room(eye): return None
    c = finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(r)))
    return c


def gen_dark(rng, i, tm):
    d = float(rng.uniform(1.0, 3.0)); tgt = np.array([rng.uniform(-0.8, 0.8), 0, rng.uniform(0.9, 1.5)])
    eye = np.array([tgt[0] + rng.uniform(-0.8, 0.8), d, tgt[2] + rng.uniform(-0.4, 0.4)])
    c = dict(light_scale=float(np.exp(rng.uniform(math.log(0.02), math.log(0.25)))), light_shift=float(rng.uniform(-2, 2)))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-30, 30))))


def gen_bright(rng, i, tm):
    d = float(rng.uniform(1.0, 3.2)); tgt = np.array([rng.uniform(-0.8, 0.8), 0, rng.uniform(0.9, 1.5)])
    eye = np.array([tgt[0] + rng.uniform(-0.8, 0.8), d, tgt[2] + rng.uniform(-0.4, 0.4)])
    c = dict(light_scale=float(np.exp(rng.uniform(math.log(2.0), math.log(7.0)))), light_shift=float(rng.uniform(-2, 2)))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-30, 30))))


def gen_grad(rng, i, tm):
    d = float(rng.uniform(1.2, 3.0)); tgt = np.array([rng.uniform(-0.5, 0.5), 0, rng.uniform(0.9, 1.5)])
    eye = np.array([tgt[0] + rng.uniform(-0.8, 0.8), d, tgt[2] + rng.uniform(-0.4, 0.4)])
    c = dict(light_scale=float(rng.uniform(0.4, 1.5)), light_shift=float(rng.choice([-1, 1]) * rng.uniform(2.5, 5.5)))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-20, 20))))


def gen_shadow(rng, i, tm):
    tid = int(rng.choice(walltags(tm) + sidetags(tm) + floortags(tm)))
    p, R, _ = tm[tid]
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(1.0, 2.8)), 55)
    if eye is None: return None
    lp = p + R[:, 2] * rng.uniform(1.4, 2.6) + R[:, 0] * rng.uniform(-1.5, 1.5) + R[:, 1] * rng.uniform(0.2, 1.4) * (1 if R[2, 1] > 0.5 else 1)
    if not in_room(lp, 0.1): return None
    f = rng.uniform(0.35, 0.75); sc = (lp + (p - lp) * f)
    s = (rng.uniform(0.2, 0.5), rng.uniform(0.2, 0.5), rng.uniform(0.02, 0.2))
    oc = box(sc + rng.normal(scale=0.03, size=3), s, rot_about_z(rng.uniform(0, math.pi)) @ cv2.Rodrigues(rng.normal(scale=0.5, size=3))[0], rng.uniform(0.05, 0.6))
    c = dict(light_scale=float(rng.uniform(0.12, 0.45)), light_shift=0.0,
             spot=dict(pos=[float(x) for x in lp], target=[float(x) for x in p], energy=float(rng.uniform(10, 40)), size=0.04),
             occluders=[oc], spot_tag=tid)
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-25, 25))), p_clutter=0.2)


def gen_glare(rng, i, tm):
    tid = int(rng.choice(walltags(tm) + walltags(tm) + sidetags(tm) + floortags(tm)))
    p, R, _ = tm[tid]; n = R[:, 2]
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(1.0, 2.8)), 50, min_ang=12)
    if eye is None: return None
    v = unit(eye - p); r = 2 * (n @ v) * n - v
    lp = p + r * rng.uniform(1.3, 2.5) + rng.normal(scale=float(rng.uniform(0.15, 0.8)), size=3)
    if not in_room(lp, 0.1): return None
    c = dict(light_scale=float(rng.uniform(0.5, 1.2)), light_shift=0.0, tag_rough=float(rng.uniform(0.12, 0.32)),
             glare=dict(pos=[float(x) for x in lp], target=[float(x) for x in p], energy=float(rng.uniform(25, 100)), size=0.2),
             veil=float(rng.choice([0.0, rng.uniform(0.3, 0.9)])), glare_tag=tid)
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-25, 25))), p_clutter=0.2)


def gen_side(rng, i, tm):
    tid = int(rng.choice(sidetags(tm)))
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(0.8, 3.2)), 80)
    if eye is None: return None
    return finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(rng.uniform(-90, 90))))


def gen_floor(rng, i, tm):
    tid = int(rng.choice(floortags(tm)))
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(0.8, 3.4)), 80)
    if eye is None: return None
    return finish(rng, base_light(rng), eye, roll(look_at(eye, tgt), float(rng.uniform(-180, 180))))


def gen_occl(rng, i, tm):
    tid = int(rng.choice(list(tm))); p, R, s = tm[tid]
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(1.0, 2.8)), 55)
    if eye is None: return None
    st = float(rng.uniform(0.04, 0.35)); h = s / 2
    off = R[:, 0] * rng.uniform(-1.5, 1.5) * h + R[:, 1] * rng.uniform(-1.5, 1.5) * h
    cen = p + R[:, 2] * st + off
    if rng.random() < 0.7:
        sz = (rng.uniform(0.07, 0.3), rng.uniform(0.07, 0.3), rng.uniform(0.02, 0.08))
        Rm = R @ rot_about_z(rng.uniform(-0.6, 0.6))
        oc = box(cen, sz, Rm, rng.uniform(0.05, 0.9))
    else:
        oc = sphere(cen, rng.uniform(0.04, 0.11), rng.uniform(0.05, 0.9))
    c = dict(base_light(rng), occluders=[oc], occl_tag=tid, occl_want_over_half=bool(i % 4 == 3))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-40, 40))), p_clutter=0.25)


def gen_edge(rng, i, tm):
    tid = int(rng.choice(list(tm))); p, R, s = tm[tid]
    eye, _ = aim_at_tag(rng, tm, tid, float(rng.uniform(1.0, 3.0)), 55)
    if eye is None: return None
    e = rng.uniform(15, 75) if i % 2 == 0 else rng.uniform(-10, 14)
    side = int(rng.integers(4))
    u0, v0 = rng.uniform(80, W - 80), rng.uniform(60, H - 60)
    uv = [(e, v0), (W - 1 - e, v0), (u0, e), (u0, H - 1 - e)][side]
    Rcam = pose_with_center_at(eye, p, uv, float(rng.uniform(-40, 40)))
    c = finish(rng, base_light(rng), eye, Rcam)
    c['edge_mode'] = 'inside' if i % 2 == 0 else 'cut'
    return c


def gen_clutter(rng, i, tm):
    d = float(rng.uniform(1.2, 3.2)); tgt = np.array([rng.uniform(-0.8, 0.8), 0, rng.uniform(0.9, 1.5)])
    eye = np.array([tgt[0] + rng.uniform(-1.0, 1.0), d, tgt[2] + rng.uniform(-0.5, 0.5)])
    if not in_room(eye): return None
    level = [(3, 6), (7, 12), (13, 22)][i % 3]
    c = dict(base_light(rng), bg=rand_bg(rng, force=True), clutter_level=i % 3 + 1)
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-30, 30))), p_clutter=1.0, level=level)


def gen_rand(rng, i, tm):
    tid = int(rng.choice(list(tm)))
    eye, tgt = aim_at_tag(rng, tm, tid, float(rng.uniform(0.9, 3.2)), 65)
    if eye is None or not (0.3 < eye[2] < 3.5): return None
    c = dict(light_scale=float(rng.uniform(0.5, 1.6)), light_shift=float(rng.uniform(-2.5, 2.5)))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-180, 180))), p_bg=0.3, p_clutter=0.3)


def gen_empty(rng, i, tm):
    eye = np.array([rng.uniform(-1.5, 3.5), rng.uniform(1.0, 5.0), rng.uniform(0.6, 2.2)])
    ang = rng.uniform(0, 2 * math.pi)
    # look away from the tag wall / tags: toward +y, +x, up, down-at-clean-floor
    kind = i % 4
    tgt = [eye + [rng.uniform(-3, 3), 6, rng.uniform(-1, 1)], eye + [6, rng.uniform(-3, 3), rng.uniform(-1, 1)],
           eye + [rng.uniform(-1, 1), 0.5, 6], eye + [rng.uniform(1, 3), rng.uniform(1, 3), -eye[2]]][kind]
    c = dict(base_light(rng), bg=rand_bg(rng, force=True))
    return finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-90, 90))), p_clutter=1.0, level=(2, 10))


GENS = dict(dist=gen_dist, yaw=gen_yaw, pitch=gen_pitch, roll=gen_roll, dark=gen_dark, bright=gen_bright, grad=gen_grad, shadow=gen_shadow,
            glare=gen_glare, side=gen_side, floor=gen_floor, occl=gen_occl, edge=gen_edge, clutter=gen_clutter, rand=gen_rand, empty=gen_empty)


def accept(c, cat, geo):
    ocs = c.get('occluders', [])
    eye = np.array(c['t_wc'])
    if not in_room(eye, 0.05) or point_in_occluder(eye, ocs, pad=0.1): return False
    vis = [g for g in geo.values() if g['visible']]
    det = [g for g in geo.values() if g['detectable']]
    if cat == 'empty': return len(vis) == 0
    if cat == 'edge':
        if c['edge_mode'] == 'inside': return any(g['detectable'] and 0 < g['edge_dist_px'] <= 40 for g in geo.values())
        return any(g['facing'] and not g['in_frame'] and 0.25 < g['vis_fraction'] < 0.95 for g in geo.values()) and len(det) >= 0
    if cat == 'occl':
        o = geo[str(c['occl_tag'])]
        if not (o['facing'] and o['in_frame']): return False
        return (0.55 < o['occ_fraction'] < 0.97) if c['occl_want_over_half'] else (0.08 < o['occ_fraction'] <= 0.5)
    if cat == 'shadow':
        sp = np.array(c['spot']['pos']); g = geo[str(c['spot_tag'])]
        sf = segment_hits(sp, tag_samples(load_tag_map(), c['spot_tag']), ocs).mean()
        return g['detectable'] and 0.1 < sf < 0.9
    if cat == 'glare':
        return geo[str(c['glare_tag'])]['detectable']
    if cat == 'yaw' and c.get('allow_none'): return len(vis) >= 1
    return len(det) >= 1


def make_cases_ext():
    tm = load_tag_map(); K = K_matrix(); out = []
    old = {c['name'] for c in md.make_cases()}
    for ci, (cat, n) in enumerate(COUNTS.items()):
        rng = np.random.default_rng([CASE_SEED, ci]); i = 0; tries = 0
        while i < n:
            tries += 1
            assert tries < 20000, f'cannot generate {cat}'
            c = GENS[cat](rng, i, tm)
            if c is None: continue
            geo = tag_geometry(np.array(c['R_wc']), np.array(c['t_wc']), tm, K, DIST_TRUE, c.get('occluders', []))
            if not accept(c, cat, geo): continue
            c['name'] = f'{cat}_x{i:03d}'; c['category'] = cat; assert c['name'] not in old
            c['seed'] = len(out)
            out.append(c); i += 1
    assert len(out) == 400
    return out


def load_cases_ext(regen=False):
    if os.path.exists(CASES_500) and not regen:
        return json.load(open(CASES_500))
    c = make_cases_ext(); json.dump(c, open(CASES_500, 'w'))
    log(f'generated {len(c)} extension cases -> {CASES_500}')
    # site/gallery reads light_scale / light_shift per frame from cases.json: append (keeps the existing entries)
    cj = os.path.join(IMG, 'cases.json'); cur = json.load(open(cj)); have = {x['name'] for x in cur}
    json.dump(cur + [dict(name=x['name'], R_wc=x['R_wc'], t_wc=x['t_wc'], light_scale=x['light_scale'], light_shift=x['light_shift']) for x in c if x['name'] not in have], open(cj, 'w'))
    return c


# ------------------------------------------------------------------ render + sensor
def render_pending(cases, batch, use_gpu, limit):
    raw = os.path.join(IMG, 'raw'); os.makedirs(raw, exist_ok=True)
    pend = [c for c in cases if not os.path.exists(os.path.join(raw, c['name'] + '.png'))]
    log(f'{len(cases) - len(pend)}/{len(cases)} raw frames present, {len(pend)} pending' + (f', limit {limit}' if limit else ''))
    if limit: pend = pend[:limit]
    maps = None; t0 = time.time(); done = 0
    for b in range(0, len(pend), batch):
        chunk = pend[b:b + batch]
        cj = os.path.join(IMG, 'cases_batch.json'); json.dump(chunk, open(cj, 'w'))
        for attempt, dev in enumerate(['HIP', 'HIP', 'CPU'] if use_gpu else ['CPU']):
            env = dict(os.environ, RENDER_DEVICE=dev)
            t1 = time.time()
            with open(LOG, 'a') as lf:
                r = subprocess.run([md.BLENDER, '-b', '-P', os.path.join(ROOT, 'tools', 'blender_render.py'), '--', cj, raw], env=env, stdout=lf, stderr=subprocess.STDOUT)
            ok = all(os.path.exists(os.path.join(raw, c['name'] + '.png')) for c in chunk)
            log(f'batch {b // batch + 1}/{math.ceil(len(pend) / batch)} ({chunk[0]["name"]}..{chunk[-1]["name"]}) device={dev} rc={r.returncode} ok={ok} {time.time() - t1:.0f}s')
            if ok: break
        else:
            raise SystemExit('render failed')
        done += len(chunk)
        if maps is None: maps = md.distortion_maps()
        make_sensor(chunk, maps)
        el = time.time() - t0
        log(f'progress {done}/{len(pend)} frames; elapsed {el:.0f}s; eta {el / done * (len(pend) - done):.0f}s')
    os.path.exists(os.path.join(IMG, 'cases_batch.json')) and os.remove(os.path.join(IMG, 'cases_batch.json'))


def sensor_img(c, maps):
    raw = cv2.imread(os.path.join(IMG, 'raw', c['name'] + '.png'))
    und = cv2.remap(raw, maps[0], maps[1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if c.get('veil'):                      # veiling glare: bloom of the saturated highlights (lens flare / sensor blooming)
        g = cv2.cvtColor(und, cv2.COLOR_BGR2GRAY).astype(np.float32)
        v = cv2.GaussianBlur(np.maximum(g - 200, 0), (0, 0), 28) * float(c['veil']) * 2.5
        und = np.clip(und.astype(np.float32) + v[..., None], 0, 255).astype(np.uint8)
    rng = np.random.default_rng(np.random.SeedSequence([SENSOR_SEED, int(c['seed'])]))
    return md.sensor_model(und, rng)


def make_sensor(cases, maps):
    for c in cases:
        out = os.path.join(IMG, 'sensor', c['name'] + '.png')
        if os.path.exists(out) or not os.path.exists(os.path.join(IMG, 'raw', c['name'] + '.png')): continue
        cv2.imwrite(out, sensor_img(c, maps))


# ------------------------------------------------------------------ ground truth
def build_gt(cases):
    K = K_matrix(); tm = load_tag_map()
    G = json.load(open(os.path.join(IMG, 'ground_truth.json')))
    old = {k: v for k, v in G['images'].items() if v.get('source', 'orig100') == 'orig100'}
    assert len(old) == 100, len(old)
    out = {}
    sens = lambda n: cv2.imread(os.path.join(IMG, 'sensor', n + '.png'), cv2.IMREAD_GRAYSCALE)
    for name, g in old.items():            # additive back-fill of the new per-tag fields; legacy fields must come out identical
        geo = tag_geometry(np.array(g['R_wc']), np.array(g['t_wc']), tm, K, DIST_TRUE, [])
        im = sens(name)
        for tid, t in g['tags'].items():
            n = geo[tid]
            assert n['visible'] == t['visible'] and np.allclose(n['corners'], t['corners'], atol=1e-6) and abs(n['px_width'] - t['px_width']) < 1e-6, (name, tid)
            t.update({k: v for k, v in n.items() if k not in ('corners', 'visible', 'px_width')})
            t.update(image_stats(im, t['corners']) if t['facing'] and n['px_width'] > 3 else dict(sat_frac=None, contrast=None, mean_level=None))
            apply_image_reasons(t)
        g['source'] = 'orig100'; g['n_visible'] = sum(t['visible'] for t in g['tags'].values()); g['n_detectable'] = sum(t['detectable'] for t in g['tags'].values())
        out[name] = g
    for c in cases:
        if not os.path.exists(os.path.join(IMG, 'sensor', c['name'] + '.png')): continue
        R = np.array(c['R_wc']); t = np.array(c['t_wc']); ocs = c.get('occluders', [])
        geo = tag_geometry(R, t, tm, K, DIST_TRUE, ocs); im = sens(c['name'])
        for tid, n in geo.items():
            n.update(image_stats(im, n['corners']) if n['facing'] and n['px_width'] > 3 else dict(sat_frac=None, contrast=None, mean_level=None))
            apply_image_reasons(n)
        sp = c.get('spot')
        if sp:
            for tid in geo:
                geo[tid]['shadow_fraction'] = round(float(segment_hits(np.array(sp['pos']), tag_samples(tm, int(tid)), ocs).mean()), 4) if geo[tid]['facing'] else None
        out[c['name']] = dict(R_wc=R.tolist(), t_wc=t.tolist(), quat_wxyz=[float(x) for x in R_to_quat(R)], tags=geo, category=c['category'], source='ext400',
                              seed=c['seed'], n_visible=sum(n['visible'] for n in geo.values()), n_detectable=sum(n['detectable'] for n in geo.values()),
                              lighting=dict(light_scale=c['light_scale'], light_shift=c['light_shift'], spot=c.get('spot'), glare=c.get('glare'),
                                            tag_roughness=c.get('tag_rough', 0.85), veil=c.get('veil', 0.0)),
                              background=c.get('bg') or dict(kind='default'), n_occluders=len(ocs), occluders=ocs,
                              notes={k: c[k] for k in ('edge_mode', 'occl_tag', 'clutter_level', 'allow_none') if k in c})
    names = sorted(out)
    G2 = dict(schema=2, width=W, height=H, K=K.tolist(), dist=DIST_TRUE.tolist(), detectability=DETECT,
              note='visible = facing camera and all 4 corners inside the frame (legacy). detectable = visible and px_width>=10 and incidence<=75deg and occ_fraction<=0.5.',
              images={n: out[n] for n in names})
    tmp = os.path.join(IMG, 'ground_truth.json.tmp'); json.dump(G2, open(tmp, 'w'), indent=1); os.replace(tmp, os.path.join(IMG, 'ground_truth.json'))
    log(f'ground truth written: {len(out)} images')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gen', action='store_true'); ap.add_argument('--gt', action='store_true'); ap.add_argument('--regen', action='store_true')
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--batch', type=int, default=40); ap.add_argument('--cpu', action='store_true')
    a = ap.parse_args()
    cases = load_cases_ext(a.regen)
    if a.gen: return
    if not a.gt:
        render_pending(cases, a.batch, not a.cpu, a.limit)
        make_sensor(cases, md.distortion_maps())
    build_gt(cases)
    log('done')


if __name__ == '__main__':
    main()
