# AprilTag camera: custom vision chip + 120 fps global-shutter camera, one USB-C cable

A self-contained camera that detects AprilTags (tag36h11) at **1280x800 / 120 fps** and hands back the **camera's pose
in a world frame you define**. You send it the tags you use and where they are (plus the lens calibration) once; it
stores them in flash and then streams the camera position and orientation over the same USB-C cable that powers it.

```
OV9281 (MIPI, 120 fps) -> ECP5 FPGA running custom RTL (threshold, labelling, own CPU with the tag decoder baked into
                          its ROM) -> RP2350 MCU (USB, stored field map, pose solve) -> host
```

Nothing here is a stock vision pipeline: the per-pixel and per-tag work is **hardware designed in Verilog in this repo**,
including a small custom processor (the TPU) whose program is burned into the chip image. The MCU only sees the tag
estimates (id + sub-pixel corners), never an image.

## What is in the box

| directory | contents |
|---|---|
| `rtl/` | the chip: D-PHY + CSI-2 receiver, adaptive threshold, despeckle, connected components, **TPU** (custom processor + baked tag36h11 ROM), SPI/I2C, top levels, pin constraints (`apriltag_cam.lpf`), generated TPU program (`tpu_prog.hex`) |
| `tools/` | golden Python models of every block, TPU assembler + instruction-set simulator + the baked program (`tpu_prog.py`), Blender scene/dataset generator, reference detector, sensor init generator, FPGA flow scripts |
| `tb/`, `tests/` | Verilog testbenches and 226 pytest tests (see `docs/verification.md`) |
| `test_images/` | **100 rendered 1280x800 test frames in 10 categories of 10** (normal, bright, dark, low-contrast, gradient light, shadow, noise, clutter, blur, perspective; Blender Cycles, lens distortion + sensor noise model) with ground-truth poses (`ground_truth.json`) |
| `firmware/core`, `firmware/rp2350` | MCU firmware: pose solver, USB protocol, flash storage, auto exposure; RP2350 (Pico SDK) port |
| `host/` | Python library + CLI (`atcam.py`) with a simulated device so everything runs without hardware |
| `pcb/` | 4-layer 48 x 48 mm board generated from code (`design.py`, `build_pcb.py`), routed, fabrication outputs |
| `housing/` | 3D-printable two-part enclosure (OpenSCAD, STLs) |
| `docs/` | architecture, hardware, protocol, verification, FPGA results |
| `config/` | example field map (`tag_map.json`) and camera calibration |

## Using it

```python
import sys; sys.path.insert(0, "host")
from apriltag_cam import Camera, load_json
with Camera.open_serial("COM5") as cam:               # USB-C CDC serial port
    cam.set_calibration(load_json("config/camera_calibration.json"))
    cam.set_field(load_json("config/tag_map.json"))   # tag ids, sizes, 3D positions + orientations (quaternion wxyz)
    cam.commit()                                      # stored in flash; survives power cycles
    for pose in cam.stream():                         # ~120 Hz
        print(pose.frame_id, pose.position, pose.quaternion, pose.ntags, pose.rms_px)
```
`py -3.12 host/atcam.py --sim configure --map config/tag_map.json --calib config/camera_calibration.json` and `... --sim stream` run the same flow against the simulated device (native firmware + a fake FPGA fed with real RTL results).
Protocol: `docs/protocol.md`. Conventions (world, tag, camera frames, corner order) are at the top of `tools/geom.py`.

## Rebuilding / re-running

```
py -3.12 tools/make_tags.py               # tag images + the 587-code ROM table
py -3.12 tools/make_dataset_100.py        # the 100-image dataset: Blender renders (needs Blender 5.x) -> test_images/ (deterministic, see docs/verification.md)
py -3.12 tools/tpu_prog.py                # assemble the TPU program ROM (rtl/tpu_prog.hex)
py -3.12 tests/run_all.py                 # the whole verification suite
bash tools/fpga_flow.sh                   # yosys + nextpnr-ecp5 (+ ecppack bitstream)
"C:/Program Files/KiCad/10.0/bin/python.exe" pcb/build_pcb.py --route ; py -3.12 pcb/make_outputs.py
```
Tools used: Icarus Verilog 13, Yosys 0.66, nextpnr-ecp5 0.7, KiCad 10, Freerouting 2.1, OpenSCAD 2021, Blender 5.1,
arm-none-eabi-gcc, Pico SDK (all installed during the build; see `docs/`).

