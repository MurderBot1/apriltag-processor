"""Build the 100-image test dataset: 10 categories x 10 images, each category a distinct imaging condition.

  py tools/make_dataset_100.py            # cases -> Blender renders (missing only) -> lens distortion + sensor model -> ground truth
  py tools/make_dataset_100.py --gen      # only (re)write test_images/cases.json
  py tools/make_dataset_100.py --gt       # only rebuild ground_truth.json from the sensor frames that exist
  options: --regen (ignore cached cases.json)  --batch N (frames per Blender process, default 25)  --cpu (no GPU)  --limit N

Categories (name = <category>_<000..009>, category = name.split('_')[0]):
  normal    clean baseline: nominal light, plain background, distance 0.8 .. 3.8 m (log-spaced, one per frame), tiny roll
  bright    over-exposed: light x2 .. x5.5 (some tags near saturation)
  dark      under-exposed: light x0.03 .. x0.25
  lowcon    low contrast: nominal scene, sensor-side contrast compressed to 24 % .. 42 % around mid-grey
  grad      uneven illumination: strong left/right light gradient (|shift| 2.5 .. 5.5 either sign)
  shadow    harsh shadow: one spot light, an occluder casts a hard shadow across a tag (10 .. 90 % shadowed)
  noise     high sensor noise: noise sigma x2 .. x4.5 of the nominal OV9281 model
  clutter   busy background + 3 .. 22 random boxes/spheres (3 levels), textured walls/floor
  blur      defocus / motion blur: extra Gaussian blur sigma 1.0 .. 3.0 px on top of the nominal 0.55 px, tags 0.9 .. 2.2 m away
  persp     perspective: tag plane tilted 15 .. 74 deg, alternating yaw / pitch, either sign, 1.2 .. 3.0 m

Deterministic: case k of category c uses numpy Generator([CASE_SEED, c_index]) with rejection sampling (documented accept rules
below); per-frame stratified parameters (distance, noise gain, blur, ...) are linspace over the 10 frames; sensor noise of frame
`seed` uses SeedSequence([SENSOR_SEED, seed]).  Blender renders use the fixed seed set in tools/blender_render.py, so re-running
reproduces the committed frames up to GPU float determinism (the committed test_images/sensor/*.png + ground_truth.json are the
reference; tests never need Blender).  Raw 1920x1200 renders go to test_images/raw (git-ignored)."""
import os, sys, json, math, time, subprocess, argparse
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import *
from dataset_gt import tag_geometry, image_stats, apply_image_reasons, segment_hits, tag_samples, DETECT
import make_dataset as md
import make_dataset_500 as m5          # reuse the case-generation helpers (rooms, clutter, shadow / pose builders)

CASE_SEED, SENSOR_SEED = 20261030, 20261031
IMG = md.IMG
CASES = os.path.join(IMG, 'cases.json')
LOG = os.path.join(ROOT, 'results', 'dataset_100.log')
N_PER = 10
CATS = ['normal', 'bright', 'dark', 'lowcon', 'grad', 'shadow', 'noise', 'clutter', 'blur', 'persp']
SENSOR_DEFAULT = dict(blur=0.0, noise_gain=1.0, contrast=1.0)


def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a') as f: f.write(line + '\n')


def lin(a, b, i): return float(a + (b - a) * i / (N_PER - 1))


def wall_target(rng, tm, spread=0.2):
    return np.array(tm[int(rng.choice(m5.walltags(tm)))][0]) + rng.normal(scale=spread, size=3) * np.array([1, 0, 0.5])


def front_view(rng, tm, d, light, p_clutter=0.0, p_bg=0.0, roll_deg=None, lateral=0.25):
    """camera at distance d in front of a random wall tag, looking at it"""
    tgt = wall_target(rng, tm)
    eye = np.array([tgt[0] + rng.normal(scale=lateral), d, tgt[2] + rng.normal(scale=0.2)])
    if not m5.in_room(eye): return None
    r = float(rng.uniform(-8, 8)) if roll_deg is None else roll_deg
    return m5.finish(rng, dict(light), eye, roll(look_at(eye, tgt), r), p_bg=p_bg, p_clutter=p_clutter)


