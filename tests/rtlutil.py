"""Helpers to build/run Icarus Verilog testbenches from pytest or the CLI."""
import os, subprocess, sys, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import shutil
_WIN_BIN = r"C:\msys64\ucrt64\bin"
# Windows dev box: MSYS2 ucrt64; elsewhere (Linux CI): iverilog / vvp from PATH (apt install iverilog)
BIN = _WIN_BIN if (os.name == "nt" and os.path.isdir(_WIN_BIN)) else os.path.dirname(shutil.which("iverilog") or "")
SIM = os.path.join(ROOT, "sim")
os.makedirs(SIM, exist_ok=True)

def _env():
    e = dict(os.environ)
    if BIN: e["PATH"] = BIN + os.pathsep + e["PATH"]
    return e

def build(name, files, defines=(), top=None):
    out = os.path.join(SIM, name + ".vvp")
    cmd = [os.path.join(BIN, "iverilog"), "-g2012", "-o", out] + [f"-D{d}" for d in defines]
    if top: cmd += ["-s", top]
    cmd += [os.path.join(ROOT, f) for f in files]
    r = subprocess.run(cmd, capture_output=True, text=True, env=_env())
    if r.returncode: raise RuntimeError(r.stdout + r.stderr)
    return out

def run(vvp, plusargs=(), timeout=3000):
    cmd = [os.path.join(BIN, "vvp"), vvp] + [f"+{a}" for a in plusargs]
    r = subprocess.run(cmd, capture_output=True, text=True, env=_env(), timeout=timeout)
    return r.stdout + r.stderr
