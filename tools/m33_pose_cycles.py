"""Estimate the run time of the pose solver (firmware/core/atpose.c) on an RP2350 core, same method as tools/m33_cycles.py (Unicorn Cortex-M33
execution + static cycle table, now with VFP loads/stores and 14-cycle vdiv/vsqrt).

Two builds bracket the real firmware, which calls double-precision sqrt/atan2 through the SDK's pico_double (RP2350 DCP coprocessor, not
modelled by the emulator):
  float  : -include tgmath.h, all maths in single precision on the M33 FPU (sqrtf/atan2f)            -> optimistic
  double : the source as written, double maths in newlib/libgcc SOFTWARE                               -> pessimistic upper bound
The real firmware (DCP doubles) lies between the two.  Inputs: the tags of results/rtl_chain_results.json (what the chain detects) against
config/tag_map.json.

    py -3.12 tools/m33_pose_cycles.py [--results results/rtl_chain_results.json] [--json out.json]
"""
import os, sys, json, argparse
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import m33_cycles as M
import atcore, geom
import ctypes as C

FIELD, MEAS, PARAM, OUT = 0x20030000, 0x20038000, 0x2003A000, 0x2003B000


def run(flags, outdir, results, mhz):
    sol = atcore.Solver(False); sol.set_field(geom.load_tag_map())
    m = M.M33(flags, build='build_pose.sh', outdir=outdir, init=None, fpu=True)
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    rows = []
    for name in sorted(gt):
        dets = [(t['id'], t['corners']) for t in results[name]['tags']][:16]
        n = len(dets)
        arr = (sol.Meas * max(n, 1))()
        for i, (tid, c) in enumerate(dets):
            arr[i].id = tid
            for a in range(4):
                for b in range(2): arr[i].c[a][b] = float(c[a][b])
        m.uc.mem_write(FIELD, bytes(sol.field)); m.uc.mem_write(MEAS, bytes(arr))
        m.uc.mem_write(PARAM, np.array([n, 0xFFFF], np.uint32).tobytes())
        m.call('bench_run')
        rc = int.from_bytes(m.uc.mem_read(PARAM + 4, 4), 'little', signed=True)
        pc = sol.solve([(t, c) for t, c in dets])
        if pc is not None:
            out = sol.Pose.from_buffer_copy(bytes(m.uc.mem_read(OUT, C.sizeof(sol.Pose))))
            assert rc == 0 and np.allclose(np.array(out.t[:]), pc[1], atol=2e-3), (name, rc, list(out.t), pc[1])
        else:
            assert rc != 0, (name, rc)
        ni, cy = m.cost()
        rows.append(dict(name=name, cat=gt[name]['category'], n=n, rc=rc, instr=ni, ms={k: v / (mhz * 1000.0) for k, v in cy.items()}))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', default=os.path.join(ROOT, 'results', 'rtl_chain_results.json')); ap.add_argument('--mhz', type=float, default=150.0)
    ap.add_argument('--json'); a = ap.parse_args()
    results = json.load(open(a.results))
    out = {}
    for label, flags, d in (('float (FPU)', '-O2 -include tgmath.h', 'm33pose_f'), ('double (software)', '-O2', 'm33pose_d')):
        rows = run(flags, d, results, a.mhz)
        out[label] = rows
        v = {k: np.array([r['ms'][k] for r in rows if r['n']]) for k in M.MODELS}
        print(f'pose solve, {label}: frames with tags {len(v["nominal"])}; nominal median {np.median(v["nominal"]):.3f} ms  p95 {np.percentile(v["nominal"], 95):.3f}  '
              f'max {v["nominal"].max():.3f}  (optimistic max {v["optimistic"].max():.3f}, pessimistic max {v["pessimistic"].max():.3f})')
    if a.json:
        json.dump(out, open(a.json, 'w'))


if __name__ == '__main__':
    main()
