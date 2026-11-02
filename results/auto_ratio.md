# Automatic contrast-ratio selection

Firmware policy `firmware/core/atratio.c` (host-testable, runs inside `at_app_poll`), protocol `SET_AUTO_RATIO` (0x10), see `docs/protocol.md`.
Background: `results/lowcon_ratio.md` (THRESH `ratio` field: ratio 1 fixes `lowcon` 1 -> 54 / 54 but costs `noise` 50 -> 29 through labeller row drops).
The RTL and the golden model stay stateless; the MCU picks the ratio per frame from feedback it already has.

## Policy

Input per processed frame: number of tags the tag unit found (`nt`) and the CCL flags carried in the frame packet trailer (bit 0 = `row dropped`).
Output: the `ratio` field (0 or 1) written to THRESH bits 31:30; the other THRESH fields are preserved.

* Start at ratio 0. 3 frames in a row without any tag -> try ratio 1.
* At ratio 1: `row dropped` flag in any frame -> ratio 0 and lock ratio 1 out for 32 frames; 6 tagless frames before any tag was seen -> same.
  Each failed trial doubles the next lockout (32 ... 512 frames). 8 frames with tags at ratio 1 = confirmed (lockout resets); 6 tagless frames after that
  go back to ratio 0 without lockout.
* Any frame with tags at ratio 0 resets the tagless counter, so scenes that already work at the reset value never leave ratio 0 (no regression by construction).
* An explicit `SET_TRACK` ratio 1..3 turns automatic mode off; `SET_AUTO_RATIO 0` fixes ratio 0; automatic mode is on after boot.

Why these signals: at ratio 0 `lowcon` frames give 0 tags (the frames have 0..16 candidates, mostly 0 to 3 for the dark ones), so "no tag" is the symptom; at ratio 1
the noisy frames that lose tags show the CCL `row dropped` flag (`noise_003` .. `noise_009`: flags 1 or 9 in `rtl_chain_results_ratio1.json`), all `lowcon`
frames show no row drop at ratio 1, and so do all other categories except `clutter_002` (flag 1, no tag lost, 47 of 51 tags at ratio 1 as at ratio 0). Re-measured on the CIL023-optics dataset;
`clutter_003/006`, `dark_002`, `noise_001/002/003` and `shadow_003` carry flag 8 = more than 64 candidates, which the policy ignores.

## Method (simulation, not hardware)

`tools/auto_ratio_sim.py` runs the real firmware C code (via `host/apriltag_cam/simfw.py`) on frame sequences. Each frame's tags and CCL register are the
**measured** RTL-chain results of the 100-frame dataset at ratio 0 (`results/rtl_chain_results.json`) or ratio 1 (`results/rtl_chain_results_ratio1.json`),
chosen by the ratio in the THRESH register when the frame is captured. A write after processing frame k takes effect for frame k + 2 (model: packet end 6.7 ms
after capture start, tag unit up to 9.3 ms, SPI write; 1.5 .. 2 frame periods; `--lat` changes it). Frames of one category are repeated 10 times (as
`tools/frame_budget.py`). What is modelled, not measured: the register latency and the assumption that a frame captured at ratio r behaves like the dataset frame
run at ratio r (the dataset frames are independent images, not a video). "found" = detectable ground-truth tags found (0 false positives in all runs).

Reproduce: `py -3.12 tools/auto_ratio_sim.py --lat 2 --md results/_tbl.md --json results/auto_ratio.json`. Test: `tests/test_fw_ratio.py`.

## Results, latency 2 frames

Register write latency 2 frame(s). Each category: its 10 frames repeated 10 times (100 frames). found = detectable GT tags found, summed over the sequence; `first r1` = index of the first frame captured at ratio 1; `frames to first tag` = index of the first frame of the sequence in which auto finds a tag.

| category | frames | GT tags | fixed 0 | fixed 1 | auto | auto - fixed 0 | ratio-1 frames | first r1 | switches | frames to first tag |
|---|---|---|---|---|---|---|---|---|---|---|
| blur | 100 | 520 | 490 | 490 | **490** | +0 | 0 | - | 0 | 0 |
| bright | 100 | 780 | 770 | 780 | **770** | +0 | 0 | - | 0 | 0 |
| clutter | 100 | 510 | 470 | 470 | **470** | +0 | 0 | - | 0 | 0 |
| dark | 100 | 590 | 590 | 590 | **590** | +0 | 0 | - | 0 | 0 |
| grad | 100 | 660 | 660 | 660 | **660** | +0 | 0 | - | 0 | 0 |
| lowcon | 100 | 540 | 10 | 540 | **515** | +505 | 95 | 5 | 1 | 0 |
| noise | 100 | 500 | 500 | 290 | **500** | +0 | 0 | - | 0 | 0 |
| normal | 100 | 520 | 520 | 520 | **520** | +0 | 0 | - | 0 | 0 |
| persp | 100 | 660 | 620 | 620 | **620** | +0 | 0 | - | 0 | 0 |
| shadow | 100 | 420 | 380 | 380 | **380** | +0 | 0 | - | 0 | 0 |
| **all** | 1000 | 5700 | 5010 | 5340 | **5515** | +505 | | | | |

