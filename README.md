# AprilTag camera: custom vision chip + 120 fps global-shutter camera, one USB-C cable

A self-contained camera that detects AprilTags (tag36h11) at **1280x800 / 120 fps** and hands back the **camera's pose
in a world frame you define**. You send it the tags you use and where they are (plus the lens calibration) once; it
stores them in flash and then streams the camera position and orientation over the same USB-C cable that powers it.

```
OV9281 (MIPI, 120 fps) -> ECP5 LFE5U-25F FPGA running custom RTL (threshold, despeckle, labelling, frame streamer) -> 8-bit frame bus ->
                          RP2350 MCU (tag decoder in C, pose solve, USB, stored field map) -> host
```

Nothing here is a stock vision pipeline: the per-pixel work is **hardware designed in Verilog in this repo**, the per-tag work (sub-pixel
corner fitting, tag36h11 decoding) is C code in this repo that runs on the MCU on the binary frame the FPGA streams to it (architecture "A3",
`docs/costdown.md`; it started life as a custom FPGA processor, the TPU, kept in `ref/tpu` as the bit-exact reference). The host only sees the tag
estimates and poses, never an image.

## What is in the box

| directory | contents |
|---|---|
| `rtl/` | the chip: D-PHY + CSI-2 receiver, adaptive threshold, despeckle, connected components, the MCU frame streamer (`mask_stream`), SPI/I2C, top levels, pin constraints (`apriltag_cam.lpf`) |
| `tools/` | golden Python models of every block, TPU assembler + instruction-set simulator + the program (`tpu_prog.py`, the golden model of `firmware/core/attpu.c`), Cortex-M33 timing estimators (`m33_cycles.py`, `m33_pose_cycles.py`, `frame_budget.py`), Blender scene/dataset generator, reference detector, sensor init generator, FPGA flow scripts |
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
py -3.12 tools/tpu_prog.py                # assemble the reference TPU program (ref/tpu/tpu_prog.hex)
py -3.12 tools/m33_cycles.py              # run time of the C tag unit on a Cortex-M33 (Unicorn + cycle model)
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

**RP2350 firmware image.** Build on Linux (the Windows msys `ld` 2.47 fails the Pico SDK link with "pico_flash_region.ld appears multiple times", so
Windows is not a supported firmware build host). Needs `gcc-arm-none-eabi` (CI: Ubuntu 24.04 package, 13.2.1), `libnewlib-arm-none-eabi`, `cmake`, `ninja` and
Pico SDK **2.1.1** with submodules (tinyusb); the SDK builds picotool from source on first configure (network needed):
```
git clone --depth 1 --branch 2.1.1 --recurse-submodules --shallow-submodules https://github.com/raspberrypi/pico-sdk.git ~/pico-sdk
cmake -S firmware/rp2350 -B build/rp2350 -G Ninja -DPICO_SDK_PATH=~/pico-sdk && cmake --build build/rp2350
python3 tools/fw_size.py build/rp2350/apriltag_cam.elf --bin build/rp2350/apriltag_cam.bin --uf2 build/rp2350/apriltag_cam.uf2
```
The workflow `.github/workflows/firmware.yml` does this on every pull request that touches `firmware/`, checks the `.uf2` structure, uploads
`apriltag_cam.uf2/.elf/.bin/.elf.map` as the artifact `rp2350-firmware` and posts the size report (flash image vs 16 MB, static SRAM vs 520 KB) on the PR.
It never creates a release. Flash the `.uf2` by holding BOOTSEL while plugging in USB and copying the file to the `RP2350` drive (not yet tried on hardware).

**Releasing:** pushing to the `deploy` branch (`git push origin main:deploy`, or merge `main` into `deploy`) runs `.github/workflows/release.yml`.
It installs the toolchains, runs `tools/build_all.sh --strict`, uploads `products/` as a workflow artifact, and creates a NEW GitHub Release
tagged `deploy-<run_number>-<short sha>` with the products and manifest attached and notes listing the commit, date, tool versions and
build/test results. Earlier releases are never overwritten. `main` does not trigger releases. The workflow can also be started manually
(workflow_dispatch) from any ref; the manual run has a `dry_run` input (default true) that does everything except `gh release create`
(it still lists the assets and checks that `firmware_apriltag_cam.uf2/.elf` are present). It uses `GITHUB_TOKEN` with `contents: write`.

