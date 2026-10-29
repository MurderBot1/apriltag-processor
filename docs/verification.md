# Verification

Run everything with `py -3.12 tests/run_all.py` (about 35 minutes; `--quick` skips the long frame-level RTL runs).
226 tests in 16 files. What each layer proves:

| layer | file | tests | what it proves |
|---|---|---|---|
| dataset | `test_dataset.py` | 7 | 100 Blender-rendered 1280x800 frames, ground truth reprojects consistently, reference detector finds the tags |
| CSI-2 packet layer (RTL) | `test_csi2.py` | 8 | clean frame, 1-bit header errors corrected, 2-bit errors dropped (all 276+144 double-error combinations are detectable: odd-weight SEC-DED columns), CRC errors, missing line, truncated burst, recovery, ignored packet types |
| D-PHY receiver (RTL, bit level) | `test_dphy.py` | 12 | real lane bit streams at 800 Mb/s: lane skew 0-21 UI, +-200 ppm clock offset, noise between bursts, slot jitter, header bit errors, back-to-back frames, **reversed gearbox bit order** |
| threshold (RTL) | (bit-exact script in `run_all`/`tests/rtlutil`) | - | 0 mismatching pixels vs `tools/golden.py` on 1280x800 frames |
| despeckle (RTL) | `test_rtl_despeckle.py` | 4 | bit-exact vs golden on 35 % random noise, edge/corner structures, a real mask, all-ones/zeros |
| connected components (RTL) | `test_rtl_ccl.py` | 14 | areas, bounding boxes and all 8 extremes identical to scipy labelling on random shapes, merging combs, parity edge cases, whole-frame black, **overflow flags + clean recovery on the next frame**, row-time budget; **noise robustness**: a 200-runs-per-row frame, 3040 one-pixel components then a real ring (label recycling), 100 components of increasing area (the 64 largest survive, table order equals `golden.stream_components`), every resource overflowing at once (frame still completes), a 16-entry label table (runs without a label stay background, RTL == model), 200-run rows at the real 686-clock line period (nothing dropped) |
| TPU | `test_tpu.py` | 14 | ISA semantics, **RTL == ISS bit-exact** (micro-program over all arithmetic corner cases, full scenes), algorithm accuracy (72/72 synthetic tags, 0.29 px mean corner error), rejection of non-tags, cycle budget |
| sensor bring-up | `test_i2c.py` | 1 | all 103 OV9281 init writes land in order over I2C, read-back, ID 0x9281, NACK detection |
| system (RTL) | `test_chain.py` | 6 | whole chip at true 120 fps timing: 3 frames back-to-back, **FS-to-FS = 832,800 clocks exactly (120.08 fps), zero dropped frames**, ping-pong banks, bad-CRC / missing-line frames rejected and the next frame delivered, overload frame does not hang, SPI register path |
| pose solver (C) | `test_pose_solver.py` | 11 | float and double builds agree; 0.004 mm / 0.02 deg on noise-free corners over 96 images; noise tolerance; outlier rejection; planar ambiguity |
| MCU firmware | `test_fw_proto.py`, `test_fw_storage.py`, `test_fw_app.py` | 101 | COBS/CRC framing incl. fuzz, flash storage with **power loss simulated at every byte of a commit**, command handling, torn FPGA reads, auto-exposure convergence |
| host + end to end | `test_host_e2e.py`, `test_host_fuzz.py` | 32 | host library against the real firmware code with the FPGA result words from the RTL runs; garbage/split/dropped bytes |
| board data | `test_pcb.py` | 13 | every net has >= 2 pins, every FPGA power ball on the right rail, pin plan legality (banks, LVDS pairs, edge-clock pad, left/right IDDR rule), regulator divider voltages, mechanical contract |
| housing | `test_housing.py` | 9 | watertight STLs, USB-C opening, screw posts vs PCB holes, 90 deg FOV cone clearance |

## Whole-pipeline accuracy (100 images, RTL simulation of the chip -> firmware solver -> compared with ground truth)

Chip (CSI-2 stream at 120 fps timing, simulated RTL) -> tag estimates over SPI -> C pose solver. Versus the reference
detector (pupil-apriltags + OpenCV `solvePnP`) on the *same* images (`tests/analyze_chain.py`,
`results/rtl_chain_results.json`, `results/reference_baseline.md`):

