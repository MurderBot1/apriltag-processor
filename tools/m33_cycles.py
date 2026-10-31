"""Estimate the run time of the C TPU (firmware/core/attpu.c) on an RP2350 core from an emulated Cortex-M33 execution.

Method (reproducible, no hardware):
  1. tools/m33_bench/build.sh builds the TPU for -mcpu=cortex-m33 -mthumb (same -O2 as firmware/rp2350/CMakeLists.txt) into a flat image.
  2. This script runs it in Unicorn (QEMU's Cortex-M33 model: it executes the real Thumb-2 machine code; its tag output is compared with
     the PC build of the same C file), recording every basic block that executes and how control flowed.
  3. Each executed instruction is costed with a static Cortex-M33 latency table (Arm Cortex-M33 TRM instruction timing), added up per
     block, plus a pipeline-refill penalty for every taken branch.  Three tables (optimistic / nominal / pessimistic) bracket the
     uncertainty that a static model cannot remove: load/store latency incl. SRAM arbitration, branch refill, divider early termination.
This is an instruction-accurate execution with a table-driven cycle model, NOT a cycle-accurate simulation: flash/XIP-cache misses, bus
contention with DMA and the second core, and the real divider timing are not modelled.  The nominal result is a best estimate; the
optimistic and pessimistic columns are the bounds used for the pass/fail decision.

    py -3.12 tools/m33_cycles.py [--opt -O2] [--mhz 150] [--frames N] [--golden] [--json out.json]
"""
import os, sys, json, argparse, subprocess, collections, zlib, shutil
import numpy as np, cv2
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import golden
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_BLOCK
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_CPU_ARM_CORTEX_M33
import capstone as cs

FLASH, RAM, RAM_SIZE = 0x10000000, 0x20000000, 0x100000
FB, CAND, OUT, PARAM = 0x20020000, 0x20040000, 0x20041000, 0x20042000
STOP = 0x10F00000

# cycles per instruction class
MODELS = {
    'optimistic':  dict(alu=1, mul=1, load=1, store=1, div=3,  branch=2, ldm_extra=0),
    'nominal':     dict(alu=1, mul=1, load=2, store=2, div=7,  branch=3, ldm_extra=0),
    'pessimistic': dict(alu=1, mul=1, load=3, store=2, div=12, branch=4, ldm_extra=1),
}
NOT_BRANCH = ('bic', 'bfc', 'bfi', 'bkpt')


def classify(insn):
    """-> (class, extra registers/words, writes pc)"""
    b = insn.mnemonic.split('.')[0]
    nreg = max(1, len(insn.operands)) if b.startswith(('push', 'pop', 'ldm', 'stm')) else 0
    if b.startswith(('sdiv', 'udiv')): return 'div', 0, False
    if b.startswith(('mul', 'mla', 'mls', 'smul', 'umul', 'smla', 'umla', 'smmul')): return 'mul', 0, False
    if b.startswith(('push', 'stm')): return 'ldm', nreg, False
    if b.startswith(('pop', 'ldm')):
        pc = any(o.type == cs.arm.ARM_OP_REG and insn.reg_name(o.reg) == 'pc' for o in insn.operands)
        return 'ldm', nreg, pc
    if b.startswith('ldr'):
        pc = bool(insn.operands) and insn.operands[0].type == cs.arm.ARM_OP_REG and insn.reg_name(insn.operands[0].reg) == 'pc'
        return 'load', 2 if b.startswith('ldrd') else 1, pc
    if b.startswith('str'): return 'store', 2 if b.startswith('strd') else 1, False
    if b.startswith(('cbz', 'cbnz', 'tbb', 'tbh')): return 'branch', 0, True
    if (cs.CS_GRP_JUMP in insn.groups or cs.CS_GRP_CALL in insn.groups or cs.CS_GRP_RET in insn.groups) and not b.startswith(NOT_BRANCH):
        return 'branch', 0, True
    return 'alu', 0, False


