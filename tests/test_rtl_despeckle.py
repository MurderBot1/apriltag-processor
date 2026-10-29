"""RTL despeckle vs golden majority filter."""
import os, sys, numpy as np, cv2, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden
S = rtlutil.SIM

@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_despeckle', ['rtl/despeckle.v', 'tb/tb_despeckle.v'])

def run(vvp, m, tag, bypass=0):
    p = f'{S}/{tag}.mask'; m.astype(np.uint8).tofile(p)
    out = rtlutil.run(vvp, [f'mask={p}', f'out={S}/{tag}.dsp', f'bypass={bypass}'])
    got = np.fromfile(f'{S}/{tag}.dsp', np.uint8).reshape(800, 1280).astype(bool)
    return out, got

def check(vvp, m, tag):
    out, got = run(vvp, m, tag)
    want = golden.despeckle(m)
    assert 'rows=800' in out and 'bad=0' in out and 'fs=1 fe=1' in out, out
    bad = np.argwhere(got != want)
    assert len(bad) == 0, (len(bad), bad[:5].tolist(), out)

def test_random_noise_and_edges(vvp):
    rng = np.random.default_rng(1)
    m = rng.random((800, 1280)) < 0.35
    check(vvp, m, 'dsp_noise')

def test_structured(vvp):
    m = np.zeros((800, 1280), bool)
    cv2.rectangle(m.view(np.uint8), (0, 0), (50, 50), 1, -1); cv2.rectangle(m.view(np.uint8), (1200, 740), (1279, 799), 1, -1)
    m[400, 600:605] = 1; m[10, 10] = 1; m[799, 0] = 1; m[0, 1279] = 1; m[300:303, 300:303] = 1
    m[500:700:2, 100:900:2] = 1
    check(vvp, m, 'dsp_struct')

def test_real_image_mask(vvp):
    img = cv2.imread(os.path.join(rtlutil.ROOT, 'test_images', 'sensor', 'clutter_001.png'), 0)
    check(vvp, golden.binarize(img), 'dsp_real')

def test_all_ones_and_zeros(vvp):
    check(vvp, np.ones((800, 1280), bool), 'dsp_ones'); check(vvp, np.zeros((800, 1280), bool), 'dsp_zeros')
