# Cost-down study (2026-10-30)

Question: can the unit be made cheaper (any part may be redesigned, e.g. a CPU doing the detection) while keeping **everything on the
unit**, the **OV9281 at 1280x800 @ 120 fps**, the same output (tags + poses over USB) and dataset accuracy (100-image set; reference
detector 630/647 detectable tags, current chip 562/647)?

This is research only. `docs/bom/bom.json` and the design are unchanged. Every number below comes from a script in `tools/` and a file in
`results/` (list at the end) or from a vendor page named next to it. Anything I could not read from a vendor is marked **UNVERIFIED**.

## 1. Answer in one page

1. **A CPU alone cannot do the detection at 1280x800@120.** Measured on this PC (Ryzen 9 7900X, one thread, upstream AprilTag C library,
   `gcc -O3 -march=native`) the full-resolution detector needs 50 ms/frame with a noise-blur trick (632/647 tags) and 83 ms without
   (626/647). 120 fps allows 8.33 ms per frame, so that is **6 to 10 desktop cores of work**. The best cheap SoC listed here has the
   capacity of about 1.1 (RK3576) to 1.6 (RK3588, $66) such cores. Decimating the image by 2 (22 ms, 613/647) still needs 2.7 cores and
   loses 13 tags. No sub-$30 SoC reaches 120 fps full frame in software. Section 3 has the table.
2. **A CPU behind a small FPGA front end is the only CPU route that gets close**, and it is not cheaper: after the FPGA's threshold and
   despeckle the back end costs 8 ms mean (19 ms p95, 59 ms max) on the PC, i.e. one desktop core on average and 2.3 at p95. That needs
   an RK3576/RK3588-class chip (+ LPDDR4 + PMIC) and still drops heavy frames. It also gets only 556/647 tags (same as the chip).
3. **The cheap win is inside the FPGA part, not a CPU:** the design needs 196 of 208 block RAMs only because the two 1 Mbit binary frame
   banks (126 blocks) and the TPU (10k LUT4, 8 blocks) live in the FPGA. If the **TPU and the frame banks move into the RP2350 firmware
   and SRAM** (520 KB holds two 128 KB binary frames), the FPGA keeps capture + threshold + despeckle + labeller: 58 block RAMs and about
   10k LUT4. That fits an **ECP5-45F in the same CABGA-381 footprint** (pin compatibility checked against the Project Trellis database
   for all 18 used balls) at **$35.28** (LCSC, LFE5UM-45F-8BG381C) instead of **$100.13**.
4. **Lens:** the Arducam 2.1 mm lens is $10.09 at RobotShop (read 2026-10-30) against $39.00, but it gives about 85 deg rectilinear HFOV
   on the 3.84 mm sensor width instead of 94 deg (the 90 deg requirement is not met by that arithmetic; real distortion data is missing).
5. **Sourcing:** LCSC's price for the existing ECP5-85F moved from about $35 (a search-index snapshot of the same page, UNVERIFIED) to
   $100.13 (API read today), stock 8. If the part can be bought near $35 elsewhere the existing design is already about $92 with no
   engineering. That is a purchasing check, not something I could verify (Mouser/DigiKey block automated reads).

Recurring BOM per board (without the OV9281 which has no public price, without PCB fabrication and SMT placement which are
unverified in `bom.json`; passives keep the `bom.json` 1+ price at every quantity):

| architecture | 1 board | 10 boards | 100 boards |
|---|---|---|---|
| A0 baseline: ECP5-85F-8 ($100.13 / 96.85 at 10+), Commonlands lens | $157.53 | $153.76 | $153.20 |
| A1 = A0 with Arducam 2.1 mm lens ($10.09) | $128.62 | $124.85 | $124.29 |
| A3 FPGA = ECP5 UM-45F-8BG381C ($35.28 / 34.12), TPU+frame store in RP2350 | $92.68 | $91.04 | $90.48 |
| A3 + A1 (cheap lens too) | $63.77 | $62.13 | $61.57 |
| A3b FPGA = LFE5U-25F-6BG256C ($15.37 / 13.55 / 11.51), needs slower MIPI rate | $72.77 | $70.46 | $67.87 |
| A3c FPGA = LFE5U-25F-7BG256C ($12.05; stock 0), needs slower MIPI rate | $69.45 | $68.96 | $68.40 |