| | this chip | reference |
|---|---|---|
| tags detected (all 100 images) | 514 / 563 (91 %) | 541 / 563 (96 %) |
| tags detected (excluding the 4 deliberately dark images) | 496 / 533 (93 %) | - |
| spurious IDs (not in the map, ignored by the MCU) | 7 | 1 |
| ghost detections of map tags that are not visible | 0 | - |
| corner error, mean (px) | 0.5-0.7 | 0.23 |
| camera position error, median (mm) | 0.8 (bright) - 1.9 (far) | 0.5-0.9 |
| camera orientation error, median (deg) | 0.02-0.04 | ~0.014 |
| worst camera position error | 60 mm (a single grazing tag, planar ambiguity) | 40 mm |

Per category (pose from the RTL tag estimates): roll 1.1 mm, grad 1.1 mm, bright 0.8 mm, yaw 0.9 mm, dist 1.9 mm,
rand 1.6 mm, dark 1.5 mm; floor 5.7 mm and side 3.8 mm are limited by how few tags those views contain (1-2).

Where it is weaker than the reference, honestly:
* **Distance**: the 8x8-pixel tile threshold and the 10-pixel minimum size lose some tags beyond ~3.5 m (tag < 20 px).
* **Low light**: the four `dark_*` images (5-12 % of nominal light) detect 60 %. The sensor's exposure/gain is meant to be
  closed by the MCU's auto-exposure loop (`FRAME_SUM` register; tested against a simulated sensor), which the static
  dataset cannot exercise.
* **Clutter**: binary processing is exposed to textured, dim backgrounds. Since the labeller rework (`rtl/run_ccl.v`: 256 runs
  per row, ~3 clocks per run, label recycling, the 64 largest candidates by area) a busy frame is never abandoned: on the 500-frame
  set the RTL chain finds **2651 of 2825 detectable tags (93.8 %) with 0 false positives**, equal to the golden-mask + TPU-ISS model
  prediction (2651); before the rework it found 2158 (76.4 %, same harness). Per category (found/visible): clutter 187/194,
  dark 182/182, glare 90/115, occl 124/158, rand 456/479, roll 302/304, dist 284/305, yaw 242/270. The original 100 images are
  unchanged (98 identical tag sets, corners identical to the last bit; `dark_a`/`dark_c` go from 0 to all 8 tags).
  The CCL status flags are diagnostics of a *degraded* frame: 63 of 500 frames set one in the 100 MHz chain run (59 only 'more than 64 candidates, the largest 64 kept', 4 with a dropped row);
  7 frames lose 1-5 rows because the labeller cannot keep up with a very busy row at the real 686-clock line (the model and the RTL
  agree on the other 493 frames), see `results/ccl_sweep_686.json`.
* **Corner accuracy** is 2-3x worse than the reference (binary sampling), but pose error is nearly as good because the
  solver uses every corner of every tag.

## Timing and resources (measured)

120 fps: FS-to-FS period 832,800 clocks @ 100 MHz = **8.328 ms = 120.08 fps**, no dropped frames in multi-frame runs.
Per frame (500-frame set, `tests/sweep_ccl_rtl.py 686` = real 686-clock line): slowest CCL row <= 686 clocks in 485 of 500 frames
(median 69, worst 1559 clocks; the busiest frame has 113,759 runs and its slowest row takes 590 clocks); `done` comes 185 clocks
(median) to 2738 clocks (worst) after the last row. TPU time (`results/tpu_budget_by_category.md`): 420k clocks median,
1.57 M at the 90th percentile, 2.53 M worst. One frame period is 713,840 clocks at 85.714 MHz, so 102 of the 500 frames (20 %; by
category: clutter 12 of 25, grad 9 of 24, dark 10 of 24, rand 14 of 100, roll 10 of 43, empty noise-only 4 of 12) would make the *next*
frame be dropped when streamed back-to-back; on the original 100 images 3 do (`dark_a` 768k, `grad_d` 959k, `dark_c` 2.37 M; the median is 349k; the earlier
figure of 523k worst on these 100 images predates the labeller rework, when overflowing frames lost their candidates). Clean frames keep the 120.08 fps
path with no drops (`test_chain.py::test_three_frames_back_to_back_at_120fps`).

FPGA (yosys + nextpnr-ecp5, LFE5U-85F-8BG381C): see `docs/fpga.md`.
