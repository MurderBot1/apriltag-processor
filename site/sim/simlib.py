"""Shared helpers: Icarus Verilog build/run in a scratch directory (never in the project root or sim/)."""
import os, re, subprocess, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(HERE, 'work')
BIN = None
for cand in (r'C:\msys64\ucrt64\bin', r'C:\msys64\mingw64\bin'):
    if os.path.exists(os.path.join(cand, 'iverilog.exe')):
        BIN = cand; break
if BIN is None:
    for d in os.environ.get('PATH', '').split(os.pathsep):
        if os.path.exists(os.path.join(d, 'iverilog.exe')) or os.path.exists(os.path.join(d, 'iverilog')):
            BIN = d; break
sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, os.path.join(ROOT, 'tests'))


def env():
    e = dict(os.environ); e['PATH'] = (BIN or '') + os.pathsep + e['PATH']; return e


def build(name, files, defines=(), params=(), top='tb'):
    """compile; files are repo-relative (rtl/..) or absolute (site/sim/tb/..)."""
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, name + '.vvp')
    cmd = [os.path.join(BIN, 'iverilog'), '-g2012', '-o', out, '-s', top] + ['-D' + d for d in defines] + ['-P%s.%s' % (top, p) for p in params]
    cmd += [f if os.path.isabs(f) else os.path.join(ROOT, f) for f in files]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env(), cwd=WORK)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return out


def run(vvp, plusargs=(), timeout=3000):
    cmd = [os.path.join(BIN, 'vvp'), vvp] + ['+' + a for a in plusargs]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env(), timeout=timeout, cwd=WORK)
    return r.stdout + r.stderr


def tb(name):
    return os.path.join(HERE, 'tb', name)


def localparams(path, prefix=None):
    """name -> value for 'localparam ... NAME = number' definitions in a verilog file."""
    txt = open(os.path.join(ROOT, path)).read()
    d = {}
    for m in re.finditer(r'localparam\s*(?:\[[^\]]*\])?\s*([^;]*);', txt):
        for nm, val in re.findall(r'(\w+)\s*=\s*(?:\d+\'[dD])?(\d+)', m.group(1)):
            if prefix is None or nm.startswith(prefix):
                d[nm] = int(val)
    return d
