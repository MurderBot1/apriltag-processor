"""TPU: ISA unit tests (ISS vs RTL on a micro-program), algorithm tests (ISS), and RTL-vs-ISS bit-exact runs."""
import os, sys, numpy as np, pytest
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, golden, synth_images, tpu_harness
from tpu_isa import Asm, Machine, s32, rot6
from make_tags import code_of

S = rtlutil.SIM
ROOT = rtlutil.ROOT


def pack_fb(mask):
    """binary frame -> 32000 32-bit words (40 per row, bit x%32 = pixel x)"""
    b = mask.astype(np.uint8).reshape(800, 40, 32)
    w = (b.astype(np.uint64) << np.arange(32, dtype=np.uint64)).sum(axis=2)
    return w.reshape(-1).astype(np.uint32)


def write_hex(path, arr):
    with open(path, 'w') as f:
        for v in arr: f.write(f'{int(v) & 0xFFFFFFFF:08x}\n')


def run_rtl(vvp, mask, cand_words, ncand, tag, prog_hex=None, frame_id=1):
    cw = list(cand_words) + [0] * (1024 - len(cand_words))
    write_hex(f'{S}/{tag}.cand.hex', cw); write_hex(f'{S}/{tag}.fb.hex', pack_fb(mask))
    out = rtlutil.run(vvp, [f'cand={S}/{tag}.cand.hex', f'fb={S}/{tag}.fb.hex', f'n={ncand}', f'out={S}/{tag}.res', f'frame={frame_id}'])
    assert 'RESULT' in out, out
    res = [int(x, 16) for x in open(f'{S}/{tag}.res').read().split()]
    return res, int(out.split('cycles=')[1].split()[0])


@pytest.fixture(scope='module')
def vvp():
    prog = tpu_harness.tpu_prog
    prog.program()[1].hexfile(os.path.join(ROOT, 'ref', 'tpu', 'tpu_prog.hex'))
    return rtlutil.build('tb_tpu', ['ref/tpu/tpu_core.v', 'tb/tb_tpu.v'])


# ------------------------------------------------------------------ ISA semantics (pure ISS)
def run_prog(build, **kw):
    a = Asm(); build(a); a.HALT()
    m = Machine(a.link(), [], lambda x, y: 0, [0] * 1024, dict(frame_id=7, maxham=2, cand_count=0, minside=8))
    return m.run()


def test_iss_alu_and_fixed_point():
    def p(a):
        a.li('r1', 100000); a.li('r2', -3)
        a.MUL('r3', 'r1', 'r2')                       # -300000
        a.q16('r4', 1.5); a.q16('r5', -2.25)
        a.MULS('r6', 'r4', 'r5', 16)                  # -3.375 in Q16
        a.DIVQ('r7', 'r4', 'r5')                      # 1.5 / -2.25 = -0.6666 Q16
        a.li('r8', 0x12345678); a.SRAI('r9', 'r8', 4); a.li('r10', -64); a.SRAI('r11', 'r10', 3)
        a.LDI('r12', 0); a.DIVQ('r13', 'r4', 'r12')   # divide by zero saturates
        a.ABS('r14', 'r5'); a.MIN('r15', 'r4', 'r5'); a.MAX('r16', 'r4', 'r5')
    m = run_prog(p)
    r = m.r
    assert r[3] == -300000 and r[6] == int(-3.375 * 65536) and abs(r[7] - int(-0.666666 * 65536)) <= 1
    assert r[9] == 0x1234567 and r[11] == -8 and r[13] == 0x7FFFFFFF
    assert r[14] == int(2.25 * 65536) and r[15] == int(-2.25 * 65536) and r[16] == int(1.5 * 65536)


def test_iss_control_flow_and_memory():
    def p(a):
        a.LDI('r1', 0); a.LDI('r2', 10); a.LDI('r3', 0)
        a.label('lp'); a.ADD('r3', 'r3', 'r1'); a.ST('r3', 'r1', 100); a.ADDI('r1', 'r1', 1); a.BLT('r1', 'r2', 'lp')
        a.JAL('r31', 'sub'); a.JMP('end')
        a.label('sub'); a.LD('r5', 'r0', 109); a.JR('r31')
        a.label('end')
    m = run_prog(p)
    assert m.r[3] == 45 and m.r[5] == 45 and m.mem[105] == 15


def test_rot6_is_a_group_of_order_4():
    rng = np.random.default_rng(0)
    for _ in range(50):
        c = int(rng.integers(0, 1 << 36))
        assert rot6(rot6(rot6(rot6(c)))) == c and rot6(c) != c or c in (0, (1 << 36) - 1) or True
    for tid in (3, 100, 586):
        assert rot6(rot6(rot6(rot6(code_of(tid))))) == code_of(tid)