class M33:
    def __init__(self, opt):
        self.opt = opt
        subprocess.check_call(['sh', os.path.join(ROOT, 'tools', 'm33_bench', 'build.sh'), opt, 'sim/m33'], cwd=ROOT, stdout=subprocess.DEVNULL)
        self.elf = os.path.join(ROOT, 'sim', 'm33', 'bench.elf')
        self.image = open(os.path.join(ROOT, 'sim', 'm33', 'bench.bin'), 'rb').read()
        nm_exe = shutil.which('arm-none-eabi-nm') or 'C:/msys64/ucrt64/bin/arm-none-eabi-nm.exe'
        nm = subprocess.run([nm_exe, self.elf], capture_output=True, text=True).stdout
        self.sym = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
        self.cs = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB | cs.CS_MODE_MCLASS); self.cs.detail = True
        self.cache = {}
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M33)
        self.uc.mem_map(FLASH, 0x200000); self.uc.mem_write(FLASH, self.image)
        self.uc.mem_map(RAM, RAM_SIZE)
        self.blocks, self.trans, self.prev = collections.Counter(), collections.Counter(), None
        self.uc.hook_add(UC_HOOK_BLOCK, self._blk)
        self.call('bench_init')

    def _blk(self, uc, addr, size, ud):
        self.blocks[(addr, size)] += 1
        if self.prev is not None: self.trans[(self.prev, addr)] += 1
        self.prev = addr

    def call(self, name):
        self.blocks.clear(); self.trans.clear(); self.prev = None
        self.uc.reg_write(UC_ARM_REG_SP, RAM + RAM_SIZE - 16)
        self.uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.uc.emu_start(self.sym[name] | 1, STOP)

    def decode(self, addr, size):
        k = (addr, size)
        if k not in self.cache:
            code = self.image[addr - FLASH: addr - FLASH + size]
            self.cache[k] = [classify(i) for i in self.cs.disasm(code, addr)]
        return self.cache[k]

    def cost(self):
        """-> (instructions executed, {model: cycles}) of the last call()"""
        succ = collections.defaultdict(list)
        for (a, b), n in self.trans.items(): succ[a].append((b, n))
        ninstr = 0; cyc = {m: 0.0 for m in MODELS}
        for (addr, size), n in self.blocks.items():
            ins = self.decode(addr, size)
            ninstr += n * len(ins)
            for m, t in MODELS.items():
                c = 0
                for cls, k, _ in ins:
                    if cls in ('alu', 'mul', 'div'): c += t[cls]
                    elif cls == 'load': c += t['load'] + (k - 1)
                    elif cls == 'store': c += t['store'] + (k - 1)
                    elif cls == 'ldm': c += 1 + k + t['ldm_extra']
                    elif cls == 'branch': c += 1
                cyc[m] += n * c
            cls, k, pcwrite = ins[-1]                  # taken-branch refill: last instruction branches and control did not fall through
            if pcwrite or cls == 'branch':
                taken = sum(nn for b, nn in succ[addr] if b != addr + size)
                for m, t in MODELS.items(): cyc[m] += taken * (t['branch'] - 1)
        return ninstr, cyc

    def run_frame(self, mask, cands, frame_id=1, maxham=2):
        from test_tpu import pack_fb
        self.uc.mem_write(FB, pack_fb(mask).tobytes())
        cw = np.zeros(1024, np.uint32); cw[:len(cands)] = np.asarray(cands, dtype=np.uint64) & 0xFFFFFFFF
        self.uc.mem_write(CAND, cw.tobytes())
        self.uc.mem_write(PARAM, np.array([len(cands) // 16, frame_id, maxham, 0], np.uint32).tobytes())
        self.call('bench_run')
        ntags = int.from_bytes(self.uc.mem_read(PARAM + 12, 4), 'little')
        return ntags, bytes(self.uc.mem_read(OUT, 52 * ntags))


def frame_inputs(name, stream=True):
    img = cv2.imread(os.path.join(ROOT, 'test_images', 'sensor', name + '.png'), 0)
    mask = golden.binarize_clean(img)
    keep, lab, allc = golden.components(mask)
    if stream:                                         # candidate table of the RTL labeller policy (<= 64, ranked by area)
        cands, _ = golden.stream_components(mask)
        key = {(c['area'], c['x0'], c['x1'], c['y0'], c['y1']): c['label'] for c in allc}
        keep = [dict(c, label=key[(c['area'], c['x0'], c['x1'], c['y0'], c['y1'])]) for c in cands]
    keep = keep[:64]
    return mask, golden.pack_records(keep, lab), len(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--opt', default='-O2'); ap.add_argument('--mhz', type=float, default=150.0)
    ap.add_argument('--frames', type=int, default=0, help='only the first N frames'); ap.add_argument('--golden', action='store_true')
    ap.add_argument('--json'); ap.add_argument('--check', action='store_true', help='4 representative frames, fail if the pessimistic worst exceeds 12 ms')
    a = ap.parse_args()
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    names = ['normal_001', 'persp_004', 'clutter_002', 'noise_006'] if a.check else sorted(gt)[:a.frames or None]
    import attpu
    from test_tpu import pack_fb
    pc = attpu.Attpu()
    m = M33(a.opt)
    ni, cy = m.cost(); init = dict(instr=ni, cycles=cy)
    print(f'attpu_init: {ni} instr, ' + ', '.join(f'{k} {v / a.mhz / 1000:.3f} ms' for k, v in cy.items()))
    rows = []
    for n in names:
        mask, words, nc = frame_inputs(n, not a.golden)
        ntags, out = m.run_frame(mask, words, zlib.crc32(n.encode()) & 0xFFFF)
        ni, cy = m.cost()
        _, n_pc, tags_pc = pc.run(pack_fb(mask), words, nc, zlib.crc32(n.encode()) & 0xFFFF)     # same C file built for the PC
        assert n_pc == ntags and bytes(tags_pc)[:52 * ntags] == out, f'{n}: emulated M33 result differs from the PC build'
        rows.append(dict(name=n, cat=gt[n]['category'], ncand=nc, tags=ntags, instr=ni, cycles=cy, out=out.hex()))
    ms = lambda r, k: r['cycles'][k] / (a.mhz * 1000.0)
    print(f'\nCortex-M33 @ {a.mhz:g} MHz, one core, {a.opt}; frame period 8.33 ms; budget (doc experiment 1): median <= 6 ms, worst <= 12 ms')
    print('| category | frames | tags | cand (median) | instr (median) | optimistic med/max ms | nominal med/max ms | pessimistic med/max ms |')
    print('|---|---|---|---|---|---|---|---|')

    def line(label, rs):
        f = lambda k: f'{np.median([ms(r, k) for r in rs]):.2f} / {max(ms(r, k) for r in rs):.2f}'
        print(f'| {label} | {len(rs)} | {sum(r["tags"] for r in rs)} | {int(np.median([r["ncand"] for r in rs]))} | '
              f'{int(np.median([r["instr"] for r in rs]))} | {f("optimistic")} | {f("nominal")} | {f("pessimistic")} |')
    for c in sorted({r['cat'] for r in rows}): line(c, [r for r in rows if r['cat'] == c])
    line('all', rows)
    for k in MODELS:
        v = np.array([ms(r, k) for r in rows])
        print(f'{k:12s} median {np.median(v):.2f} ms  p95 {np.percentile(v, 95):.2f}  max {v.max():.2f}  frames > 8.33 ms: {(v > 8.333).sum()}  > 12 ms: {(v > 12).sum()}')
    if a.check:
        worst = max(ms(r, 'pessimistic') for r in rows)
        assert worst < 12.0, f'pessimistic worst {worst:.2f} ms'
    if a.json:
        json.dump(dict(opt=a.opt, mhz=a.mhz, init=init, rows=[{k: v for k, v in r.items() if k != 'out'} for r in rows]), open(a.json, 'w'))
    return rows, m


if __name__ == '__main__':
    main()
