# Architecture

```
                  24 MHz osc                                    USB-C (power + data, FS device)
                      |                                                   |
  +-----------+   +---v---------------------------------------+      +-----v-------------+
  |  OV9281   |   |  ECP5 LFE5U-85F-8BG381C  (custom RTL)     |      |  RP2350A (MCU)    |
  | 1280x800  |   |                                           | SPI  |  - USB CDC link   |
  | global    |MIPI  dphy_rx -> csi2_rx -> thresh_binarize -> |<---->|  - field map +    |
  | shutter   |2-lane|  (LVDS gearing,  (packet     (adaptive    |12 MHz  calibration     |
  | 120 fps   +----->|   sync, deskew)   layer)      threshold)  |      |    flash storage |
  |           |      |        -> despeckle -> run_ccl -> TPU     |      |  - pose solve     |
  +-----^-----+      |           (3x3 maj.)   (components)  (own |      |    (LM over all   |
        |I2C         |                         CPU, baked ROM)   |      |     tag corners)  |
        +------------+  i2c_master + sensor_init ROM  spi_slave  |      |  - auto exposure  |
                     +-------------------------------------------+      +-------------------+
                       frame banks 2x1 Mbit | candidate RAM | result RAM
```

Everything per-pixel and per-tag is hardware. The MCU never sees an image: it receives, for each decoded tag, an
ID and four sub-pixel corners (Q16.16), solves the camera pose from the stored field map, and streams it to the host.

## Pixel path (what the chip does to every frame)

| stage | module | what it does | latency |
|---|---|---|---|
| D-PHY RX | `dphy_rx`, `dphy_lane`, `async_fifo` | LVDS DDR 4:1 gearing from the sensor clock lane, SoT-sync hunt (3 zero bytes + 0xB8) at all 8 bit alignments, both nibble orders tried in parallel, 2-lane deskew, CDC to the 100 MHz core clock | ~1 us |
| CSI-2 | `csi2_rx` | header ECC (SEC-DED, 1-bit correction), CRC-16, FS/FE, line count check; 2 pixels / clock | 3 clocks |
| threshold | `thresh_binarize` | 2x2 binning, 8x8-pixel tile min/max, 3x3 tile neighbourhood, per-tile contrast test, black mask; 17-row delay line | 17 rows |
| despeckle | `despeckle` | 3x3 majority filter (suppresses isolated speckle so the labeller is not flooded) | 1 row |
| components | `run_ccl` | streaming run-based 4-connected labelling, union-find with **label recycling**, per-component area and 8 directional extremes; filters; the **64 largest** candidates by area are kept as records; capacity limits degrade a frame (flags) and never reject it | 2-3 rows + termination (median `done` 185 clocks after the last row) |
| tag unit | `tpu_core` | **custom processor**, baked program: coarse quad -> sub-pixel edge refinement by line fitting on binary samples -> homography -> 6x6 sampling -> tag36h11 match (587 codes x 4 rotations in ROM) | ~0.2 ms / 6 tags |
| bridge | `cam_core`, `spi_slave` | ping-pong frame/candidate/result banks, registers, SPI (mode 0, <= 16 MHz), I2C bring-up of the sensor | - |

### Why the TPU (and not a CPU running code)
The tag decoder is a small *fixed program* with a lot of fixed-point multiply/divide and pixel look-ups. The TPU
(`tools/tpu_isa.py`, `rtl/tpu_core.v`) is a 32-bit processor with exactly the operations that program needs: Q16.16
multiply/shift, 64-bit-numerator divide, a binary-frame pixel fetch, candidate read, result write and a hardware
`TAGMATCH` instruction that scans the baked code ROM. Its program (`tools/tpu_prog.py`, 574 words) is assembled
into the instruction ROM at build time, so the chip contains the algorithm; there is no firmware to load. A Python
instruction-set simulator is the golden model and the RTL is checked **bit-exact** against it (every arithmetic corner
case, plus full scenes).

## Timing budget at 120 fps

OV9281 settings (`tools/ov9281_init.py`, register values from the mainline Linux driver):
400 MHz DDR link = 800 Mb/s per lane, 2 lanes, RAW8 -> 200 Mpixel/s; HTS = 1600 px, VTS = 1041 lines ->
**200e6 / (1600 x 1041) = 120.08 fps**.

* byte clock = 100 MHz; 2 pixels per clock; one line = 800 clocks (640 carry pixels), frame = 832,800 clocks (8.328 ms)
* threshold + CCL are paced by the line rate; the labeller needs about 2-4 clocks per run on the common path (a run that just
  extends the label of the run above it), 256 runs per row are kept, and up to 4 rows (2 pending + current + previous) may be
  in flight, so even a 100-140 runs-per-row noise frame (113,759 runs, slowest row 590 clocks) fits the 686-clock line of the
  real 85.714 MHz core. Unions of several components, new labels and finished components cost more (10-20 clocks each); a
  row that still cannot be labelled in time is dropped with a flag (`max_row_cycles` is exported in the status registers) -
  never a hang. 7 of 500 frames of an earlier (historical) evaluation set lose 1-5 rows that way, none of the current 100, see `docs/verification.md`
* two frame banks: frame N is processed by the TPU (median ~0.2-0.35 ms, worst case measured 2.1 ms) while frame N+1
  streams into the other bank, so capture never stalls; a frame is only dropped (and counted) if the TPU is still busy
  with the bank the next frame would overwrite
* end-to-end latency (last pixel -> tag list in the result RAM) = 17-row threshold delay + 1 row despeckle +
  ~2-3 rows CCL + TPU run ~ 0.15 ms + TPU time

## Memory map (SPI, 24-bit byte addresses)

| address | content |
|---|---|
| `0x000000..0x0000FF` | registers (ID `0x41544731`, CTRL, thresholds, STATUS, counters, I2C bridge, FRAME_SUM) |
| `0x001000`, `0x002000` | result banks 0/1: word0 = tag count, record i at word 16+16i |
| `0x100000`, `0x200000` | debug read-back of the binary frame banks (only while the TPU is idle) |
| `0x300000`, `0x301000` | candidate RAM banks (debug) |

Result record (16 words): `w0 = 0x80000000 | ham<<12 | rot<<10 | id`, `w1..w8` = corners TL,TR,BR,BL as (x,y) Q16.16 pixels
(pixel centre of the top-left pixel = (0,0)), `w9` label, `w10` area, `w11` frame id, `w12` quad area.
The same tables are in `rtl/cam_core.v` and `firmware/core/atapp.h`.

## Pose solve (MCU)

`firmware/core/atpose.c`: corner pixels -> undistort with the stored calibration -> homography pose of the largest tag ->
Levenberg-Marquardt over *all* tag corners (6 DoF, analytic Jacobian) -> planar-ambiguity second start for single tags ->
leave-one-out outlier rejection. Output: camera position and orientation in the world frame defined by the field map.
Float32 build is what runs on the RP2350 (single-precision FPU).
