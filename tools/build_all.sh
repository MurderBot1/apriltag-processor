#!/bin/bash
# Build every buildable output of the repo into products/ and write products/MANIFEST.json + MANIFEST.txt.
#
# usage: tools/build_all.sh [--strict] [--skip-tests] [--skip-fpga] [--out DIR]
#   --strict      exit non-zero if any step FAILED (a missing toolchain is recorded as "skipped",
#                 unless that step is listed in REQUIRE="fpga firmware" in the environment, then it is "failed")
#   --skip-tests  do not run the unit tests that accompany each client build
#   --skip-fpga   skip the (slow) yosys/nextpnr flow
# Nothing is faked: a step that cannot run is recorded in the manifest as skipped/failed with a note.
# Environment: PICO_SDK_PATH (RP2350 firmware), FPGA_SEED, FPGA_FREQ, RUN_SUITE=1 (also run tests/run_all.py).
set -u
STRICT=0; TESTS=1; FPGA=1
ROOT=$(cd "$(dirname "$0")/.." && pwd); OUT="$ROOT/products"
while [ $# -gt 0 ]; do
  case $1 in
    --strict) STRICT=1;; --skip-tests) TESTS=0;; --skip-fpga) FPGA=0;;
    --out) mkdir -p "$2"; OUT=$(cd "$2" && pwd); shift;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac; shift
done
export PATH=/c/msys64/ucrt64/bin:$PATH
cd "$ROOT"
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
have() { command -v "$1" >/dev/null 2>&1; }
rm -rf "$OUT"; mkdir -p "$OUT"/fpga "$OUT"/firmware "$OUT"/host "$OUT"/api/python "$OUT"/api/cpp "$OUT"/api/java "$OUT"/api/rust "$OUT"/docs "$OUT"/config "$OUT"/logs
STEPS="$OUT/logs/steps.tsv"; : > "$STEPS"
FAILED=0
record() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$STEPS"; echo "[build_all] $1: $2 $3"; [ "$2" = failed ] && FAILED=1; return 0; }
# step NAME LOGNAME cmd...   runs the command, keeps its log, records ok/failed
step() { local n=$1 l=$OUT/logs/$2.log; shift 2; if "$@" >"$l" 2>&1; then record "$n" ok ""; return 0; else record "$n" failed "see logs/$(basename "$l")"; return 1; fi; }
skip() { record "$1" skipped "$2"; }
# if step is in REQUIRE, a missing tool is a failure rather than a skip
unavailable() { case " ${REQUIRE:-} " in *" $1 "*) record "$1" failed "required but $2";; *) record "$1" skipped "$2";; esac; }