def g_normal(rng, i, tm):
    return front_view(rng, tm, float(np.exp(lin(math.log(0.8), math.log(3.8), i))), dict(light_scale=1.0, light_shift=0.0))


def g_bright(rng, i, tm):
    return front_view(rng, tm, float(rng.uniform(1.0, 3.0)), dict(light_scale=lin(2.0, 5.5, i), light_shift=float(rng.uniform(-1, 1))), roll_deg=float(rng.uniform(-20, 20)))


def g_dark(rng, i, tm):
    ls = float(np.exp(lin(math.log(0.25), math.log(0.03), i)))
    return front_view(rng, tm, float(rng.uniform(1.0, 2.6)), dict(light_scale=ls, light_shift=float(rng.uniform(-1, 1))), roll_deg=float(rng.uniform(-20, 20)))


def g_lowcon(rng, i, tm):
    c = front_view(rng, tm, float(rng.uniform(1.0, 2.6)), dict(light_scale=1.0, light_shift=0.0))
    if c: c['sensor'] = dict(contrast=lin(0.42, 0.24, i))
    return c


def g_grad(rng, i, tm):
    sh = (1 if i % 2 == 0 else -1) * lin(2.5, 5.5, i)
    return front_view(rng, tm, float(rng.uniform(1.2, 2.8)), dict(light_scale=float(rng.uniform(0.6, 1.2)), light_shift=sh), roll_deg=float(rng.uniform(-15, 15)))


def g_noise(rng, i, tm):
    c = front_view(rng, tm, float(rng.uniform(1.0, 2.4)), dict(light_scale=1.0, light_shift=0.0))
    if c: c['sensor'] = dict(noise_gain=lin(2.0, 4.5, i))
    return c


def g_blur(rng, i, tm):
    c = front_view(rng, tm, float(rng.uniform(0.9, 2.2)), dict(light_scale=1.0, light_shift=0.0))
    if c: c['sensor'] = dict(blur=lin(1.0, 3.0, i))
    return c


def g_clutter(rng, i, tm):
    d = float(rng.uniform(1.2, 3.0)); tgt = wall_target(rng, tm, 0.3)
    eye = np.array([tgt[0] + rng.uniform(-1.0, 1.0), d, tgt[2] + rng.uniform(-0.5, 0.5)])
    if not m5.in_room(eye): return None
    level = [(3, 6), (7, 12), (13, 22)][i % 3]
    c = dict(light_scale=1.0, light_shift=0.0, bg=m5.rand_bg(rng, force=True), clutter_level=i % 3 + 1)
    return m5.finish(rng, c, eye, roll(look_at(eye, tgt), float(rng.uniform(-30, 30))), p_clutter=1.0, level=level)