Notes: the 10- and 100-board columns use the LCSC tier at 1x the board count for the ladders that were read (a tier is the largest break not
above the quantity); the UM-45F ladder stops at 10, so 100 uses the 10+ price. LCSC **stock** limits these: 85F has 8 pieces, UM-45F 6,
25F-6 has 153, 25F-7 has 0. One-time fees (setup 51.12 + stencil 16.42 + feeder 1.53 x 37 lines) are $124.15 per order: $124.15 /
$12.42 / $1.24 per board at 1 / 10 / 100. Reproduce: `py -3.12 tools/costdown_model.py`.

Ranked shortlist (details in section 6):

1. **Check the real price/stock of the ECP5-85F-8BG381C at other distributors** (0 engineering, up to -$65). UNVERIFIED.
2. **Lens swap** (-$29 per unit) after measuring FOV/distortion of the candidate on a real OV9281 (no engineering in RTL; housing bore/holder
   height must be re-checked).
3. **A3: move TPU + frame banks to the RP2350, FPGA -> ECP5 UM-45F** (-$65 per unit, same footprint, RTL and firmware work).
4. A3b/A3c (25F) only after the sensor can be run below about 650 Mb/s per lane (section 4) and the labeller is cut to NLAB=512.
5. Not recommended: a CPU/SoC-based detector (section 3).

## 2. The workload (measured)

Frames: the 100 images of `test_images/sensor` (1280x800, 8 bit; synthetic with sensor noise, so noisy frames are the expensive ones).
Detector: AprilRobotics/apriltag at commit b7c0ebe (cloned via `gh`), tag36h11, `refine_edges=1`, `decode_sharpening=0.25`,
**one thread**. `tools/costdown_c/bench.c` + `build.sh` build it, `tools/costdown_score.py` runs the settings and scores
ids. Accuracy = detectable GT ids found with hamming 0 (same rule as `tests/ci_category.py`, id level, no pose). PC: Ryzen 9 7900X.
Run-to-run noise is about +-5 %.

| input / setting | mean ms | p95 | max | tags found /647 | frames ok /100 |
|---|---|---|---|---|---|
| gray, full res, no blur | 83.2 | 104.9 | 109.7 | 626 | 84 |
| gray, full res, `quad_sigma` 0.6 | 65.0 | 86.8 | 103.8 | 633 | 87 |
| **gray, full res, `quad_sigma` 0.8** | **49.9** | 65.3 | 70.8 | **632** | 87 |
| gray, full res, `quad_sigma` 1.0 | 42.1 | 57.7 | 67.4 | 628 | 86 |
| gray, decimate 1.5 | 35.8 | 41.8 | 46.5 | 618 | 81 |
| gray, decimate 2 | 22.4 | 25.9 | 28.2 | 613 | 78 |
| gray, decimate 2 + sigma 0.8 | 15.6 | 23.4 | 74.6 | 593 | 71 |
| gray, 2 threads / 4 threads (no blur) | 44.0 / 26.0 | 52.4 / 31.4 | 57.6 / 123.4 | 626 | 84 |
| **after the FPGA front end** (tile threshold + 3x3 despeckle, `tools/golden.py`), full res | **8.0** | 19.0 | 59.1 | 556 | 71 |
| after front end, decimate 2 | 3.1 | 11.0 | 26.4 | 553 | 71 |

