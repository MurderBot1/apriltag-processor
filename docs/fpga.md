# FPGA implementation results (Yosys + nextpnr-ecp5, LFE5U-45F-8BG381C, speed grade 8)

Architecture A3 (`docs/costdown.md`): the FPGA keeps CSI-2/D-PHY receive, threshold, despeckle, the connected-component labeller
and a streamer; the tag processing unit (TPU) and the two binary frame banks moved into the RP2350 (firmware C code + SRAM). That is
what allows the smaller LFE5U-45F in the same CABGA-381 footprint (the old design needed the 85F: 196 of 208 block RAMs).

Flow: `bash tools/fpga_flow.sh <seed> <freq>` (synth_ecp5 -> nextpnr-ecp5 `--45k --package CABGA381 --speed 8` with `rtl/apriltag_cam.lpf` -> ecppack;
env `FPGA_OUT=dir`, `FPGA_DEVICE=45k|85k|25k` for parallel runs / other devices). A real bitstream is produced (`sim/apriltag_cam.bit`).
Nothing has been loaded onto a physical device. All numbers below are from nextpnr (estimates, not signoff), yosys 0.66, nextpnr 0.7.

## Resource use (full chip, seed 1; the other seeds differ by a few LUTs only)

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
headroom (the 45F has about 2x the block RAM needed). An ECP5-25F has 56 block RAMs: the design needs all 56 (100 %), so no margin; see
`results/fpga_45f_seeds.md` for the one-seed nextpnr trial of the 25F.

## Timing (post place-and-route, target 85.714 MHz core clock, 200 MHz D-PHY `sclk`)

| seed | core clock fmax | D-PHY `sclk` fmax | both pass |
|---|---|---|---|
| 1 | 89.57 MHz | 209.86 MHz | yes |
| 2 | 86.24 MHz | 206.14 MHz | yes |
| 3 | 91.40 MHz | 195.69 MHz (misses by 4.3) | no |
| 4 | 89.09 MHz | 193.61 MHz (misses by 6.4) | no |
| 5 | 86.78 MHz | 206.44 MHz | yes |
| 6 | 84.07 MHz (misses by 1.6) | 193.27 MHz (misses by 6.7) | no |

Core clock: 5 of 6 seeds close 85.714 MHz (old 85F design: 1 of 5). D-PHY clock: 3 of 6 close 200 MHz (old design: 5 of 5); the misses are
placement-dependent paths in the lane deskew FIFO (`dphy.f0`). Build the bitstream with seed 1, 2 or 5 and re-check after any RTL change.
Reproduce: `FPGA_OUT=sim/fpga_s<N> bash tools/fpga_flow.sh <N> 85.714`; summary in `results/fpga_45f_seeds.md`.

**Decision unchanged: the core runs at 85.714 MHz** (`rtl/sys_pll.v`, `LINE_CYC_DEFAULT=686` clocks per 8 us sensor line). The 120 fps requirement is a property of
the sensor rate (frame 1041 lines = 8.328 ms). Removing the TPU (whose multiplier/divider operand routing was a critical path of some seeds) is the likely
reason the core clock now closes on most seeds; that causal link was not isolated.

## MCU frame bus (FPGA -> RP2350)

The mask is streamed at the pixel rate instead of being stored: one byte per 4 core clocks = 21.4 MB/s while a row is flowing, 15.4 MB/s average.
Pins (bank 2, 3.3 V, LVCMOS33 DRIVE=8 SLEWRATE=FAST, balls checked identical on the 85F / 45F / 25F by `tools/pin_compat.py`):
`mcu_d[7:0]` = H16 H17 H18 G18 G20 F17 F20 E20 -> RP2350 GPIO16..23, `mcu_clk` = J16 -> GPIO24, `mcu_fs` = J17 -> GPIO25.

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
7 available at 150 MHz), autopush every 4 bytes, a DMA channel moves each packet (33,032 words) into one of two 132 KB frame buffers in SRAM; the channel
is re-armed from its completion interrupt (to a dummy word when both buffers are busy, so the stream never loses alignment); a packet that ends early is
detected 100 us after `mcu_fs` falls and repaired by restarting the state machine. Firmware RAM use (bss, linked locally): 348 KB of 520 KB.

**Not verified on hardware:** the input timing margin (the PIO input synchroniser adds about 13 ns; the data window around the strobe edge is 11.7 ns
before / 35 ns after), DMA/CPU SRAM arbitration at 21 MB/s while the tag unit runs, the PIO program itself (no PIO simulator was available; it compiles
with the Pico SDK's `pioasm`). Testbenches: `tb/tb_mstream.v` (byte timing, stability around the strobe, FIFO, late labeller, short frame, abort),
`tb/tb_cam.v` (whole chip).

## Caveats

* Timing is nextpnr's estimate, not signoff; real-device margins are unknown. Seed variation (84 - 91 MHz core, 193 - 210 MHz D-PHY over six seeds)
  means the bitstream must be rebuilt with a passing seed after any RTL change.
* Frame drops now happen in the MCU (no free frame buffer), see `docs/verification.md` and `results/frame_budget.md`.
* The RP2350 firmware could not be linked through the SDK's own CMake flow with the msys2 `ld` 2.47 used on the development PC; the Linux release workflow (apt `gcc-arm-none-eabi`, older binutils) was not run here
  ("pico_flash_region.ld appears multiple times", a toolchain/SDK incompatibility unrelated to this code); locally the image was linked with the linker
  script's include inlined (compile of all sources with SDK 2.1.1 and 2.2.0: no warnings).
