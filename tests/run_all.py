"""Run the whole verification suite and print a summary table.

    py -3.12 tests/run_all.py            # everything (~35 min: RTL simulations dominate)
    py -3.12 tests/run_all.py --quick    # skip the long frame-level RTL simulations (~5 min)

Groups run in parallel where they are independent."""
import os, subprocess, sys, time, re
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUPS = [
    # name,                    files,                                                         long?
    ('dataset (Blender/GT)',    ['tests/test_dataset.py'],                                     False),
    ('housing',                 ['tests/test_housing.py'],                                     False),
    ('pcb netlist/pin plan',    ['tests/test_pcb.py'],                                         False),
    ('pose solver (C)',         ['tests/test_pose_solver.py'],                                 False),
    ('firmware proto/storage/app', ['tests/test_fw_proto.py', 'tests/test_fw_storage.py', 'tests/test_fw_app.py'], False),
    ('host library',            ['tests/test_host_e2e.py', 'tests/test_host_fuzz.py'],        False),
    ('TPU ISA/algorithm/RTL',   ['tests/test_tpu.py'],                                         False),
    ('TPU in C vs ISS (bit-exact)', ['tests/test_fw_tpu.py', 'tests/test_m33_cycles.py'],       False),
    ('D-PHY receiver (bit level)', ['tests/test_dphy.py'],                                     False),
    ('despeckle RTL',           ['tests/test_rtl_despeckle.py'],                               False),
    ('CCL RTL',                 ['tests/test_rtl_ccl.py'],                                     False),
    ('device clock RTL (tb_clock)', ['tests/test_clock.py'],                                   False),
    ('CSI-2 RTL',               ['tests/test_csi2.py'],                                        True),
    ('system: cam_core @120fps', ['tests/test_chain.py'],                                      True),
]


def run(group):
    name, files, _ = group
    t = time.time()
    r = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *files], cwd=ROOT, capture_output=True, text=True)
    tail = [l for l in r.stdout.strip().splitlines() if l.strip()][-1] if r.stdout.strip() else r.stderr[-200:]
    m = re.search(r'(\d+) passed', tail); n = int(m.group(1)) if m else 0
    f = re.search(r'(\d+) failed', tail); nf = int(f.group(1)) if f else 0
    return name, n, nf, r.returncode, time.time() - t, tail


def main():
    quick = '--quick' in sys.argv
    groups = [g for g in GROUPS if not (quick and g[2])]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('JOBS', 6))) as ex:
        results = list(ex.map(run, groups))
    print(f'{"group":34s} {"passed":>7s} {"failed":>7s} {"time":>7s}')
    tot = totf = 0
    for name, n, nf, rc, dt, tail in results:
        print(f'{name:34s} {n:7d} {nf:7d} {dt:6.0f}s' + ('' if rc == 0 else f'   <-- {tail}'))
        tot += n; totf += nf
    print(f'{"TOTAL":34s} {tot:7d} {totf:7d}')
    sys.exit(1 if totf or any(r[3] for r in results) else 0)


if __name__ == '__main__':
    main()
