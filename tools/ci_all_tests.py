"""Run every test suite of the repository that is feasible in CI, count passes/failures per suite and write a markdown report.

    python tools/ci_all_tests.py [--out results/ci/all_tests.md] [--only NAME ...] [--full]

Suites (each is a subprocess; a failing suite never stops the others; exit status 1 if any suite failed or could not run):
  python-quick     tests/run_all.py --quick   (all pytest groups of the repo incl. the RTL testbenches via Icarus Verilog: dataset, housing, pcb,
                   pose solver, firmware, host, TPU, D-PHY, despeckle, CCL, device clock = tb/tb_clock.v)
  python-i2c       tests/test_i2c.py          (RTL I2C master + sensor init; not part of run_all.py)
  rtl-long         tests/test_csi2.py + tests/test_chain.py  (long frame-level RTL simulations: CSI-2 packet layer and the whole chip at 120 fps)
  api-python       api/python/tests           (client API, Python)
  api-cpp          make -C api/cpp test       (client API, C++17)
  api-java         api/java/build.sh          (client API, Java)
  api-rust         cargo test                 (client API, Rust)
  golden-frames    api/testdata/gen_golden.py regenerates golden_frames.json and it must equal the committed file
Deliberately EXCLUDED (stated in the report, never silently): tests/run_chain_dataset.py (full RTL chain over all 100 dataset frames,
~40 s per frame, about 7 min with 10 workers on a big machine, hours on a 4-core runner), the Blender dataset generation and everything
that needs the PCB/FPGA toolchains (yosys / nextpnr / KiCad / Pico SDK / arm-none-eabi-gcc).  rtl-long runs by default; --skip-long drops it."""
import os, sys, re, time, shutil, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def sh(cmd, cwd=ROOT, timeout=3600):
    t = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
        out, rc = r.stdout + '\n' + r.stderr, r.returncode
    except FileNotFoundError as e:
        out, rc = f'tool not found: {e}', 127
    except subprocess.TimeoutExpired:
        out, rc = 'TIMEOUT', 124
    return rc, out, time.time() - t


def count_pytest(out):
    p = sum(int(x) for x in re.findall(r'(\d+) passed', out)); f = sum(int(x) for x in re.findall(r'(\d+) failed', out))
    e = sum(int(x) for x in re.findall(r'(\d+) error', out)); s = sum(int(x) for x in re.findall(r'(\d+) skipped', out))
    return p, f + e, s


def run_all_quick():
    rc, out, dt = sh([PY, 'tests/run_all.py', '--quick'])
    m = re.search(r'^TOTAL\s+(\d+)\s+(\d+)', out, re.M)
    p, f = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    table = '\n'.join(l for l in out.splitlines() if re.match(r'^(group|TOTAL|\S.*\s\d+\s+\d+\s+\d+s)', l))
    return dict(rc=rc, passed=p, failed=f, skipped=0, dt=dt, out=out, detail=table)


def run_pytest(args):
    rc, out, dt = sh([PY, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *args])
    p, f, s = count_pytest(out)
    return dict(rc=rc, passed=p, failed=f, skipped=s, dt=dt, out=out, detail='')


def run_cmd(cmd, cwd=ROOT, parse=None):
    rc, out, dt = sh(cmd, cwd)
    p, f = parse(out) if parse else (None, None)
    return dict(rc=rc, passed=p, failed=f, skipped=0, dt=dt, out=out, detail='')


def parse_rust(out):
    return sum(int(x) for x in re.findall(r'test result: \w+\. (\d+) passed', out)), sum(int(x) for x in re.findall(r'(\d+) failed', out))


def parse_summary(out):
    m = re.findall(r'(\d+) passed, (\d+) failed', out)
    return (int(m[-1][0]), int(m[-1][1])) if m else (0, 1)