The whole dataset as one stream (scene changes between categories), detectable tags found:

| order | frames | GT tags | fixed 0 | fixed 1 | auto | ratio-1 frames | switches |
|---|---|---|---|---|---|---|---|
| file order (sorted names) | 100 | 570 | 501 | 534 | **523** | 10 | 2 |
| categories reversed | 100 | 570 | 501 | 534 | **529** | 29 | 2 |
| lowcon first | 100 | 570 | 501 | 534 | **530** | 29 | 2 |
| noise, lowcon, clutter, noise, lowcon | 50 | 259 | 149 | 213 | **177** | 9 | 2 |

## Before / after per category (one pass of 10 frames)

| category | GT tags | measured fixed 0 (before) | measured fixed 1 | auto, steady state (simulated) | auto, first pass (simulated) |
|---|---|---|---|---|---|
| blur | 52 | 49 | 49 | 49 | 49 |
| bright | 78 | 77 | 78 | 77 | 77 |
| clutter | 51 | 47 | 47 | 47 | 47 |
| dark | 59 | 59 | 59 | 59 | 59 |
| grad | 66 | 66 | 66 | 66 | 66 |
| lowcon | 54 | 1 | 54 | **54** | 29 (frames 1..4 lost) |
| noise | 50 | 50 | 29 | 50 | 50 |
| normal | 52 | 52 | 52 | 52 | 52 |
| persp | 66 | 62 | 62 | 62 | 62 |
| shadow | 42 | 38 | 38 | 38 | 38 |
| **all** | 570 | 501 | 534 | 554 | 529 |

Steady state = a pass after the switch (54 / 54 lowcon, other categories unchanged from ratio 0). Over ten passes (table above) lowcon finds 515 of 540 because the first pass finds 29.

## Frames lost at the switch

A scene that needs ratio 1 (`lowcon`) is nearly blind until the policy has seen 3 tagless frames and the register write has reached the sensor: frame 0 finds 1 tag at ratio 0 (that resets the tagless counter), frames 1 .. 4
(4 frames = 33 ms at 120 fps) give no tag, the first ratio-1 tag is found in frame 5, and from there the stream is as good as fixed ratio 1 (54 / 54). Latency 1: 523 of 540 over 100 frames,
latency 3: 511 of 540. Without auto, `lowcon` stays at 1 of 54 forever.
Scene changes (second table): noise first, lowcon, clutter, noise, lowcon again: auto 177, fixed 0 149, fixed 1 213 of 259. Fixed ratio 1 finds more in that order because the policy, sitting at ratio 1 after the first `lowcon` block, meets the second `noise` block, takes a row drop, goes back to ratio 0 and is locked out of ratio 1 for 32 frames, which covers most of the following `lowcon` block (that is the hysteresis price; compare the lockout against how often real scenes change). In every order tried, auto is above fixed 0.

## Not verified / needs hardware

* The latency of a THRESH write (when `thr_ratio` is sampled by `thresh_binarize` relative to a frame start) is modelled as 2 frames; the RTL registers the value
  directly, a mid-frame change would mix two ratios inside one frame. Needs a hardware or full-chain test with a register write between frames; it is also unclear whether
  a write while a frame is being thresholded should be latched at frame start (RTL change, not done here).
* Real scene sequences: the dataset frames are independent images, a camera that sees a low-contrast scene produces similar consecutive frames; thresholds (3 / 6 / 8 frames, lockouts)
  were chosen from the dataset flags only. Real noise level versus the row-drop threshold and the real tag-unit processing time decide how often a trial fails.
* A scene with no tag in view alternates ratio 0 / 1 (bounded by the lockouts; unconfirmed trials back off to one trial per 512 frames, confirmed ones return after 6 tagless frames);
  the cost is a few SPI writes, no detection is lost because there is nothing to detect. A scene with tags that disappear at ratio 0 for 3 frames (occlusion) is tried at ratio 1 for
  6+ frames; in the dataset ratio 1 is not worse than ratio 0 for any category except `noise`, where the row-drop flag brings it back.
* RP2350 build (Pico SDK) of `atratio.c` is only added to `firmware/rp2350/CMakeLists.txt`; compiled and run in the host-test library only.
