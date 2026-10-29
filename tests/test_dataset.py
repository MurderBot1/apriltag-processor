"""The 100-image dataset: 10 categories x 10 frames (tools/make_dataset_100.py).  Structure, ground-truth consistency and the
reference detector's accuracy.  Per-category detection counts are reported by tests/ci_category.py (one GitHub workflow per category)."""
import os, sys, json
import numpy as np, cv2, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from geom import project, load_tag_map, tag_corners_world, K_matrix, DIST_TRUE
import reference_pipeline as rp

GT_PATH = os.path.join(ROOT, 'test_images', 'ground_truth.json')
N_IMAGES, N_PER = 100, 10
CATS = ['normal', 'bright', 'dark', 'lowcon', 'grad', 'shadow', 'noise', 'clutter', 'blur', 'persp']


@pytest.fixture(scope='module')
def gt():
    return json.load(open(GT_PATH))


@pytest.fixture(scope='module')
def rows():
    return rp.evaluate()


def test_exactly_100_images_in_10_categories_of_10(gt):
    names = sorted(f[:-4] for f in os.listdir(os.path.join(ROOT, 'test_images', 'sensor')) if f.endswith('.png'))
    assert len(names) == N_IMAGES
    assert sorted(gt['images']) == names
    for c in CATS:
        assert sorted(n for n, g in gt['images'].items() if g['category'] == c) == [f'{c}_{i:03d}' for i in range(N_PER)], c
    assert {g['category'] for g in gt['images'].values()} == set(CATS)
    assert all(g['source'] == 'ds100' for g in gt['images'].values())


def test_cases_match_ground_truth(gt):
    cases = json.load(open(os.path.join(ROOT, 'test_images', 'cases.json')))
    assert [c['name'] for c in cases] == sorted(gt['images'], key=lambda n: (CATS.index(n.split('_')[0]), n))
    for c in cases:
        assert np.allclose(c['R_wc'], gt['images'][c['name']]['R_wc']) and np.allclose(c['t_wc'], gt['images'][c['name']]['t_wc'])


def test_images_shape_dtype(gt):
    for n in gt['images']:
        im = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), cv2.IMREAD_UNCHANGED)
        assert im is not None and im.shape == (800, 1280) and im.dtype == np.uint8, n
        assert 3 < im.mean() < 252 and im.std() > 1.5, n


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


def test_gt_schema_and_detectability_rules(gt):
    assert gt['schema'] == 2 and gt['detectability']['min_px'] == 10.0
    D = gt['detectability']
    need = {'corners', 'visible', 'px_width', 'in_frame', 'facing', 'incidence_deg', 'occ_fraction', 'vis_fraction', 'detectable', 'undetectable_reasons', 'edge_dist_px'}
    for n, g in gt['images'].items():
        assert g['n_detectable'] == sum(t['detectable'] for t in g['tags'].values()) >= 1 and g['n_visible'] == sum(t['visible'] for t in g['tags'].values())
        for tid, t in g['tags'].items():
            assert need <= set(t), (n, tid)
            assert t['visible'] == (t['facing'] and t['in_frame'])
            assert t['detectable'] == (not t['undetectable_reasons'])
            if t['detectable']:
                assert t['visible'] and t['px_width'] >= D['min_px'] and t['incidence_deg'] <= D['max_incidence_deg'] and t['occ_fraction'] <= D['max_occlusion'], (n, tid)


def test_categories_have_their_condition(gt):
    G = gt['images']; cat = lambda c: [g for n, g in G.items() if g['category'] == c]
    mean_level = lambda c: np.mean([cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), 0).mean() for n, g in G.items() if g['category'] == c])
    assert mean_level('dark') < 0.5 * mean_level('normal') < mean_level('bright')
    assert all(g['sensor']['noise_gain'] >= 2 for g in cat('noise')) and all(g['sensor']['blur'] >= 1 for g in cat('blur'))
    assert all(g['sensor']['contrast'] <= 0.42 for g in cat('lowcon'))
    assert all(g['n_occluders'] >= 3 for g in cat('clutter'))
    assert all(g['lighting']['spot'] for g in cat('shadow'))
    assert max(t['incidence_deg'] for g in cat('persp') for t in g['tags'].values() if t['detectable']) > 60
    assert all(g['sensor'] == dict(blur=0.0, noise_gain=1.0, contrast=1.0) for g in cat('normal'))


def test_detection_rate_and_corner_error(rows):
    det = dt = 0; errs = []
    for n, r in rows.items():
        det += r['n_det_detectable']; dt += r['n_detectable']; errs += r['corner_errs']
        assert r['n_false'] <= 1, n
    assert dt > 600
    assert det / dt >= 0.93, det / dt                # measured 630 / 647 = 0.974
    assert np.median(errs) < 0.6, np.median(errs)    # measured ~0.28
    assert np.percentile(errs, 99) < 1.5


def test_baseline_categories_are_clean(rows):
    for c in ('normal', 'bright', 'dark', 'lowcon', 'grad', 'clutter', 'noise'):
        r = [v for v in rows.values() if v['category'] == c]
        assert sum(v['n_det_detectable'] for v in r) >= 0.95 * sum(v['n_detectable'] for v in r), c


def test_pose_errors(rows):
    t = [r['t_err_mm'] for r in rows.values() if r['t_err_mm'] is not None]
    a = [r['rot_err_deg'] for r in rows.values() if r['rot_err_deg'] is not None]
    assert len(t) >= 95
    assert np.median(t) < 3 and np.percentile(t, 95) < 12          # measured median 0.7 mm, p95 4.5 mm, max 6.3 mm
    assert np.median(a) < 0.1 and np.percentile(a, 95) < 0.5
    for n, r in rows.items():
        if r['t_err_mm'] is not None:
            assert r['t_err_mm'] < 40 and r['rot_err_deg'] < 1.5, n