def golden_check():
    g = os.path.join(ROOT, 'api', 'testdata', 'golden_frames.json')
    before = open(g, 'rb').read()
    rc, out, dt = sh([PY, 'api/testdata/gen_golden.py'])
    norm = lambda b: b.replace(bytes([13, 10]), bytes([10]))          # a Windows checkout may have CRLF line endings
    same = norm(open(g, 'rb').read()) == norm(before)
    if not same:
        open(g, 'wb').write(before)
    return dict(rc=0 if rc == 0 and same else 1, passed=1 if rc == 0 and same else 0, failed=0 if rc == 0 and same else 1, skipped=0, dt=dt,
                out=out + ('' if same else '\ngolden_frames.json differs from the regenerated file'), detail='')


def suites(skip_long):
    S = [('python-quick', 'tests/run_all.py --quick (all pytest groups + RTL testbenches incl. tb_clock)', run_all_quick),
         ('python-i2c', 'tests/test_i2c.py (RTL I2C master + OV9281 init)', lambda: run_pytest(['tests/test_i2c.py'])),
         ('api-python', 'api/python/tests', lambda: run_pytest(['api/python/tests'])),
         ('api-cpp', 'api/cpp (make test)', lambda: run_cmd(['make', '-C', 'api/cpp', 'test'], parse=parse_summary)),
         ('api-java', 'api/java (build.sh: javac + Tests)', lambda: run_cmd(['sh', 'api/java/build.sh'], parse=parse_summary)),
         ('api-rust', 'api/rust (cargo test)', lambda: run_cmd(['cargo', 'test', '--manifest-path', 'api/rust/Cargo.toml'], parse=parse_rust)),
         ('golden-frames', 'api/testdata/golden_frames.json reproducible', golden_check)]
    if not skip_long:
        S.insert(2, ('rtl-long', 'tests/test_csi2.py + tests/test_chain.py (long frame-level RTL simulations)', lambda: run_pytest(['tests/test_csi2.py', 'tests/test_chain.py'])))
    return S


EXCLUDED = ['`tests/run_chain_dataset.py` - full RTL chain over the 100 dataset frames (~40 s per frame); the dataset is covered at reference-detector level by the ten `dataset-<category>` workflows',
            'Blender dataset generation (`tools/make_dataset_100.py` renders; needs Blender + GPU) - the committed frames and ground truth are checked by `tests/test_dataset.py`',
            'FPGA / PCB / MCU toolchain flows (yosys, nextpnr, KiCad, freerouting, Pico SDK, arm-none-eabi-gcc) - these are build flows, not tests of this repo']


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=os.path.join(ROOT, 'results', 'ci', 'all_tests.md'))
    ap.add_argument('--only', nargs='*'); ap.add_argument('--skip-long', action='store_true')
    a = ap.parse_args()
    results = []
    for name, desc, fn in suites(a.skip_long):
        if a.only and name not in a.only: continue
        print(f'--- {name}: {desc}', flush=True)
        r = fn(); r.update(name=name, desc=desc); results.append(r)
        print(r['out'][-1500:], flush=True)
        print(f"--- {name}: rc={r['rc']} passed={r['passed']} failed={r['failed']} {r['dt']:.0f}s", flush=True)
    bad = [r for r in results if r['rc'] != 0 or r['failed']]
    P = sum(r['passed'] or 0 for r in results); F = sum(r['failed'] or 0 for r in results)
    fmt = lambda v: '-' if v is None else str(v)
    L = [f"### All tests: {'FAILED' if bad else 'passed'} - {P} passed, {F} failed in {len(results)} suites ({len(bad)} suite(s) failing)", '',
         '| suite | what | passed | failed | skipped | time | status |', '|---|---|---|---|---|---|---|']
    for r in results:
        L.append(f"| {r['name']} | {r['desc']} | {fmt(r['passed'])} | {fmt(r['failed'])} | {r['skipped']} | {r['dt']:.0f}s | {'ok' if r['rc'] == 0 and not r['failed'] else 'FAIL (rc ' + str(r['rc']) + ')'} |")
    L += ['', 'Excluded from CI (not run, by design):'] + [f'- {x}' for x in EXCLUDED]
    for r in results:
        if r['detail']:
            L += ['', f"<details><summary>{r['name']} per group</summary>", '', '```', r['detail'], '```', '</details>']
    for r in bad:
        L += ['', f"<details><summary>{r['name']} output (tail)</summary>", '', '```', r['out'][-3000:], '```', '</details>']
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[:len(results) + 6]))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
