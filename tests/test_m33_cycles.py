"""The C TPU cross-compiled for Cortex-M33 and run in the Unicorn emulator gives the PC build's results and stays inside the time budget of
docs/costdown.md experiment 1 (tools/m33_cycles.py --check; asserts inside: emulated == PC result, pessimistic worst < 12 ms).
Skipped when arm-none-eabi-gcc / unicorn / capstone are not installed (CI).  Runs in a subprocess because Unicorn can crash the host process."""
import os, sys, shutil, subprocess, pytest
pytest.importorskip('unicorn'); pytest.importorskip('capstone')
if not (shutil.which('arm-none-eabi-gcc') or os.path.exists('C:/msys64/ucrt64/bin/arm-none-eabi-gcc.exe')):
    pytest.skip('arm-none-eabi-gcc not installed', allow_module_level=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_m33_matches_pc_and_meets_budget():
    for attempt in range(2):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'm33_cycles.py'), '--opt=-O3', '--check'], capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0:
            return
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
