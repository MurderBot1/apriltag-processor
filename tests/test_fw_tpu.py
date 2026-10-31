"""C port of the tag processing unit (firmware/core/attpu.c) vs the bit-exact Python ISS (tools/tpu_isa.py + tools/tpu_prog.py), which in turn
is checked against the old FPGA TPU RTL in tests/test_tpu.py.  Everything is compared word for word (the whole result RAM image)."""
import os, sys, random, zlib, numpy as np, pytest, cv2
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import attpu, golden, tpu_harness, synth_images
from tpu_isa import Machine, s32
from test_tpu import pack_fb

ROOT = attpu.ROOT
GT = None


@pytest.fixture(scope='module')
def A():
    return attpu.Attpu()


def names():
    import json
    return sorted(json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images'])


def iss_vs_c(A, mask, words, ncand, frame_id=7, maxham=2):
    cand = list(words) + [0] * (1024 - len(words))
    h, w = mask.shape
    pix = lambda x, y: int(mask[y, x]) if 0 <= x < w and 0 <= y < h else 0
    m = Machine(tpu_harness.PROG, tpu_harness.CODES, pix, cand, dict(frame_id=frame_id, maxham=maxham, cand_count=ncand, minside=8)).run()
    iss = [x & 0xFFFFFFFF for x in m.res]
    res, n, _ = A.run(pack_fb(mask), words, ncand, frame_id, maxham)
    return iss, res, n


def same(iss, res, n):
    k = 16 + 16 * n
    return iss[0] == n and iss[:k] == res[:k] and all(v == 0 for v in iss[k:])


# --------------------------------------------------------------------------------------- primitives
def test_divq_matches_isa(A):
    rng = random.Random(1)
    edge = [0, 1, -1, 2, 65535, 65536, 65537, -65536, 0x7FFFFFFF, -0x7FFFFFFF, -0x80000000, 0x40000000, 0x12345678, 3, 1000003]
    pairs = [(a, b) for a in edge for b in edge]
    pairs += [(rng.randint(-2**31, 2**31 - 1), rng.randint(-2**31, 2**31 - 1)) for _ in range(20000)]
    pairs += [(rng.randint(-2**31, 2**31 - 1) >> rng.randint(0, 31), rng.randint(-2**31, 2**31 - 1) >> rng.randint(0, 31)) for _ in range(20000)]
    for a, b in pairs:
        if b == 0:
            ref = 0x7FFFFFFF if a >= 0 else -0x7FFFFFFF
        else:
            q = (abs(a) << 16) // abs(b)
            ref = s32(q if (a < 0) == (b < 0) else -q)
        assert A.lib.attpu_divq(a, b) == ref, (a, b)


def test_muls_matches_isa(A):
    rng = random.Random(2)
    for _ in range(20000):
        a, b, sh = rng.randint(-2**31, 2**31 - 1), rng.randint(-2**31, 2**31 - 1), rng.choice((12, 16, 24))
        assert A.lib.attpu_muls(a, b, sh) == s32((a * b) >> sh)


def test_match_matches_iss_scan(A):
    codes = tpu_harness.CODES
    m = Machine([0], codes, lambda x, y: 0, [0] * 1024, dict(frame_id=0, maxham=2, cand_count=0, minside=8))
    from tpu_isa import rot6
    rng = random.Random(3)
    cases = []
    for _ in range(3000):
        c = codes[rng.randrange(587)]
        for _ in range(rng.choice((0, 0, 1, 2, 2, 3, 5))):
            c ^= 1 << rng.randrange(36)
        for _ in range(rng.randrange(4)):
            c = rot6(c)
        cases.append(c)
    cases += [rng.getrandbits(36) for _ in range(1500)] + [0, (1 << 36) - 1]
    for maxham in (0, 1, 2, 3, 5):
        m.cfg['maxham'] = maxham
        for c in cases:
            ref, _ = m.match(c & 0xFFFFFFFF, c >> 32)
            assert A.lib.attpu_match(c & 0xFFFFFFFF, c >> 32, maxham) == ref, (hex(c), maxham)


# --------------------------------------------------------------------------------------- whole frames
@pytest.mark.parametrize('stream', [False, True], ids=['golden-ccl', 'streaming-ccl'])
def test_dataset_frames_bit_exact(A, stream):
    """all 100 dataset frames: Python threshold + despeckle, candidates from the (golden or RTL-policy) labeller; ISS and C results identical"""
    tot_tags = 0
    for n in names():
        img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), 0)
        mask = golden.binarize_clean(img)
        keep, lab, allc = golden.components(mask)
        if stream:                             # the candidate list of the RTL labeller policy: <= 64 largest, table order
            cands, _ = golden.stream_components(mask)
            key = {(c['area'], c['x0'], c['x1'], c['y0'], c['y1']): c['label'] for c in allc}
            keep = [dict(c, label=key[(c['area'], c['x0'], c['x1'], c['y0'], c['y1'])]) for c in cands]
        keep = keep[:64]
        words = golden.pack_records(keep, lab)
        iss, res, nt = iss_vs_c(A, mask, words, len(keep), frame_id=zlib.crc32(n.encode()) & 0xFFFF)
        assert same(iss, res, nt), (n, [i for i in range(512) if iss[i] != res[i]][:8])
        tot_tags += nt
    assert tot_tags > 400


@pytest.mark.parametrize('maxham', [0, 1, 3, 4, 8])
def test_other_thresholds_bit_exact(A, maxham):
    for n in ('normal_001', 'persp_004', 'noise_003', 'blur_002'):
        img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', n + '.png'), 0)
        mask = golden.binarize_clean(img)
        keep, lab, _ = golden.components(mask)
        iss, res, nt = iss_vs_c(A, mask, golden.pack_records(keep, lab), len(keep), maxham=maxham)
        assert same(iss, res, nt), (n, maxham)


@pytest.mark.parametrize('seed', range(6))
def test_corrupted_masks_bit_exact(A, seed):
    """scenes with random pixel noise, holes and shifted bits: exercises the failure paths of coarse / refine / decode"""
    rng = np.random.default_rng(100 + seed)
    img, gt = synth_images.tag_scene(seed, ntags=6, smin=45, smax=170)
    mask = golden.binarize(img)
    if seed % 3 == 1:
        mask ^= rng.random(mask.shape) < 0.004
    if seed % 3 == 2:
        for _ in range(60):
            x, y = int(rng.integers(0, 1200)), int(rng.integers(0, 760))
            mask[y:y + int(rng.integers(2, 30)), x:x + int(rng.integers(2, 30))] ^= True
    keep, lab, _ = golden.components(mask)
    iss, res, nt = iss_vs_c(A, mask, golden.pack_records(keep, lab), len(keep), frame_id=seed)
    assert same(iss, res, nt)


def test_random_candidate_records(A):
    """garbage records (random extremes) must not crash and must agree with the ISS"""
    rng = random.Random(7)
    img, gt = synth_images.tag_scene(2, ntags=5, smin=60, smax=150)
    mask = golden.binarize(img)
    keep, lab, _ = golden.components(mask)
    words = golden.pack_records(keep, lab)
    for _ in range(15):
        w = list(words)
        for _ in range(rng.randrange(1, 12)):
            w[rng.randrange(len(w))] = rng.getrandbits(32) if rng.random() < 0.5 else rng.getrandbits(16) | (rng.getrandbits(11) << 16)
        iss, res, nt = iss_vs_c(A, mask, w, len(keep))
        assert same(iss, res, nt)
    iss, res, nt = iss_vs_c(A, mask, [], 0)
    assert nt == 0 and same(iss, res, nt)
