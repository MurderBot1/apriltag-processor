# FPGA implementation results (Yosys + nextpnr-ecp5, LFE5U-45F / LFE5U-25F, speed grade 8)

**Part on the board (2026-11-01): LFE5U-25F-8BG381I** (the 45F-8BG381C is out of stock; the design closes timing only at speed grade 8). Same CABGA-381 footprint and balls (`tools/pin_compat.py`: 31 used balls identical), so no PCB re-route. nextpnr on the 25F at speed 8 (pinned OSS CAD Suite 2025-09-01, RTL at main 828bf22): 7 of 7 seeds close both clocks, 13,389 LUT4 (55 %), 56 of 56 block RAM (100 %, no margin); seed 1: core 93.81 MHz, D-PHY 211.15 MHz. The 45F and 85F are drop-in fallbacks (85F: 6 of 7 seeds close). The tables below were produced for the 45F with the older tool versions. Sources and stock: `docs/bom/PRODUCTION.md` section 1a.

Architecture A3 (`docs/costdown.md`): the FPGA keeps CSI-2/D-PHY receive, threshold, despeckle, the connected-component labeller
and a streamer; the tag processing unit (TPU) and the two binary frame banks moved into the RP2350 (firmware C code + SRAM). That is
what allows the smaller LFE5U-25F in the same CABGA-381 footprint (the old design needed the 85F: 196 of 208 block RAMs).

Flow: `bash tools/fpga_flow.sh <seed> <freq>` (synth_ecp5 -> nextpnr-ecp5 `--45k --package CABGA381 --speed 8`; speed grade is `FPGA_SPEED=6|7|8`, see "Speed grades" below with `rtl/apriltag_cam.lpf` -> ecppack;
env `FPGA_OUT=dir`, `FPGA_DEVICE=45k|85k|25k` for parallel runs / other devices). A real bitstream is produced (`sim/apriltag_cam.bit`).
Nothing has been loaded onto a physical device. All numbers below are from nextpnr (estimates, not signoff), yosys 0.66, nextpnr 0.7.

## Resource use on the 45F (older RTL, seed 1, MSYS2 tools; the 25F shipping numbers are in the first paragraph)

| resource | used | of (45F) | % | old design on the 85F |
|---|---|---|---|---|
| LUT4 (total, incl. carry/RAM) | 12,227 | 43,848 | 27 | 23,346 |
| flip-flops | 5,435 | 43,848 | 12 | 7,299 |
| block RAM (DP16KD) | 56 | 108 | **52** | 196 of 208 (94 %) |
| MULT18X18D | 3 | 72 | 4 | 8 |
| PLL | 1 | 4 | 25 | 1 |
| IO | 28 | 245 | 11 | 18 |

Block RAM now: threshold 17-row ring 27, labeller ~26 (label tables, run RAM), candidate RAM 2 (1024 x 32, the streamer reads it back), sensor init 1.
The streamer itself (`rtl/mask_stream.v`) is a 16-word FIFO in LUT RAM plus the byte transmitter: a few hundred LUTs. Logic and block RAM have large
headroom on the 45F (about 2x the block RAM needed). The shipping ECP5-25F has 56 block RAMs: the design needs all 56 (100 %), so no margin, and 13,389 LUT4 (55 %) with the THRESH ratio field; see the top of this file and `results/fpga_speed_grades.md`.

## Timing on the 45F (older RTL and tools, post place-and-route, target 85.714 MHz core clock, 200 MHz D-PHY `sclk`)

| seed | core clock fmax | D-PHY `sclk` fmax | both pass |
|---|---|---|---|
| 1 | 90.99 MHz | 206.02 MHz | yes |
| 2 | 85.48 MHz (misses by 0.2) | 216.64 MHz | no |
| 3 | 87.50 MHz | 217.49 MHz | yes |
| 4 | 87.47 MHz | 211.86 MHz | yes |
| 5 | 81.73 MHz (misses by 4.0) | 204.88 MHz | no |
| 6 | 87.91 MHz | 201.53 MHz | yes |

Core clock: 4 of 6 seeds close 85.714 MHz (old 85F design: 1 of 5). D-PHY clock: 6 of 6 close 200 MHz. Seeds 1, 3, 4 and 6 close both; the default is seed 1 (90.99 / 206.02 MHz). Re-check after any RTL or pin change (the numbers moved between the first pin plan in bank 2 and the final one in bank 6).
Reproduce: `FPGA_OUT=sim/fpga_s<N> bash tools/fpga_flow.sh <N> 85.714`; summary in `results/fpga_45f_seeds.md`.

**Decision unchanged: the core runs at 85.714 MHz** (`rtl/sys_pll.v`, `LINE_CYC_DEFAULT=686` clocks per 8 us sensor line). The 120 fps requirement is a property of
the sensor rate (frame 1041 lines = 8.328 ms). Removing the TPU (whose multiplier/divider operand routing was a critical path of some seeds) is the likely
reason the core clock now closes on most seeds; that causal link was not isolated.

## Speed grades and tool versions