Stage profile of the 83 ms case (library's own timers, mean ms): threshold 1.3, union-find 10.1, make clusters 17.8, **fit quads 45.9**,
quads 1.7, decode 2.7. The cost is the noise clusters, not the threshold. After the front end the same stages are 1.2 / 2.2 / 2.4 / 1.5 / 0.2 / 0.4.

Other facts from the measurements:

* The "5 false ids" per setting are decodes of map tags the ground truth marks not visible (frames blur_007, dark_001, lowcon_003, noise_006,
  normal_003); I did not investigate why the reference pipeline (undistort first) reports none. Detecting on the raw image skips the
  2080x1600 padded undistortion that `tools/reference_pipeline.py` does (that path costs 218 ms with the pupil-apriltags wheel; the on-unit
  design undistorts corners, not images, `tools/costdown_bench.py`). The pupil-apriltags wheel on raw 1280x800 is 111 ms, slower than the
  native build above, so the native `-O3 -march=native` build is the fair number.
* The front-end result (556/647) matches the repo's chip number (562/647), which is a useful cross-check: the RTL front end, not the quad
  fitter, is what separates the chip from the 630 reference.
* `docs/verification.md` states TPU time of **427k clocks median, 2.55 M worst** at 85.714 MHz (frame period 713,840 clocks). So the
  *current* chip already drops the next frame on 20 of the 100 frames if the stream looked like them (the 0.2 ms in `docs/architecture.md`
  is stale against that table). "Sustains 120.08 fps" is true of the sensor link and of clean frames, not of every dataset frame.
* ROI tracking (search only near last positions) and tag-size priors would cut cost by an order of magnitude but are **not full frame**
  and were not measured. Listed only.

## 3. Software detection on a CPU/SoC

Scaling method: 7-zip single-thread MIPS (`results/costdown_sbc_bench_Results.md`, ThomasKaiser/sbc-bench, read 2026-10-30) relative to
this PC's `7z b -mmt1` total (9469 on the first run, 9700 on a later run; `results/costdown_7zip_pc.txt`; I use the lower). Needed
capacity = PC ms / 8.33 ms per frame, with one whole frame per core (frame pipelining) and 85 % parallel efficiency assumed.
Uncertainty: 7-zip is only a proxy; the detector is memory- and branch-heavy (union-find, hash of cluster edges), so small cores with
LPDDR4 are more likely slower than this scaling than faster. Treat the table as optimistic by 0 to 40 %. Prices are LCSC 1+ API reads
2026-10-30 (`results/costdown_prices.json`); they exclude DDR, PMIC and storage.

| CPU | LCSC 1+ | capacity (PC-core equiv.) | gray sigma 0.8 needs mean/p95/max | gray decimate 2 | after FPGA front end |
|---|---|---|---|---|---|
| RV1106G3 (1x A7 1.2 GHz; A7 MIPS **estimated**) | $25.39 | 0.07 | 6.0 / 7.8 / 8.5 | 2.7 / 3.1 / 3.4 | 1.0 / 2.3 / 7.1 |
| T113-S3 (2x A7; 128 MB DDR in package per LCSC/CNX) | $21.44 | 0.14 | same | same | same |
| i.MX 8M Mini (4x A53 1.8 GHz) | $23.49 | 0.48 | same | same | same |
| RK3566 (4x A55) | $14.65 | 0.52 | same | same | same |
| V853 (1x A7 + 1 TOPS NPU) | $5.94 | 0.06 | same | same | same |
| RK3576 (4x A72 + 4x A53) | $22.82 | 1.14 | same | same | 1.0 ok / 2.3 / 7.1 |
| RK3588 (4x A76 + 4x A55) | $65.95 | 1.63 | same | same | 1.0 ok / 2.3 / 7.1 |

(All "needs" columns are the same for every CPU; only the capacity differs. `py -3.12 tools/costdown_scale.py` prints the full table with
the over-capacity marks, `results/costdown_scaling.md`.) Reading it:

* Gray full-frame (632/647 tags): needs 6.0 desktop cores on average and 8.5 at the worst frame. Nothing here is within 3x of that.
* Decimate 2 (613/647, -19 tags): needs 2.7 to 3.4. Only RK3588 (1.6) comes closer, still short, and it loses accuracy.
* With the FPGA front end (556/647): the mean need (1.0) fits RK3576/RK3588, p95 (2.3) and max (7.1) do not, so heavy frames are dropped
  (the chip's TPU drops similar frames today). That is a $23-66 SoC + LPDDR4 + PMIC + flash **on top of** a (smaller) FPGA, which
  is not cheaper than section 4's option.
* i.MX RT1170/RT1180 (LCSC MIMXRT1176AVM8A $21.70, stock 3): the Cortex-M7 at 1 GHz has no MIPS number in the sources I read, so I did not model it; I expect it to be
  well below the A53 class for this workload (UNVERIFIED expectation, not measured). STM32N6 (M55 800 MHz,
  NeoISP, CSI-2): price not found on LCSC; same conclusion. RK3588/RK3568 NPUs and ISPs, RGA blocks, Sophgo SG2002, Ambarella: no
  standard block does tile-adaptive thresholding + labelling + quad fitting; an NPU corner detector would be a different algorithm with
  unmeasured accuracy. Not evaluated.
* Hardware you would need beyond the chip: RK3566 is BGA-565 (15.5 x 14.4 mm) with LPDDR4, PMIC and eMMC/NOR, i.e. a 6-layer-class board
  in a 48x48 mm box with a USB device stack on Linux. RV1106G3 is QFN-128 with DDR inside (per the Waveshare/Spotpear listings found, not
  checked on a datasheet). These overheads were **not priced** (no verified quotes) and probably erase most of a $15-25 SoC's advantage
  over the $35 FPGA of section 4.

**Conclusion for item 1:** full-frame 120 fps software detection on a cheap CPU is not achievable. The numbers: 6.0 to 10 desktop-core
equivalents needed, 0.07 to 1.6 available.

## 4. Smaller FPGA, and an FPGA + MCU split

### Why the existing design needs the 85F (yosys, `synth_ecp5 -noflatten`, `sim/stat_nf.txt`)

| module | DP16KD (18 kbit) | LUT4 |
|---|---|---|
| cam_core (frame banks fb0/fb1 126, candidate banks 4, result banks 2, regs) | 134 | 2,576 |
| thresh_binarize (17-row ring) | 27 | 715 |
| run_ccl (labeller) | 26 | 4,110 |
| tpu_core (incl. 587x4 tag ROM) | 8 | 10,009 |
| sensor_init | 1 | 126 |
| csi2_rx, despeckle, dphy, spi, i2c | 0 | ~1,900 |
| **total** | **196 of 208** | **~19.9k (23.3k with carry/RAM)** |

Fitting the unchanged design on a 45F (108 blocks): nextpnr-ecp5 `--45k --package CABGA381 --speed 8` reports
`DP16KD: 196/108 181 %` and fails ("no BELs remaining"). ECP5-25F has 56 blocks. So the frame banks (126) must leave the FPGA. Block RAM
alone rules out Artix-7 35T (50 BRAM36 = 100 BRAM18; LCSC $152.87 at 1+, stock 166), Gowin GW2A-18 ($40.50, stock 68, 828 kbit by my
recollection of the datasheet, UNVERIFIED) and every other low-cost part I priced.

### Option A3: split the work at the binary frame

FPGA keeps D-PHY RX, CSI-2, threshold, despeckle and `run_ccl` (candidate list). It streams the despeckled mask (bit-packed 128 KB per frame,
15.4 MB/s at 120 fps, e.g. 8-bit parallel + clock into PIO + DMA, or QSPI) into RP2350 SRAM (two ping-pong frames = 256 KB of 520 KB) together with
the candidate table. The **TPU algorithm (`tools/tpu_prog.py`, 574 words, ISS `tools/tpu_isa.py` is the golden model) is ported to C on the RP2350**
(two Cortex-M33 at up to 150 MHz).

* FPGA after the change (estimate from the per-module table; the RTL was **not** modified or re-synthesised): about 27 + 26 + 4 + 1 = 58
  block RAMs, ~10k LUT4. Fits ECP5-45F (108) comfortably; on 25F (56) it needs `NLAB` 1024 -> 512 (the repo estimates -7 blocks).
* **Footprint compatibility** (prjtrellis `iodb.json`, `LFE5U-85F` vs `LFE5U-45F`/`LFE5UM-45F`/`LFE5U-25F`, CABGA381): all 18 balls used by
  `tools/pins.py` have the same bank and pad function. So A3 with the 45F is a drop-in for the FPGA footprint; only the new FPGA-to-RP2350 bus
  needs routing. (Ball compatibility from the open database, not from a Lattice drawing.)
* FPGA price: LFE5UM-45F-8BG381C (the SerDes variant, SerDes unused) $35.28 at 1+, $34.12 at 10+, LCSC C1550814, stock **6**. The plain
  LFE5U-45F-8BG381C had no LCSC page in my search (a $43.23 Octopart figure from a search snippet is UNVERIFIED).
* **TPU in C, the key risk.** The TPU takes 427k clocks median / 2.55 M worst at 85.714 MHz = 5.0 ms / 29.8 ms. Its instructions take 2 clocks
  each, divides about 48. A C port on a Cortex-M33 at 150 MHz costs k M33 cycles per TPU clock. I **cannot measure k here**; a plausible
  range is 0.7 to 2.0 (RISC-like ops, 64-bit divide in software, bit-packed pixel fetch). That gives 2.0 to 5.7 ms median per frame on **one** core
  and 12 to 34 ms worst, i.e. the same order as the TPU today, and roughly half that when the two cores take alternate frames. This is
  an estimate, not a result.
* Firmware also keeps the pose solver, USB and calibration. 130 KB frame buffers + pose code fit 520 KB; not checked against the linker map.
* Not full-frame-lossy: the algorithm and the FPGA front end are unchanged, so tag accuracy equals the current chip if the C port is bit-exact
  to the ISS (the repo already has a bit-exact ISS to port against).

### Option A3b/A3c: ECP5-25F (cheapest) and the D-PHY speed-grade problem

I synthesised a **front-end-only** design (`tools/costdown_exp/fe_top.v`: dphy_rx + csi2_rx + thresh_binarize + despeckle; 2,469 LUT4,
27 block RAM) and ran nextpnr at the real 85.714 MHz core clock with the sensor clock lane constrained to 400 MHz
(`tools/costdown_exp/fe_flow.sh`, LPF on the same pad functions: PCLKT7_0, PCLKT7_1, GR_PCLK7_1):

| device / speed | D-PHY `sclk` fmax (needs 200 MHz) | core clk fmax (needs 85.7 MHz) |
|---|---|---|
| 25F, speed 8 | 213.3 MHz pass | 103.2 MHz pass |
| 25F, speed 7 | 184.1 MHz **fail** | 90.2 MHz pass |
| 25F, speed 6 | 164.2 MHz **fail** | 79.1 MHz **fail** |

(nextpnr estimates, one seed, no signoff; the full design in `docs/fpga.md` is within 1 MHz of failing at speed 8 already.) The cheap parts on
LCSC are speed 6 ($15.37, stock 153) and speed 7 ($12.05, stock 0; $4.66 at 200+). They cannot receive 800 Mb/s lanes. The sensor link would have to run at
about 650 Mb/s per lane or less (sclk 164 MHz = 656 Mb/s upper bound, no margin; the core clock would also need a faster-than-speed-6 design). Whether the OV9281
can still deliver 1280x800@120 at a lower lane rate with longer line blanking (the 1041-line frame at 8.0 us per line leaves little room) depends on a sensor register
set I have not generated or verified. UNVERIFIED. I found no speed-8 25F price on LCSC (the 25F-8BG256C appears at other sellers; price not read).

### Other FPGAs

Efinix Ti/Trion and Anlogic parts were not priced (no LCSC product found in my searches). Gowin GW2A-18 and Artix-7 35T fail on block RAM
(above). A CPLD cannot hold the threshold ring (17 rows x 640 x 16 bit = 174 kbit) plus a CSI-2 receiver.

## 5. Other savings

* **Lens** (BOM $39.00 Commonlands CIL018-F2.8-M12B650, EFL 1.8 mm, 93.7 deg rectilinear HFOV, 6.8 mm image circle, -14 % distortion):
  Arducam M27210H08 (SKU LN005) EFL 2.1 mm, 1/2.7" format (image circle covers the OV9281's 4.5 mm diagonal), F/2.0, listed at **$10.09**
  (RobotShop RB-Adu-231, backorder, page read via WebFetch 2026-10-30; the $12.62 in the request I could not verify; Arducam's own site returned 403).
  Rectilinear HFOV on the 3.84 mm width: 2 atan(1.92/2.1) = **84.6 deg** vs 93.7 deg for the 1.8 mm lens, 9 % larger tag images, distortion
  not published on the page, and the vendor quotes "73 deg on a 1/4 inch Raspberry Pi camera" (axis unspecified). So it does **not** meet a hard
  90 deg HFOV; whether 85 deg is acceptable is a requirements decision. I did not re-render the dataset with a 2.1 mm lens.
  Saving $28.91 per unit. The CLA020 holder is a separate part ($4.50 already in the BOM; out of stock per `docs/bom/AUDIT.md`).
* **Sensor:** OV9281 has no public price (`docs/bom/AUDIT.md` item 18). I did not find priced alternatives (OG01A1B, SC132GS, AR0144 returned no
  LCSC page); not evaluated.
* **PCB / assembly:** the 4-layer PCB fee and placement cost are unverified in `bom.json` (needs a live JLCPCB quote). The FPGA package in A3
  is unchanged (CABGA-381, 0.8 mm), so fab and BGA assembly cost do not change; a 25F in CABGA-256 and an SoC in a 565-ball BGA are not
  priced for assembly. One-time JLCPCB fees ($124.15 per order) dominate small runs: $124/$12/$1.2 per board at 1/10/100.
* **Power:** current budget ~1.1 W (`docs/hardware.md`). A smaller FPGA lowers it (not quantified); a Linux SoC with LPDDR4 typically adds
  roughly watt-class load (UNVERIFIED, no datasheet read), which matters in the sealed 48x48 mm printed housing with only slots under the FPGA.
* **Size:** A3 changes nothing in the PCB outline. An SoC + DDR + PMIC design would not fit the 48x48 mm board without a re-layout.

## 6. Comparison and recommendation

| | A0 baseline | A1 lens | A3 (45F + firmware TPU) | A3b (25F-6/7) | CPU-only SoC | FPGA front end + SoC |
|---|---|---|---|---|---|---|
| recurring BOM @1 / 10 / 100 (verified parts, no sensor/PCB) | $157.53 / 153.76 / 153.20 | $128.62 / 124.85 / 124.29 | $92.68 / 91.04 / 90.48 ($63.77 / 62.13 / 61.57 with A1) | $72.77 / 70.46 / 67.87 | not priced (DDR, PMIC, storage unquoted) | not priced |
| 1280x800@120 margin | sensor link ok; 20 % of dataset frames exceed TPU time | same | similar to today if k <= ~1.5 (estimate) | link fails at speed 6/7 as designed | **not achievable** (needs 6-10 cores, has 0.07-1.6) | mean ok on RK3576/88, p95/max dropped |
| tags on dataset | 562/647 | same | same if C port bit-exact | same | 626-632 (gray, but too slow) | 556/647 |
| reused | all | all | RTL: threshold, CSI-2, labeller, D-PHY; ISS/golden; firmware: pose, USB | same, + NLAB cut | none | RTL front end |
| rewritten | - | housing check | TPU in C, frame transport RTL + PIO, remove TPU/banks from cam_core, new constraints | + sensor re-timing | everything | everything + Linux |
| size/power | as built | as built | same footprint, less FPGA power | smaller FPGA | needs larger board | needs larger board |
| main risk | stock/price | FOV 85 vs 94 deg, distortion | k factor of the C port; 6 pcs LCSC stock; bus bandwidth/PIO | sensor mode below 650 Mb/s unverified | fails the requirement | cost not below A3 |

**Recommendation:** (1) before anything else, price the ECP5-85F-8BG381C at Mouser/DigiKey/Lattice distributors (the LCSC price spiked from a seen
$35 to $100; with a $35 part the unchanged design is ~$92 and ~$64 with the cheaper lens). (2) Take the lens saving if a real-lens test shows
85 deg HFOV and its distortion are acceptable. (3) If the 85F stays above ~$60, do **A3**: ECP5-45F in the same footprint with the TPU and frame
store in the RP2350. Do not pursue CPU/SoC detection; at 120 fps it needs several times the compute of any cheap chip.
A3 gives -$65 per unit at the LCSC prices read today; with the lens -$94 (-60 %).

**De-risking experiments (cheap, in this order):**
1. Port `tools/tpu_prog.py` to C (use `tools/tpu_isa.py` outputs as golden vectors) and run the 100 frames' candidates on a Pico 2 / RP2350 dev
   board with the binary frames in SRAM. Measure cycles per frame per category. Pass criterion: median <= 6 ms and worst <= 12 ms on one core,
   or the two-core split meets 8.33 ms for the categories that fit the TPU today (`results/tpu_budget_by_category.md`).
2. Synthesise the reduced RTL (no TPU, no fb0/fb1, add a mask-stream output) with `--45k --package CABGA381 --speed 8` and with `--25k`
   to confirm the 58 / 51 block RAM estimate and the 85.7 MHz closure over several seeds.
3. PIO capture of a 15.4 MB/s 8-bit bus at 120 fps into RP2350 SRAM with DMA, with USB and pose running.
4. For the lens: shoot a checkerboard with the Arducam lens on the real sensor, fit the distortion, and measure HFOV and corner MTF.
5. For the 25F: write the OV9281 register set for a <= 650 Mb/s lane rate and verify 120 fps, then run `fe_flow.sh` on seeds 1-5.

## 7. Unverified claims (explicit list)

* Earlier LCSC price of about $35.12 / stock 1 for the 85F (search-engine snippet; API now says $100.13, stock 8). Mouser $33.41/0 stock and DigiKey
  ~$80 are the `AUDIT.md` figures, not re-read.
* RobotShop's Arducam 2.1 mm $10.09 and the lens FOV numbers (page summarised by WebFetch; Arducam's page 403). The request's $12.62 not checked.
* All A7 per-core MIPS (RV1106, T113, V853) are estimates from a SigmaStar SSD202D result at 1.7 GHz scaled linearly; A53/A55 at other clocks scaled linearly.
* The C-port factor k, the RP2350 SRAM budget, the FPGA resource figures after removing the TPU (estimates from per-module yosys counts; no
  modified RTL synthesised), the 15.4 MB/s link feasibility on PIO.
* nextpnr frequencies (one seed, estimate, not signoff). Speed grade 8 25F price/availability. Sensor operation below 800 Mb/s per lane.
* SoC DDR/PMIC/storage prices and power; the i.MX RT1170, STM32N6, Efinix, Anlogic, Sophgo, Ambarella options (not modelled or not priced).
* Gowin GW2A-18 block RAM size (from memory of the datasheet).
* PCB fabrication and SMT placement cost (unverified already in `bom.json`).

## 8. Evidence and how to reproduce

| file | what |
|---|---|
| `tools/costdown_bench.py`, `results/costdown_bench.json` | pupil-apriltags wheel timing/accuracy (raw vs padded, decimation) |
| `tools/costdown_c/bench.c`, `build.sh` | native AprilTag C build + stage profile (needs an AprilRobotics/apriltag checkout) |
| `tools/costdown_score.py`, `results/costdown_native.json`, `results/costdown_native_bin.json` | settings sweep with id-level scoring (gray and post-front-end frames) |
| `tools/costdown_binpgm.py` | writes the frames after `tools/golden.py` threshold + despeckle |
| `tools/costdown_scale.py`, `results/costdown_scaling.md`, `results/costdown_sbc_bench_Results.md`, `results/costdown_7zip_pc.txt` | MIPS scaling to candidate CPUs |
| `tools/costdown_prices.py`, `results/costdown_prices.json` | LCSC API price/stock reads (2026-10-30) |
| `tools/costdown_model.py`, `results/costdown_model.json` | recurring BOM at 1/10/100 |
| `tools/costdown_exp/` | front-end-only RTL top, LPF and nextpnr script for 25F/45F speed grades |

Steps used here: build apriltag with `sh tools/costdown_c/build.sh <apriltag checkout> bench.exe -march=native`; convert frames to PGM; `py -3.12
tools/costdown_score.py bench.exe <pgm dir>` (add `bin` for the post-front-end set from `tools/costdown_binpgm.py`); `py -3.12 tools/costdown_prices.py`;
`py -3.12 tools/costdown_model.py`; `py -3.12 tools/costdown_scale.py`; `bash tools/costdown_exp/fe_flow.sh 25k 8`.
