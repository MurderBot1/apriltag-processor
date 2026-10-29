import os, sys, json, math
import numpy as np, cv2, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from geom import project, load_tag_map, tag_corners_world, K_matrix, DIST_TRUE
import reference_pipeline as rp

GT_PATH = os.path.join(ROOT, 'test_images', 'ground_truth.json')
N_IMAGES = 500          # 100 original frames + 400 added by tools/make_dataset_500.py
N_ORIG = 100
BASE_CATS = {'dist', 'yaw', 'roll', 'dark', 'bright', 'grad', 'side', 'floor', 'rand', 'empty'}
NEW_CATS = {'pitch', 'occl', 'edge', 'shadow', 'glare', 'clutter'}


@pytest.fixture(scope='module')
def gt():
    return json.load(open(GT_PATH))


@pytest.fixture(scope='module')
def rows():
    return rp.evaluate()


def test_exactly_500_images_and_gt_entries(gt):
    names = sorted(f[:-4] for f in os.listdir(os.path.join(ROOT, 'test_images', 'sensor')) if f.endswith('.png'))
    assert len(names) == N_IMAGES
    assert sorted(gt['images']) == names
    cats = {g['category'] for g in gt['images'].values()}
    assert BASE_CATS | NEW_CATS <= cats
    assert sum(1 for g in gt['images'].values() if g['category'] == 'empty') >= 3 + 8
    assert sum(1 for g in gt['images'].values() if g.get('source', 'orig100') == 'orig100') == N_ORIG
    assert sum(1 for g in gt['images'].values() if g.get('source') == 'ext400') == N_IMAGES - N_ORIG
    for n, g in gt['images'].items():
        assert g['category'] == n.split('_')[0], n


def test_images_shape_dtype(gt):
    for n in gt['images']:
        im = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), cv2.IMREAD_UNCHANGED)
        assert im is not None and im.shape == (800, 1280) and im.dtype == np.uint8, n


def test_gt_reprojection(gt):
    tmap = load_tag_map(); K = np.array(gt['K']); d = np.array(gt['dist'])
    assert np.allclose(K, K_matrix()) and np.allclose(d, DIST_TRUE)
    for n, g in gt['images'].items():
        R, t = np.array(g['R_wc']), np.array(g['t_wc'])
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)
        assert set(map(int, g['tags'])) == set(tmap)
        for tid, tg in g['tags'].items():
            px, z = project(tag_corners_world(tmap, int(tid)), R, t, K, d)
            assert np.allclose(px, np.array(tg['corners']), atol=1e-6), (n, tid)
            if tg['visible']:
                assert (z > 0).all() and (px >= 0).all() and (px[:, 0] < 1280).all() and (px[:, 1] < 800).all()


def test_empty_images_have_no_visible_tags(gt):
    for n, g in gt['images'].items():
        if g['category'] == 'empty':
            assert not any(t['visible'] for t in g['tags'].values()), n


def test_detection_rate_and_corner_error(rows):
    vis = det = 0; errs = []
    for n, r in rows.items():
        if r['category'] in ('dark', 'empty'):
            continue
        vis += r['n_visible']; det += r['n_detected']; errs += r['corner_errs']
        assert r['n_false'] <= 2, n
    assert vis > 300
    assert det / vis >= 0.90, det / vis            # measured ~0.96
    assert np.median(errs) < 0.7, np.median(errs)   # measured ~0.25
    assert np.percentile(errs, 99) < 1.5


def test_dark_still_detected(rows):
    r = [v for v in rows.values() if v['category'] == 'dark']
    assert sum(v['n_detected'] for v in r) >= 0.8 * sum(v['n_visible'] for v in r)


def test_pose_errors(rows):
    isnew = lambda n: '_x' in n
    ok = lambda n, r: r['category'] != 'empty' and r['t_err_mm'] is not None
    t = [r['t_err_mm'] for n, r in rows.items() if ok(n, r)]
    a = [r['rot_err_deg'] for n, r in rows.items() if ok(n, r)]
    assert len(t) >= 450
    assert np.median(t) < 4 and np.percentile(t, 95) < 25      # measured median ~0.8 mm, p95 ~13 mm over all 500
    assert np.median(a) < 0.1 and np.percentile(a, 95) < 0.6
    for n, r in rows.items():            # the original 100 keep their original bounds
        if ok(n, r) and not isnew(n):
            assert r['t_err_mm'] < 80 and r['rot_err_deg'] < 1.7, n
            if r['category'] in ('dist', 'yaw', 'roll', 'dark', 'bright', 'grad'):
                assert r['t_err_mm'] < 20 and r['rot_err_deg'] < 0.5, n
        elif ok(n, r):                   # new frames include grazing/lone-tag probes (planar ambiguity): loose cap, worst measured yaw_x013 = 342 mm (2 grazing tags)
            assert r['t_err_mm'] < 400 and r['rot_err_deg'] < 4, n
            if r['category'] in ('roll', 'dark', 'bright', 'grad', 'pitch', 'clutter'):
                assert r['t_err_mm'] < 20 and r['rot_err_deg'] < 0.5, n