## Headline results (details and caveats in `docs/verification.md`, `docs/fpga.md`, `docs/hardware.md`)

* **120.08 fps** sustained in full-chip simulation at true sensor timing (832,800 clocks per frame at 100 MHz), every frame leaves the FPGA
  as a complete packet; the MCU has two frame buffers so capture never stalls.
* 100 rendered frames (10 conditions x 10, rendered for the shipping lens: CIL023, 82.2 degrees HFOV, fx 733 px, -5 % TV distortion) through the simulated chip + the MCU's solver: **median camera position error about
  1-5 mm and 0.03-0.17 deg per category** where tags are found; **88 % of the detectable tags overall (501 / 570; the reference AprilTag library: 98 %)**,
  100 % on dark / grad / noise / normal, 99 % bright, 92-94 % clutter / blur / persp, 90 % shadow, but still
  **2 % on the low-contrast category** with the reset THRESH ratio (54 / 54 with ratio 1, chosen automatically by the firmware), see `docs/verification.md`.
* GitHub Actions: one check per dataset category (`N/10 detected`, reference detector) plus an all-tests workflow, see `docs/verification.md`.
* RTL is verified bit-exact against Python golden models (threshold, despeckle, labelling), the C tag unit bit-exact against the golden model of the old FPGA processor, and the whole
  chain is exercised with real CSI-2 packets and a bit-level D-PHY model with lane skew and clock offsets.
* Open-source place-and-route onto the real ECP5 CABGA-381 pins, shipping part LFE5U-25F-8BG381I: 13.4 k LUT4 (55 %), 56 of 56 block RAM (100 %, no margin), core clock closes 85.7 MHz and D-PHY 200 MHz on 7 of 7 seeds (nextpnr estimates, not signoff; `docs/fpga.md`). Earlier 45F numbers (12.2 k LUT4, 56 of 108 block RAM, 4 of 6 seeds, older RTL and tools) are kept in `docs/fpga.md`, labelled as 45F.

## Honest limits - read before building hardware

1. **Not run on silicon.** Everything is simulated or tool-checked; there is no physical board. The ECP5 D-PHY receiver
   (LVDS gearing, sync hunt) and the OV9281 bring-up are the first things to validate on a prototype.
2. **OV9281 footprint**: the ball map comes from an open-hardware reference design, but the CSP ball pitch/pad size
   is assumed (0.5 mm / 0.25 mm). Verify against OmniVision's drawing before ordering. Bare-CSP assembly with an
   M12 holder needs a specialist assembler.
3. **Timing closure**: see `docs/fpga.md` for the measured fmax of each clock domain against the 100 MHz / 200 MHz
   targets. Anything reported as failing there must be fixed (more pipelining) before relying on 120 fps in hardware.
4. Detection is weaker than the reference library at long range (> ~3.5 m for 16.5 cm tags), for low-contrast scenes (0 % on the
   `lowcon` category with the reset THRESH ratio; 100 % with ratio 2, see `results/lowcon_ratio.md`) and for small / grazing / shadowed tags. The labeller no longer rejects busy frames (256 runs/row, label recycling,
   the 64 largest candidates kept), but a cluttered or noisy frame costs the MCU up to about 9 ms (estimate, Cortex-M33 emulation, median 1.6 ms; the old FPGA processor
   needed up to 30 ms): in a stream at 120 fps a heavy frame can make the MCU miss a packet (`frames_dropped`); the model predicts 1 - 4 % of frames
   if every 10th frame were the slowest of its category (`results/frame_budget.md`; the old design: 20 %). The MCU timing, the PIO/DMA frame
   capture and the bus timing margin are **not measured on hardware**.
5. No schematic capture: the board is netlist-first (`pcb/design.py`, `pcb/output/netlist.txt`).
