# Architecture

```
                  24 MHz osc                                    USB-C (power + data, FS device)
                      |                                                   |
  +-----------+   +---v---------------------------------+  8-bit frame bus  +-----v----------------------+
  |  OV9281   |   |  ECP5 LFE5U-45F-8BG381C (custom RTL) |  21 MB/s strobe   |  RP2350A (MCU, 2 x M33)   |
  | 1280x800  |MIPI  dphy_rx -> csi2_rx -> thresh_binarize ->  mask_stream ----->  PIO + DMA -> 2 x 132 KB  |
  | global    |2-lane|  (LVDS gearing,  (packet     (adaptive   |  (mask +   |   frame buffers (SRAM)    |
  | shutter   +----->|   sync, deskew)   layer)      threshold)  |  cand. list)|  - tag unit in C (attpu.c) |
  | 120 fps   |      |        -> despeckle -> run_ccl -----------+            |  - pose solve (LM)         |
  +-----^-----+      |           (3x3 maj.)   (components)  SPI <------------>|  - USB CDC link            |
        |I2C         |  i2c_master + sensor_init ROM  spi_slave  |   12 MHz   |  - field map + calibration |
        +------------+-------------------------------------------+            |    flash storage, auto exp.|
                       no frame store, no CPU in the FPGA                     +----------------------------+
```

The FPGA does everything that is per pixel and streaming: it never stores a frame. The binary (thresholded, despeckled) frame leaves it at the pixel rate
together with the candidate list of the labeller; the MCU receives it into SRAM, decodes the tags (sub-pixel corners, tag36h11 match, `firmware/core/attpu.c`),
solves the camera pose from the stored field map, and streams it to the host. (Architecture "A3" of `docs/costdown.md`: this is what lets the FPGA
be the 45k-LUT part instead of the 85k one. The old design ran the tag decoder in a custom FPGA processor, the TPU, and held two frame banks in block RAM.)

## Pixel path (what the chip does to every frame)

| stage | module | what it does | latency |
|---|---|---|---|
| D-PHY RX | `dphy_rx`, `dphy_lane`, `async_fifo` | LVDS DDR 4:1 gearing from the sensor clock lane, SoT-sync hunt (3 zero bytes + 0xB8) at all 8 bit alignments, both nibble orders tried in parallel, 2-lane deskew, CDC to the 100 MHz core clock | ~1 us |
| CSI-2 | `csi2_rx` | header ECC (SEC-DED, 1-bit correction), CRC-16, FS/FE, line count check; 2 pixels / clock | 3 clocks |
| threshold | `thresh_binarize` | 2x2 binning, 8x8-pixel tile min/max, 3x3 tile neighbourhood, per-tile contrast test, black mask; 17-row delay line | 17 rows |
| despeckle | `despeckle` | 3x3 majority filter (suppresses isolated speckle so the labeller is not flooded) | 1 row |
| components | `run_ccl` | streaming run-based 4-connected labelling, union-find with **label recycling**, per-component area and 8 directional extremes; filters; the **64 largest** candidates by area are kept as records; capacity limits degrade a frame (flags) and never reject it | 2-3 rows + termination (median `done` 185 clocks after the last row) |
| stream | `mask_stream` | packs the despeckled pixels into 32-bit words (bit x%32 = pixel x), sends header + 32,000 mask words + trailer + the 64 candidate records over an 8-bit strobed bus (132,128 bytes per frame, `docs/fpga.md`) | pixel rate (1 byte per 4 clocks), candidates ~0.2 ms after the mask |
| bridge | `cam_core`, `spi_slave` | registers (SPI mode 0, <= 16 MHz), device clock, brightness sum, I2C bring-up of the sensor | - |
| tag unit (**MCU**) | `firmware/core/attpu.c` | C port of the old TPU program, bit-exact: coarse quad -> sub-pixel edge refinement by line fitting on binary samples -> homography -> 6x6 sampling -> tag36h11 match (587 codes x 4 rotations, bucket index) | median 1.6 ms, worst 9.3 ms per frame (estimate, Cortex-M33 @ 150 MHz) |

### Where the tag decoder runs, and why it is bit-exact with the old FPGA processor
The decoder is a small *fixed program* with a lot of fixed-point multiply/divide and pixel look-ups. It was first built as a custom FPGA processor
(the TPU, `ref/tpu/tpu_core.v`, program `tools/tpu_prog.py`, golden Python model `tools/tpu_isa.py`), which needed 10 k LUT4, 8 block RAMs and, with the
two 1 Mbit frame banks it read, most of the 85k-LUT part. `firmware/core/attpu.c` is a line-by-line port of that program to C (Q16.16 integer arithmetic, 64-bit
multiply/shift, 48/32-bit divide on the Cortex-M33's 32-bit divider, a bucket index instead of scanning all 2,348 tag codes). `tests/test_fw_tpu.py` checks the
whole result image against the ISS word for word on all 100 dataset frames (and thresholds, corrupted masks, random candidate records); the RTL chain
(`tests/run_chain_dataset.py`) gives the same tags and corners as the old all-FPGA chain on every one of the 100 frames (0 px difference).
The ISS is itself checked against the old RTL (`tests/test_tpu.py`), so the C code is transitively equal to the hardware it replaced.

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
* two frame buffers in the MCU's SRAM (2 x 132 KB): frame N is processed by the tag unit (median 1.6 ms, worst 9.3 ms, estimated) while frame N+1
  streams into the other buffer, so capture never stalls; a packet is lost (and counted) only if both buffers are busy when it starts, which needs the
  processing of a frame to take more than ~10 ms (`results/frame_budget.md`)
* end-to-end latency (last pixel -> tag list on the MCU) = 17-row threshold delay + 1 row despeckle + ~2-3 rows CCL + the candidate list
  (~0.2 ms) + tag unit time

## Memory map (SPI, 24-bit byte addresses; registers only, frames travel on the frame bus)

| address | content |
|---|---|
| `0x000000..0x0000FF` | registers (ID `0x41544731`, CTRL, thresholds, STATUS, counters, I2C bridge, FRAME_SUM) |

Tag record (produced by `attpu_run`, same layout the FPGA result RAM used to hold; `attpu_pack_results`): 16 words, `w0 = 0x80000000 | ham<<12 | rot<<10 | id`,
`w1..w8` = corners TL,TR,BR,BL as (x,y) Q16.16 pixels (pixel centre of the top-left pixel = (0,0)), `w9` label, `w10` area, `w11` frame id, `w12` quad area.
Frame packet (FPGA -> MCU): `docs/fpga.md`, `firmware/core/atframe.h`.

## Pose solve (MCU)

`firmware/core/atpose.c`: corner pixels -> undistort with the stored calibration -> homography pose of the largest tag ->
Levenberg-Marquardt over *all* tag corners (6 DoF, analytic Jacobian) -> planar-ambiguity second start for single tags ->
leave-one-out outlier rejection. Output: camera position and orientation in the world frame defined by the field map.
Float32 build is what runs on the RP2350 (single-precision FPU).