## Build and release (deploy)

`bash tools/build_all.sh [--strict] [--skip-tests] [--skip-fpga]` builds every buildable output into `products/` (git-ignored) and writes
`products/MANIFEST.json` / `MANIFEST.txt` (commit, build date, tool versions, per-step ok/skipped/failed with notes, and file name, size and sha256).
Products: FPGA bitstream + netlist/config + timing/utilisation reports (yosys, nextpnr-ecp5, ecppack), RP2350 firmware (`.uf2/.elf/.bin`, needs
arm-none-eabi-gcc + Pico SDK via `PICO_SDK_PATH`), native firmware-sim library, host bundle + configs, Python wheel, C++ static lib + headers,
Java jar, Rust `.crate`/rlib, docs tarball and the committed PCB gerbers/BOM (copied, not regenerated; needs KiCad). A step whose toolchain is
missing is recorded as `skipped` in the manifest (never faked); set `REQUIRE="fpga firmware ..."` to make that an error. A timing miss in the FPGA
flow is recorded as a `warning`, and the bitstream is still produced.

**Releasing:** pushing to the `deploy` branch (`git push origin main:deploy`, or merge `main` into `deploy`) runs `.github/workflows/release.yml`.
It installs the toolchains, runs `tools/build_all.sh --strict`, uploads `products/` as a workflow artifact, and creates a NEW GitHub Release
tagged `deploy-<run_number>-<short sha>` with the products and manifest attached and notes listing the commit, date, tool versions and
build/test results. Earlier releases are never overwritten. `main` does not trigger releases. The workflow can also be started manually
(workflow_dispatch) from any ref. It uses `GITHUB_TOKEN` with `contents: write`.

## Headline results (details and caveats in `docs/verification.md`, `docs/fpga.md`, `docs/hardware.md`)

* **120.08 fps** sustained in full-chip simulation at true sensor timing (832,800 clocks per frame at 100 MHz), no dropped
  frames, two frame banks so capture never stalls.
* 100 rendered frames (10 conditions x 10) through the simulated chip + the MCU's solver: **median camera position error about
  1-3 mm and 0.02-0.05 deg** where tags are found; 70 % of the detectable tags overall (the reference AprilTag library: 97 %) -
  95 % on the clean baseline but 0 % on the low-contrast and 14 % on the cluttered category, see `docs/verification.md`.
* GitHub Actions: one check per dataset category (`N/10 detected`, reference detector) plus an all-tests workflow, see `docs/verification.md`.
* RTL is verified bit-exact against Python golden models (threshold, despeckle, labelling, the custom CPU), and the whole
  chain is exercised with real CSI-2 packets and a bit-level D-PHY model with lane skew and clock offsets.
* Open-source place-and-route onto the real ECP5-85F pins, with measured resource use and timing (`docs/fpga.md`).

## Honest limits - read before building hardware

1. **Not run on silicon.** Everything is simulated or tool-checked; there is no physical board. The ECP5 D-PHY receiver
   (LVDS gearing, sync hunt) and the OV9281 bring-up are the first things to validate on a prototype.
2. **OV9281 footprint**: the ball map comes from an open-hardware reference design, but the CSP ball pitch/pad size
   is assumed (0.5 mm / 0.25 mm). Verify against OmniVision's drawing before ordering. Bare-CSP assembly with an
   M12 holder needs a specialist assembler.
3. **Timing closure**: see `docs/fpga.md` for the measured fmax of each clock domain against the 100 MHz / 200 MHz
   targets. Anything reported as failing there must be fixed (more pipelining) before relying on 120 fps in hardware.
4. Detection is weaker than the reference library at long range (> ~3.5 m for 16.5 cm tags), in very low light (until
   the MCU's auto-exposure runs) and in cluttered, dim backgrounds (the labeller drops rows beyond ~55 runs/row and
   flags it).
5. No schematic capture: the board is netlist-first (`pcb/design.py`, `pcb/output/netlist.txt`).