# ---- FPGA: yosys + nextpnr-ecp5 + ecppack ---------------------------------------------------
if [ $FPGA = 0 ]; then skip fpga "--skip-fpga given"
elif have yosys && have nextpnr-ecp5 && have ecppack; then
  mkdir -p sim
  step fpga fpga bash tools/fpga_flow.sh "${FPGA_SEED:-1}" "${FPGA_FREQ:-85.714}"
  if [ -f sim/apriltag_cam.bit ] && grep -q FLOW_DONE sim/nextpnr.out 2>/dev/null; then
    cp sim/apriltag_cam.bit sim/timing.json sim/yosys_top.out sim/nextpnr.log "$OUT/fpga/" 2>/dev/null
    gzip -9 -c sim/top.json > "$OUT/fpga/top.json.gz"; gzip -9 -c sim/top.cfg > "$OUT/fpga/top.cfg.gz"   # netlist + textual config (large)
    cp rtl/apriltag_cam.lpf "$OUT/fpga/"
    { grep -E "Max frequency for clock" sim/nextpnr.log | tail -4; grep -A14 "Device utilisation" sim/nextpnr.log | tail -15; } > "$OUT/fpga/summary.txt"
    if grep -q "FAIL at" "$OUT/fpga/summary.txt"; then record fpga-timing warning "timing NOT met at ${FPGA_FREQ:-85.714} MHz target (see fpga/summary.txt); bitstream still produced"; fi
  else
    record fpga-bitstream failed "no bitstream / FLOW_DONE marker (see logs/)"; cp sim/*.out sim/*.log "$OUT/logs/" 2>/dev/null
  fi
else unavailable fpga "yosys/nextpnr-ecp5/ecppack not installed"; fi

# ---- RP2350 firmware (arm-none-eabi-gcc + Pico SDK 2.x + cmake) ----------------------------
if have arm-none-eabi-gcc && have cmake && [ -n "${PICO_SDK_PATH:-}" ] && [ -f "${PICO_SDK_PATH}/pico_sdk_init.cmake" ]; then
  GEN=""; have ninja && GEN="-G Ninja"
  if step firmware firmware bash -c "cmake -S firmware/rp2350 -B build/rp2350 $GEN -DPICO_SDK_PATH='$PICO_SDK_PATH' && cmake --build build/rp2350 -j"; then
    for e in uf2 elf bin hex elf.map; do [ -f "build/rp2350/apriltag_cam.$e" ] && cp "build/rp2350/apriltag_cam.$e" "$OUT/firmware/"; done
    [ -f "$OUT/firmware/apriltag_cam.uf2" ] || record firmware-uf2 failed "build ok but no uf2 produced"
    if [ -f "$OUT/firmware/apriltag_cam.elf" ] && have arm-none-eabi-size; then
      step firmware-size firmware_size $PY tools/fw_size.py "$OUT/firmware/apriltag_cam.elf"         $([ -f "$OUT/firmware/apriltag_cam.bin" ] && echo --bin "$OUT/firmware/apriltag_cam.bin")         $([ -f "$OUT/firmware/apriltag_cam.uf2" ] && echo --uf2 "$OUT/firmware/apriltag_cam.uf2") --out "$OUT/firmware/size.md"
    fi
  fi
else unavailable firmware "arm-none-eabi-gcc, cmake or PICO_SDK_PATH (Pico SDK 2.x with tinyusb) not available"; fi

# ---- Native firmware-simulation library (host --sim, tests) ---------------------------------
if have gcc; then
  EXT=so; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) EXT=dll;; Darwin) EXT=dylib;; esac
  step firmware-sim firmware_sim gcc -O2 -Wall -Wextra -shared -fPIC -Ifirmware/core firmware/core/atpose.c firmware/core/atproto.c \
    firmware/core/atapp.c firmware/core/atae.c firmware/core/atframe.c firmware/core/attpu.c firmware/tests/atfw_shim.c -o "$OUT/firmware/libatfw.$EXT" -lm
else unavailable firmware-sim "gcc not installed"; fi

# ---- Host software + configs ----------------------------------------------------------------
tar -czf "$OUT/host/apriltag-host.tar.gz" --exclude=__pycache__ host config tools/geom.py && record host-bundle ok "host/ config/ tools/geom.py"
cp config/*.json "$OUT/config/"

# ---- Python client wheel --------------------------------------------------------------------
if have $PY && $PY -m pip --version >/dev/null 2>&1; then
  step api-python-wheel api_python_wheel $PY -m pip wheel --no-deps --no-build-isolation -w "$OUT/api/python" api/python \
    || step api-python-wheel api_python_wheel_isolated $PY -m pip wheel --no-deps -w "$OUT/api/python" api/python
  if [ $TESTS = 1 ]; then
    step api-python-tests api_python_tests env PYTHONPATH=api/python $PY -m pytest -q api/python/tests \
      || step api-python-tests api_python_tests_direct env PYTHONPATH=api/python $PY api/python/tests/test_api.py
  fi
else unavailable api-python "python/pip not installed"; fi
rm -rf api/python/build api/python/*.egg-info

# ---- C++ client library ---------------------------------------------------------------------
if have g++ && have make; then
  if step api-cpp api_cpp make -C api/cpp all; then
    cp api/cpp/build/libapriltag_camera.a "$OUT/api/cpp/"; cp -r api/cpp/include "$OUT/api/cpp/"
    [ $TESTS = 1 ] && step api-cpp-tests api_cpp_tests make -C api/cpp test
  fi
else unavailable api-cpp "g++/make not installed"; fi

# ---- Java client jar ------------------------------------------------------------------------
if have javac && have jar; then
  if step api-java api_java sh api/java/build.sh $([ $TESTS = 1 ] || echo nottest); then cp api/java/apriltag-camera.jar "$OUT/api/java/"; git checkout -- api/java/apriltag-camera.jar 2>/dev/null; fi
else unavailable api-java "JDK (javac/jar) not installed"; fi

# ---- Rust client crate ----------------------------------------------------------------------
if have cargo; then
  if step api-rust api_rust bash -c "cd api/rust && cargo package --allow-dirty --locked --no-verify && cargo build --release --locked"; then
    cp api/rust/target/package/*.crate "$OUT/api/rust/" 2>/dev/null
    cp api/rust/target/release/libapriltag_camera.rlib "$OUT/api/rust/" 2>/dev/null
    [ $TESTS = 1 ] && step api-rust-tests api_rust_tests bash -c "cd api/rust && cargo test --locked"
  fi
else unavailable api-rust "cargo not installed"; fi

# ---- Docs, and hardware outputs already committed (not regenerated; that needs KiCad) -------
tar -czf "$OUT/docs/docs.tar.gz" docs README.md api/README.md && record docs ok "docs/ + READMEs"
if [ -f pcb/output/apriltag_cam_gerbers.zip ]; then
  cp pcb/output/apriltag_cam_gerbers.zip pcb/output/bom.csv "$OUT/docs/" 2>/dev/null
  record pcb-fab ok "committed gerbers/BOM copied as-is (not rebuilt: needs KiCad)"
fi

# ---- Full project verification suite (optional, slow) ---------------------------------------
if [ "${RUN_SUITE:-0}" = 1 ]; then step suite suite $PY tests/run_all.py; fi

# ---- Manifest -------------------------------------------------------------------------------
$PY - "$OUT" "$ROOT" <<'PYEOF'
import hashlib, json, os, subprocess, sys, datetime, shutil
out, root = sys.argv[1], sys.argv[2]
def sh(*c):
    try: return subprocess.run(c, capture_output=True, text=True, cwd=root, timeout=20).stdout.strip().splitlines()[0]
    except Exception: return None
def ver(*c): return sh(*c) if shutil.which(c[0]) else None
steps = []
for l in open(os.path.join(out, 'logs', 'steps.tsv')):
    n, s, note = (l.rstrip('\n').split('\t') + ['', ''])[:3]
    steps.append({'step': n, 'status': s, 'note': note})
files = []
for d, _, fs in os.walk(out):
    for f in fs:
        if f.startswith('MANIFEST'): continue
        p = os.path.join(d, f)
        files.append({'path': os.path.relpath(p, out).replace('\\', '/'), 'bytes': os.path.getsize(p),
                      'sha256': hashlib.sha256(open(p, 'rb').read()).hexdigest()})
files.sort(key=lambda x: x['path'])
tools = {'python': sys.version.split()[0], 'git': ver('git', '--version'), 'gcc': ver('gcc', '--version'),
         'g++': ver('g++', '--version'), 'yosys': ver('yosys', '-V'), 'nextpnr-ecp5': (subprocess.run(['nextpnr-ecp5','--version'],capture_output=True,text=True).stderr.strip() or None) if shutil.which('nextpnr-ecp5') else None,
         'arm-none-eabi-gcc': ver('arm-none-eabi-gcc', '--version'), 'cmake': ver('cmake', '--version'),
         'javac': ver('javac', '-version'), 'cargo': ver('cargo', '--version'), 'rustc': ver('rustc', '--version')}
dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], capture_output=True, text=True, cwd=root).stdout.strip()
m = {'git_commit': sh('git', 'rev-parse', 'HEAD'), 'git_branch': sh('git', 'rev-parse', '--abbrev-ref', 'HEAD'), 'git_dirty': bool(dirty),
     'build_date_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'host_platform': sys.platform,
     'tool_versions': {k: v for k, v in tools.items() if v}, 'tools_missing': [k for k, v in tools.items() if not v],
     'steps': steps, 'files': files}
json.dump(m, open(os.path.join(out, 'MANIFEST.json'), 'w'), indent=2)
with open(os.path.join(out, 'MANIFEST.txt'), 'w') as t:
    t.write(f"commit {m['git_commit']} ({m['git_branch']}{', dirty' if m['git_dirty'] else ''})\nbuilt  {m['build_date_utc']} on {m['host_platform']}\n\nSTEPS\n")
    for s in steps: t.write(f"  {s['status']:8} {s['step']}  {s['note']}\n")
    t.write('\nTOOLS\n')
    for k, v in m['tool_versions'].items(): t.write(f"  {k}: {v}\n")
    if m['tools_missing']: t.write('  not installed: ' + ', '.join(m['tools_missing']) + '\n')
    t.write('\nFILES (sha256  bytes  path)\n')
    for f in files: t.write(f"  {f['sha256']}  {f['bytes']:>9}  {f['path']}\n")
PYEOF
echo "[build_all] manifest: $OUT/MANIFEST.txt"
if [ $STRICT = 1 ] && [ $FAILED = 1 ]; then echo "[build_all] FAILED steps present" >&2; exit 1; fi
exit 0
