# FPGA speed grade study (architecture A3, LFE5U-45F / 25F, CABGA381)

Why: LFE5U-45F-8BG381C (speed grade 8) was out of stock at every distributor on 2026-10-31. The -6 grade of the same package is in stock.
The UM (SERDES) variant is not a drop-in (SERDES rails are tied to GND on our PCB).

Flow: `bash tools/fpga_sweep.sh "1 2 3 4 5 6" <speed> <45k|25k>` (calls `tools/fpga_flow.sh`; yosys `synth_ecp5 -noabc9`, nextpnr-ecp5 `--speed <N>`, target core clock
85.714 MHz, D-PHY `sclk` 200 MHz). All numbers: **nextpnr estimates, not signoff**. Final post-route report per clock (nextpnr also prints a lower post-placement estimate first).

Tool versions (this table): OSS CAD Suite 2025-09-01 (the version pinned by `.github/workflows/release.yml`): Yosys 0.56+197 (d4c4b2106), nextpnr-ecp5 0.8-115-gbc086c01,
run on Ubuntu 22.04 (WSL2). RTL = main at 33e0207 (no RTL change in this study). Resource use is the same for every speed grade: 12954 LUT4, 56 DP16KD.

## LFE5U-45F (43848 LUT4, 108 DP16KD: 29 % / 51 %)

| speed | seeds closing both clocks | core clk100 fmax range (need 85.714) | D-PHY sclk fmax range (need 200) |
|---|---|---|---|
| 8 | 6 of 6 | 86.27 - 92.58 MHz | 205.93 - 229.20 MHz |
| 7 | 0 of 6 | 72.41 - 78.16 MHz | 180.96 - 191.46 MHz |
| 6 | 0 of 6 | 62.12 - 69.70 MHz | 154.94 - 172.29 MHz |

Per seed, speed 8: 1: 89.11/229.20, 2: 86.27/211.33, 3: 92.58/224.92, 4: 90.28/213.04, 5: 90.99/223.86, 6: 88.83/205.93 (core/D-PHY, MHz).
Per seed, speed 7: 1: 78.16/188.39, 2: 76.72/188.47, 3: 72.41/191.46, 4: 76.17/180.96, 5: 77.74/185.77, 6: 72.65/191.17.
Per seed, speed 6: 1: 62.12/160.69, 2: 67.62/172.29, 3: 66.53/165.81, 4: 69.70/165.84, 5: 65.98/154.94, 6: 64.73/170.33.

## LFE5U-25F (24288 LUT4, 56 DP16KD: 53 % / 100 %)

| speed | seeds closing both clocks | core clk100 fmax range | D-PHY sclk fmax range |
|---|---|---|---|
| 8 | 5 of 6 (seed 5: D-PHY 193.31, FAIL) | 89.65 - 93.80 MHz | 193.31 - 217.91 MHz |
| 7 | 0 of 6 | 76.38 - 81.89 MHz | 173.67 - 195.12 MHz |
| 6 | 0 of 6 | 66.61 - 72.63 MHz | 146.46 - 179.76 MHz |

The 25F fits only with every block RAM used (56/56). Timing at grade 8 closes; grades 6 and 7 do not. Grade 8 25F is not the part the LCSC listings carry (docs/costdown.md section 4).

## What was tried for the -6 grade

* Earlier run (MSYS2 yosys 0.66 / nextpnr 0.7, 8 seeds, before any change): grade 6 core 64.2 - 67.4 MHz, D-PHY 145.9 - 159.0 MHz; grade 7 core 71.9 - 77.2 MHz, D-PHY 160.8 - 185.4 MHz. Same picture.
* Experiment, not kept: replacing the `w[7:0] * MS_CLKS` multiplier in `rtl/sensor_init.v` (BRAM output -> MULT18X18D -> counter was the worst core path of some seeds) by a millisecond counter raised grade-6 core fmax by only about 3 - 4 MHz (66.9 - 71.2 MHz over 6 seeds, MSYS2 tools); D-PHY 149 - 170 MHz. Reverted, because it does not close.
* The remaining grade-6 core critical paths are the carry chains of `rtl/run_ccl.v` (area / bounding-box accumulation, `wr_data`, `p3k`) and BRAM clock-to-output (5.6 ns at grade 6). Closing 85.714 MHz (11.67 ns) needs a deeper pipelined redesign of the labeller, which changes its per-run cycle count; its worst case per line (8.0 us = 686 core clocks) would have to be re-derived with `tools/frame_budget.py`. Not attempted: it would not help the link (below).

## Why grade 6 / 7 cannot be used even with a faster core

The D-PHY side runs the lanes at 800 Mb/s (clock lane 400 MHz DDR, `CLKDIVF` /2 -> `sclk` 200 MHz). The sclk fabric domain alone reaches only 155 - 172 MHz at grade 6
and 181 - 191 MHz at grade 7, and `docs/costdown.md` section 4 already states that grade 6/7 parts cannot receive 800 Mb/s lanes (the ECP5 IO gearbox limit; datasheet figure not re-checked in this study).
A 650 Mb/s lane rate leaves 7.8 us of an 8.0 us line for 1280 payload bytes on two lanes, with no room for the low-power / SoT gap and packet overhead (arithmetic only; sensor register set for a lower rate not
verified). So the 120 fps budget (1041 lines x 8.0 us = 8.328 ms) cannot be kept at grade 6/7, and the core clock must not be relaxed (`LINE_CYC_DEFAULT=686` clocks per line at 85.714 MHz).
Conclusion: **no speed 6 or 7 build closes; only grade 8 (45F or 25F) does.** Sourcing -8 parts, or another design (lower lane rate and a longer line, i.e. fewer fps), is needed if -8 stays unavailable.