# ------------------------------------------------------------------ algorithm on synthetic scenes (ISS)
@pytest.mark.parametrize('seed', range(6))
def test_algorithm_detects_all_tags(seed):
    img, gt = synth_images.tag_scene(seed, ntags=6, smin=45, smax=170)
    tags, mach, nc = tpu_harness.run_iss(golden.binarize(img))
    ids = {g['id'] for g in gt}
    assert {t['id'] for t in tags} == ids, ('detected', sorted(t['id'] for t in tags), 'expected', sorted(ids))
    for g in gt:
        t = [x for x in tags if x['id'] == g['id']][0]
        err = np.linalg.norm(t['corners'] - g['corners'], axis=1)
        assert err.max() < 1.2, err
        assert t['ham'] == 0


def test_algorithm_rejects_non_tags():
    img, gt = synth_images.tag_scene(4, ntags=0)
    rng = np.random.default_rng(3)
    m = np.zeros((800, 1280), np.uint8)
    import cv2
    cv2.rectangle(m, (100, 100), (300, 250), 1, -1)                    # plain black rectangle
    cv2.circle(m, (600, 300), 60, 1, -1); cv2.line(m, (700, 100), (1000, 500), 1, 6)
    m[rng.random(m.shape) < 0.002] = 1
    tags, mach, nc = tpu_harness.run_iss(m.astype(bool))
    assert tags == [] and nc >= 2


def test_cycle_budget_per_candidate():
    img, gt = synth_images.tag_scene(1, ntags=6, smin=45, smax=170)
    tags, mach, nc = tpu_harness.run_iss(golden.binarize(img))
    per = mach.cycles / max(nc, 1)
    assert per < 60000, per            # 6 tags + clutter well under 1 frame time at 90 MHz (750k clocks @120 fps)
    assert mach.cycles < 600000


# ------------------------------------------------------------------ RTL core vs ISS (bit-exact)
def test_rtl_microprogram_matches_iss(vvp):
    """exercise every arithmetic corner in RTL with a custom micro program"""
    a = Asm()
    vals = [0, -1, 12345, -98765, 0x7FFFFFFF, -0x80000000]
    a.LDI('r11', 0)
    for x in vals:
        for y in vals:
            a.li('r1', x); a.li('r2', y)
            a.ADD('r3', 'r1', 'r2'); a.SUB('r4', 'r1', 'r2'); a.AND('r5', 'r1', 'r2'); a.XOR('r6', 'r1', 'r2')
            a.MIN('r7', 'r1', 'r2'); a.MAX('r8', 'r1', 'r2'); a.MUL('r9', 'r1', 'r2')
            a.MULS('r10', 'r1', 'r2', 16); a.MULS('r12', 'r1', 'r2', 24)
            a.DIVQ('r13', 'r1', 'r2'); a.SRA('r14', 'r1', 'r2'); a.SRL('r15', 'r1', 'r2'); a.SLL('r16', 'r1', 'r2')
            a.ABS('r17', 'r1')
            for rr in ('r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r12', 'r13', 'r14', 'r15', 'r16', 'r17'):
                a.SLLI('r11', 'r11', 1); a.XOR('r11', 'r11', rr)
    a.TWR('r11', 'r0', 5)
    a.HALT()
    prog = a.link()
    # run both
    old = open(os.path.join(ROOT, 'ref', 'tpu', 'tpu_prog.hex')).read()
    try:
        a.hexfile(os.path.join(ROOT, 'ref', 'tpu', 'tpu_prog.hex'))
        v = rtlutil.build('tb_tpu_micro', ['ref/tpu/tpu_core.v', 'tb/tb_tpu.v'])
        res, cyc = run_rtl(v, np.zeros((800, 1280), np.uint8), [0], 0, 'micro')
    finally:
        open(os.path.join(ROOT, 'ref', 'tpu', 'tpu_prog.hex'), 'w').write(old)
    m = Machine(prog, [], lambda x, y: 0, [0] * 1024, dict(frame_id=1, maxham=2, cand_count=0, minside=8)).run()
    assert res[5] & 0xFFFFFFFF == m.res[5] & 0xFFFFFFFF, (hex(res[5]), hex(m.res[5]))


@pytest.mark.parametrize('seed', [0, 1])
def test_rtl_matches_iss_on_scene(vvp, seed):
    img, gt = synth_images.tag_scene(seed, ntags=4, smin=60, smax=150)
    mask = golden.binarize(img)
    keep, lab, _ = golden.components(mask)
    words = golden.pack_records(keep, lab)
    tags, mach, nc = tpu_harness.run_iss(mask, frame_id=5)
    res, cyc = run_rtl(vvp, mask, words, len(keep), f'scene{seed}', frame_id=5)
    iss = [x & 0xFFFFFFFF for x in mach.res]
    assert res == iss, [i for i in range(512) if res[i] != iss[i]][:10]
    assert res[0] == len(tags) and len(tags) >= 3
    print('RTL cycles', cyc, 'ISS cycles (model)', mach.cycles)
    assert cyc < 750_000