# ---------------------------------------------------------------- v2 ground truth (500-frame set)
def test_original_100_frames_unchanged():
    import hashlib
    man = json.load(open(os.path.join(ROOT, 'test_images', 'orig100_sha256.json')))
    assert len(man) == 2 * N_ORIG
    for rel, h in man.items():
        assert hashlib.sha256(open(os.path.join(ROOT, 'test_images', rel), 'rb').read()).hexdigest() == h, rel


def test_every_frame_has_a_raw_render(gt):
    for n in gt['images']:
        assert os.path.exists(os.path.join(ROOT, 'test_images', 'raw', n + '.png')), n


def test_gt_v2_schema_and_detectability_rules(gt):
    assert gt['schema'] == 2 and gt['detectability']['min_px'] == 10.0
    D = gt['detectability']
    need = {'corners', 'visible', 'px_width', 'in_frame', 'facing', 'incidence_deg', 'occ_fraction', 'vis_fraction', 'detectable', 'undetectable_reasons', 'edge_dist_px'}
    for n, g in gt['images'].items():
        assert g['n_detectable'] == sum(t['detectable'] for t in g['tags'].values()) and g['n_visible'] == sum(t['visible'] for t in g['tags'].values())
        for tid, t in g['tags'].items():
            assert need <= set(t), (n, tid)
            assert t['visible'] == (t['facing'] and t['in_frame'])
            assert t['detectable'] == (not t['undetectable_reasons'])
            if t['detectable']:
                assert t['visible'] and t['px_width'] >= D['min_px'] and t['incidence_deg'] <= D['max_incidence_deg'] and t['occ_fraction'] <= D['max_occlusion'], (n, tid)
            r = set(t['undetectable_reasons'])
            if t['facing'] and t['in_frame'] and t['px_width'] < D['min_px']: assert 'too_small' in r, (n, tid)
            if t['facing'] and t['incidence_deg'] > D['max_incidence_deg']: assert 'grazing' in r, (n, tid)
            if t['occ_fraction'] > D['max_occlusion']: assert 'occluded' in r, (n, tid)
            if not t['in_frame']: assert 'outside_frame' in r, (n, tid)


def test_new_frames_cover_the_requested_conditions(gt):
    G = gt['images']; new = {n: g for n, g in G.items() if g['source'] == 'ext400'}
    tags = [t for g in new.values() for t in g['tags'].values()]
    inc = [t['incidence_deg'] for t in tags if t['facing']]
    assert max(inc) > 80 and any(t['detectable'] and t['incidence_deg'] > 60 for t in tags)      # yaw/pitch up to (and past) the 75 deg limit
    assert any(t['detectable'] and t['distance_m'] < 0.7 for t in tags) and any(t['detectable'] and t['distance_m'] > 3.5 for t in tags)
    assert any(0.1 < t['occ_fraction'] <= 0.5 for t in tags) and any(t['occ_fraction'] > 0.5 for t in tags)       # partial / heavy occlusion
    assert sum(1 for t in tags if t['detectable'] and 0 < t['edge_dist_px'] <= 40) >= 10                          # tags at the frame edge
    assert sum(1 for t in tags if t['facing'] and not t['in_frame'] and t['vis_fraction'] > 0.2) >= 10             # tags cut by the frame edge
    for reason in ('too_small', 'grazing', 'occluded', 'outside_frame'):
        assert any(reason in t['undetectable_reasons'] for t in tags), reason
    assert len({g['background']['kind'] for g in new.values()}) >= 5 and max(g['n_occluders'] for g in new.values()) >= 10
    assert any(g['lighting']['spot'] for g in new.values()) and any(g['lighting']['glare'] for g in new.values())
    assert min(g['lighting']['light_scale'] for g in new.values()) < 0.1 and max(g['lighting']['light_scale'] for g in new.values()) > 4
    rolls = [math.degrees(math.atan2(np.array(g['R_wc'])[1, 0], np.array(g['R_wc'])[0, 0])) for n, g in new.items() if g['category'] == 'roll']
    assert max(rolls) - min(rolls) > 250
    assert sum(1 for g in new.values() if g['category'] == 'empty' and g['n_visible'] == 0) == 8


def test_new_frames_are_not_blank(gt):
    for n, g in gt['images'].items():
        if g['source'] != 'ext400': continue
        im = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), 0)
        assert 3 < im.mean() < 252 and im.std() > 2, n