`FPGA_SPEED=6|7|8` (default 8) and `FPGA_DEVICE=45k|25k` select the part; `tools/fpga_sweep.sh "<seeds>" <speed> <device>` runs several seeds in parallel and prints the table.
Full study with per-seed numbers: `results/fpga_speed_grades.md`. Result (nextpnr estimate, not signoff, OSS CAD Suite 2025-09-01 as pinned in `release.yml`, 6 seeds):
LFE5U-45F speed 8: 6 of 6 seeds close both clocks; speed 7: 0 of 6 (core 72 - 78 MHz, D-PHY 181 - 191 MHz); speed 6: 0 of 6 (core 62 - 70 MHz, D-PHY 155 - 172 MHz).
LFE5U-25F speed 8: 5 of 6 close on the RTL of 33e0207 (56/56 block RAM), 7 of 7 on main 828bf22 (see top of this file); speeds 7 and 6: 0 of 6. A -6 or -7 FPGA therefore cannot be used with this design: the labeller carry chains limit the core clock, and the 800 Mb/s lanes need a faster
grade anyway (`docs/costdown.md` section 4).

The release workflow measures with the same pinned tools (`.github/workflows/fpga-timing.yml` also runs the sweep on PRs that touch `rtl/`). nextpnr prints a post-placement estimate before routing, which is
lower than the final number (seed 1: 78.09 MHz vs 89.11 MHz core); `tools/build_all.sh` previously read both and reported "timing NOT met" for a seed that closes. It now uses the final report only, tries `FPGA_SEEDS`
(default `1 3 5 4 7`) and keeps the first seed that closes both clocks.
Tool versions differ in the absolute numbers (MSYS2 yosys 0.66 / nextpnr 0.7 gave seed 1 core 90.99 / D-PHY 206.02 MHz; pinned Yosys 0.56 / nextpnr 0.8: 89.11 / 229.20 MHz), so quote the version with every number.

## MCU frame bus (FPGA -> RP2350)

The mask is streamed at the pixel rate instead of being stored: one byte per 4 core clocks = 21.4 MB/s while a row is flowing, 15.4 MB/s average.
Pins (bank 6, 3.3 V, the outer ball row on the MCU side, LVCMOS33 DRIVE=8 SLEWRATE=FAST, balls checked identical on the 85F / 45F / 25F by `tools/pin_compat.py`):
`mcu_d[7:0]` = P1 N1 M1 L1 K1 P2 N2 L2 -> RP2350 GPIO16..23, `mcu_clk` = K2 -> GPIO24, `mcu_fs` = M3 -> GPIO25.

| signal | meaning |
|---|---|
| `mcu_d[7:0]` | byte, changes 1 core clock before `mcu_clk` rises, stable for 3 clocks after |
| `mcu_clk` | strobe, high 2 of the 4 clocks of a byte slot; stops (while `mcu_fs` stays high) if the next word is late |
| `mcu_fs` | high from before the first byte of a packet to after the last |

One packet per accepted frame, 132,128 bytes, little-endian words: 4-word header (`0x4D335441` "AT3M", sequence number, 64-bit device time of the frame
start), 32,000 mask words (800 rows x 40 words, bit x%32 of word y*40+x/32 = pixel (x,y), 1 = black, after threshold and despeckle), a 4-word trailer
(candidate count, labeller flags, status bits, frame sum for auto exposure, max row clocks, check word `~seq`) and the 64 x 16-word candidate records of
`run_ccl`. A frame with a sensor CRC/line-count error still leaves as a complete packet with the `CSI bad` status bit (the FPGA has no store to
retract it; a frame with missing lines is zero padded); the MCU discards flagged packets. Format: `rtl/mask_stream.v`, `firmware/core/atframe.h`.

RP2350 side (`firmware/rp2350/frame_rx.pio`, `hal_frame_rx.c`): a PIO state machine samples D on the rising edge of the strobe (3 PIO cycles per byte,
7 available at 150 MHz), autopush every 4 bytes, a DMA channel moves each packet (33,032 words) into one of three 132 KB frame buffers in SRAM (`AT_NBUF`); the channel
is re-armed from its completion interrupt (to a dummy word when all buffers are busy, so the stream never loses alignment) and switched to a buffer that became free in the gap when `mcu_fs` rises (`late_claim`); a packet that ends early is
detected 100 us after `mcu_fs` falls and repaired by restarting the state machine. Firmware RAM use: 348 KB bss of 520 KB with two buffers (linked locally); with three buffers about 480 - 488 KB of the 512 KiB main SRAM (computed, see `results/frame_budget.md`, not linked).

**Not verified on hardware:** the input timing margin (the PIO input synchroniser adds about 13 ns; the data window around the strobe edge is 11.7 ns
before / 35 ns after), DMA/CPU SRAM arbitration at 21 MB/s while the tag unit runs, the PIO program itself (no PIO simulator was available; it compiles
with the Pico SDK's `pioasm`). Testbenches: `tb/tb_mstream.v` (byte timing, stability around the strobe, FIFO, late labeller, short frame, abort),
`tb/tb_cam.v` (whole chip).

## Caveats

* Timing is nextpnr's estimate, not signoff; real-device margins are unknown. Seed variation (81.7 - 91.0 MHz core, 201.5 - 217.5 MHz D-PHY over six seeds)
  means the bitstream must be rebuilt with a passing seed after any RTL change.
* Frame drops now happen in the MCU (no free frame buffer), see `docs/verification.md` and `results/frame_budget.md`.
* The RP2350 firmware could not be linked through the SDK's own CMake flow with the msys2 `ld` 2.47 used on the development PC; the Linux release workflow (apt `gcc-arm-none-eabi`, older binutils) was not run here
  ("pico_flash_region.ld appears multiple times", a toolchain/SDK incompatibility unrelated to this code); locally the image was linked with the linker
  script's include inlined (compile of all sources with SDK 2.1.1 and 2.2.0: no warnings).