def g_persp(rng, i, tm):
    a = lin(15, 74, i); sgn = 1 if (i // 2) % 2 == 0 else -1
    d = float(rng.uniform(1.2, 3.0)); tgt = wall_target(rng, tm)
    small = math.radians(rng.uniform(-10, 10))
    ang = math.radians(sgn * a)
    if i % 2 == 0:      # yaw: camera swings sideways around the tag
        off = np.array([d * math.cos(small) * math.sin(ang), d * math.cos(small) * math.cos(ang), d * math.sin(small)])
    else:               # pitch: camera above / below
        off = np.array([d * math.sin(small), d * math.cos(ang), d * math.sin(ang)])
    eye = tgt + off
    if not m5.in_room(eye, 0.1): return None
    return m5.finish(rng, dict(light_scale=1.0, light_shift=0.0), eye, roll(look_at(eye, tgt), float(rng.uniform(-8, 8))), p_bg=0.0, p_clutter=0.0)


GENS = dict(normal=g_normal, bright=g_bright, dark=g_dark, lowcon=g_lowcon, grad=g_grad, shadow=m5.gen_shadow,
            noise=g_noise, clutter=g_clutter, blur=g_blur, persp=g_persp)


def accept(c, cat, geo):
    eye = np.array(c['t_wc']); ocs = c.get('occluders', [])
    if not m5.in_room(eye, 0.05) or m5.point_in_occluder(eye, ocs, pad=0.1): return False
    det = [g for g in geo.values() if g['detectable']]
    if cat == 'shadow': return m5.accept(c, 'shadow', geo)
    if cat in ('lowcon', 'noise', 'blur'):      # degraded after rendering: need at least one tag that is comfortably large
        return any(g['detectable'] and g['px_width'] >= 40 for g in geo.values())
    return len(det) >= 1


def make_cases():
    tm = load_tag_map(); K = K_matrix(); out = []
    for ci, cat in enumerate(CATS):
        rng = np.random.default_rng([CASE_SEED, ci]); i = 0; tries = 0
        while i < N_PER:
            tries += 1
            assert tries < 20000, f'cannot generate {cat}'
            c = GENS[cat](rng, i, tm)
            if c is None: continue
            geo = tag_geometry(np.array(c['R_wc']), np.array(c['t_wc']), tm, K, DIST_TRUE, c.get('occluders', []))
            if not accept(c, cat, geo): continue
            c['name'] = f'{cat}_{i:03d}'; c['category'] = cat; c['seed'] = len(out)
            c['sensor'] = dict(SENSOR_DEFAULT, **c.get('sensor', {}))
            out.append(c); i += 1
    assert len(out) == 100 and len({c['name'] for c in out}) == 100
    return out


def load_cases(regen=False):
    if os.path.exists(CASES) and not regen:
        return json.load(open(CASES))
    c = make_cases(); json.dump(c, open(CASES, 'w'))
    log(f'generated {len(c)} cases -> {CASES}')
    return c


# ------------------------------------------------------------------ render + sensor
def sensor_img(c, maps):
    raw = cv2.imread(os.path.join(IMG, 'raw', c['name'] + '.png'))
    und = cv2.remap(raw, maps[0], maps[1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    s = c['sensor']
    g = cv2.cvtColor(und, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if s['contrast'] != 1.0: g = 110 + (g - 110) * s['contrast']
    g = cv2.GaussianBlur(g, (0, 0), math.hypot(0.55, s['blur']))
    rng = np.random.default_rng(np.random.SeedSequence([SENSOR_SEED, int(c['seed'])]))
    sig = (np.sqrt(np.maximum(g, 1) * 0.35) + 1.5) * s['noise_gain']
    g = g + rng.normal(size=g.shape).astype(np.float32) * sig + 4      # same model as make_dataset.sensor_model, with gain / extra blur / contrast knobs
    return np.clip(g, 0, 255).astype(np.uint8)


def render_pending(cases, batch, use_gpu, limit):
    raw = os.path.join(IMG, 'raw'); os.makedirs(raw, exist_ok=True)
    pend = [c for c in cases if not os.path.exists(os.path.join(raw, c['name'] + '.png'))]
    log(f'{len(cases) - len(pend)}/{len(cases)} raw frames present, {len(pend)} pending')
    if limit: pend = pend[:limit]
    for b in range(0, len(pend), batch):
        chunk = pend[b:b + batch]
        cj = os.path.join(IMG, 'cases_batch.json'); json.dump(chunk, open(cj, 'w'))
        for dev in (['HIP', 'HIP', 'CPU'] if use_gpu else ['CPU']):
            t1 = time.time()
            with open(LOG, 'a') as lf:
                r = subprocess.run([md.BLENDER, '-b', '-P', os.path.join(ROOT, 'tools', 'blender_render.py'), '--', cj, raw],
                                   env=dict(os.environ, RENDER_DEVICE=dev), stdout=lf, stderr=subprocess.STDOUT)
            ok = all(os.path.exists(os.path.join(raw, c['name'] + '.png')) for c in chunk)
            log(f'batch {b // batch + 1} device={dev} rc={r.returncode} ok={ok} {time.time() - t1:.0f}s')
            if ok: break
        else:
            raise SystemExit('render failed')
    if os.path.exists(os.path.join(IMG, 'cases_batch.json')): os.remove(os.path.join(IMG, 'cases_batch.json'))


def make_sensor(cases):
    maps = md.distortion_maps(); os.makedirs(os.path.join(IMG, 'sensor'), exist_ok=True)
    for c in cases:
        out = os.path.join(IMG, 'sensor', c['name'] + '.png')
        if os.path.exists(out) or not os.path.exists(os.path.join(IMG, 'raw', c['name'] + '.png')): continue
        cv2.imwrite(out, sensor_img(c, maps))


# ------------------------------------------------------------------ ground truth (schema 2, see tools/dataset_gt.py)
def build_gt(cases):
    K = K_matrix(); tm = load_tag_map(); out = {}
    for c in cases:
        im = cv2.imread(os.path.join(IMG, 'sensor', c['name'] + '.png'), cv2.IMREAD_GRAYSCALE)
        if im is None: continue
        R = np.array(c['R_wc']); t = np.array(c['t_wc']); ocs = c.get('occluders', [])
        geo = tag_geometry(R, t, tm, K, DIST_TRUE, ocs)
        for tid, n in geo.items():
            n.update(image_stats(im, n['corners']) if n['facing'] and n['px_width'] > 3 else dict(sat_frac=None, contrast=None, mean_level=None))
            apply_image_reasons(n)
        sp = c.get('spot')
        if sp:
            for tid in geo:
                geo[tid]['shadow_fraction'] = round(float(segment_hits(np.array(sp['pos']), tag_samples(tm, int(tid)), ocs).mean()), 4) if geo[tid]['facing'] else None
        out[c['name']] = dict(R_wc=R.tolist(), t_wc=t.tolist(), quat_wxyz=[float(x) for x in R_to_quat(R)], tags=geo, category=c['category'], source='ds100',
                              seed=c['seed'], n_visible=sum(n['visible'] for n in geo.values()), n_detectable=sum(n['detectable'] for n in geo.values()),
                              lighting=dict(light_scale=c['light_scale'], light_shift=c['light_shift'], spot=c.get('spot')),
                              sensor=c['sensor'], background=c.get('bg') or dict(kind='default'), n_occluders=len(ocs), occluders=ocs)
    G = dict(schema=2, width=W, height=H, K=K.tolist(), dist=DIST_TRUE.tolist(), detectability=DETECT,
             note='visible = facing camera and all 4 corners inside the frame (legacy). detectable = visible and px_width>=10 and incidence<=75deg and occ_fraction<=0.5 and not washed out / flat.',
             images={n: out[n] for n in sorted(out)})
    tmp = os.path.join(IMG, 'ground_truth.json.tmp'); json.dump(G, open(tmp, 'w'), indent=1); os.replace(tmp, os.path.join(IMG, 'ground_truth.json'))
    log(f'ground truth written: {len(out)} images')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gen', action='store_true'); ap.add_argument('--gt', action='store_true'); ap.add_argument('--regen', action='store_true')
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--batch', type=int, default=25); ap.add_argument('--cpu', action='store_true')
    a = ap.parse_args()
    cases = load_cases(a.regen)
    if a.gen: return
    if not a.gt:
        render_pending(cases, a.batch, not a.cpu, a.limit)
        make_sensor(cases)
    build_gt(cases)
    log('done')


if __name__ == '__main__':
    main()
