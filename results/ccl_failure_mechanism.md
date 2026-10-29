# Step 0: why overflowing frames produced 0 tags (original `run_ccl.v`, before the noise-robustness rework)

Instrumentation: `tb/tb_cam.v` built with `-DTRACE` prints per frame `ccl_done`, `ccl_flags`, `ccl_count`, `tpu_start`, `cancel`,
`csi_frame_ok` and the number of rows the run detector dropped for backpressure. Frames `bright_x013` and `dark_c`, one frame per run,
full chain at 120 fps timing (100 MHz sim clock, 800 clocks/line).

| | bright_x013 | dark_c |
|---|---|---|
| CCL flags at `done` (cand,lab,run,row) | 0111 | 0111 |
| `ccl_count` (candidates handed to the TPU) | 0 | 9 |
| rows dropped by `ovf_row` backpressure | 13 | 25 |
| `max_row_cycles` (reg 0x28) | 1254 | 914 |
| `cancel` / `csi_frame_ok` | 0 / 1 | 0 / 1 |
| `S_DONE` reached, `ccl_done` fired | yes (18.5k clk after FE) | yes |
| `tpu_start` | **yes**, count=0 | **yes**, count=9 |
| TPU cycles | 24 | 290,669 |
| tags | 0 | 0 (the stored JSON from an earlier RTL state has 4) |

Findings

1. The TPU is **not** gated by `ccl_flags`, `cancel` or `tpu_busy` on these frames: `cam_core.v` starts the TPU on every `ccl_done`
   (only `cancel || tpu_busy` drops a frame, neither was set). `S_DONE` is always reached. The "0 tags" frames are frames where the TPU
   ran, with no usable candidate list.
2. The candidates are missing because the CCL **loses data inside the frame**, not because the frame is flagged:
   * `nlab` hits 1024 (`ovf_lab`) well before the bottom of the image; labels are never freed, so every later run gets label 0
     (background) and a tag in the lower half cannot form a component.
   * `ovf_row` is real and binding: the labeller needs ~20-25 clocks per run (`S_CUR_SET`..`S_WRLAB`), i.e. only ~35 runs fit in one
     line period. Busy rows queue (2 pending), then `pend >= 2` drops the row; the dropped row breaks the connectivity of everything
     crossing it. `tests/sweep_noise.py` does not model this.
   * run overflow (64 runs/row) additionally truncates busy rows.
3. Raising only the capacities does not fix it: with `MAXR=256`, `NLAB=4096` (scratch experiment, same two frames) the dropped rows
   go **up** (13 -> 30 and 25 -> 105 rows) because rows now carry more runs, `max_row_cycles` rises to 1663 / 1921, and `nlab` still
   reaches 4096. So the labeller must be made several times faster per run and must recycle labels; the sweep model's three capacity
   limits are necessary but not sufficient.

Run-count statistics of the noisy frames (`tests/sweep_ccl_rtl.py`, golden masks): the worst frames have 100-140 runs on every row
(113,759 runs in `glare_x005`) but almost all runs just extend a run of the previous row (1.0 overlaps per run, 0.5-1 % new labels), so
the sequencer needs a fast path for "extend the label of the overlapping run" rather than a larger label table.
