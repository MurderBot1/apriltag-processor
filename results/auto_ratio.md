# Automatic contrast-ratio selection

Firmware policy `firmware/core/atratio.c` (host-testable, runs inside `at_app_poll`), protocol `SET_AUTO_RATIO` (0x10), see `docs/protocol.md`.
Background: `results/lowcon_ratio.md` (THRESH `ratio` field: ratio 1 fixes `lowcon` 0 -> 66 / 66 but costs `noise` 57 -> 31 through labeller row drops).
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
the noisy frames that lose tags show the CCL `row dropped` flag (`noise_004` .. `noise_009`: flags 1 or 9, 1892 .. 2712 max row clocks) while all `lowcon`
frames and all other categories show no row drop at ratio 1 (checked over the 100 frames of `rtl_chain_results_ratio1.json`; `clutter_003/006` and `dark_002` have flag 8
= more than 64 candidates, which the policy ignores).

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
| blur | 100 | 590 | 540 | 540 | **540** | +0 | 0 | - | 0 | 0 |
| bright | 100 | 810 | 800 | 810 | **800** | +0 | 0 | - | 0 | 0 |
| clutter | 100 | 590 | 570 | 570 | **570** | +0 | 0 | - | 0 | 0 |
| dark | 100 | 690 | 690 | 690 | **690** | +0 | 0 | - | 0 | 0 |
| grad | 100 | 750 | 750 | 750 | **750** | +0 | 0 | - | 0 | 0 |
| lowcon | 100 | 660 | 0 | 660 | **637** | +637 | 96 | 4 | 1 | 4 |
| noise | 100 | 570 | 570 | 310 | **570** | +0 | 0 | - | 0 | 0 |
| normal | 100 | 620 | 620 | 620 | **620** | +0 | 0 | - | 0 | 0 |
| persp | 100 | 720 | 650 | 650 | **650** | +0 | 0 | - | 0 | 0 |
| shadow | 100 | 470 | 430 | 430 | **430** | +0 | 0 | - | 0 | 0 |
| **all** | 1000 | 6470 | 5620 | 6030 | **6257** | +637 | | | | |

The whole dataset as one stream (scene changes between categories), detectable tags found:

| order | frames | GT tags | fixed 0 | fixed 1 | auto | ratio-1 frames | switches |
|---|---|---|---|---|---|---|---|
| file order (sorted names) | 100 | 647 | 562 | 603 | **605** | 10 | 2 |
| categories reversed | 100 | 647 | 562 | 603 | **606** | 56 | 1 |
| lowcon first | 100 | 647 | 562 | 603 | **606** | 60 | 2 |
| noise, lowcon, clutter, noise, lowcon | 50 | 305 | 171 | 251 | **214** | 20 | 2 |

## Before / after per category (one pass of 10 frames)

| category | GT tags | measured fixed 0 (before) | measured fixed 1 | auto, steady state (simulated) | auto, first pass (simulated) |
|---|---|---|---|---|---|
| blur | 59 | 54 | 54 | 54 | 54 |
| bright | 81 | 80 | 81 | 80 | 80 |
| clutter | 59 | 57 | 57 | 57 | 57 |
| dark | 69 | 69 | 69 | 69 | 69 |
| grad | 75 | 75 | 75 | 75 | 75 |
| lowcon | 66 | 0 | 66 | **66** | 43 (frames 0..3 lost) |
| noise | 57 | 57 | 31 | 57 | 57 |
| normal | 62 | 62 | 62 | 62 | 62 |
| persp | 72 | 65 | 65 | 65 | 65 |
| shadow | 47 | 43 | 43 | 43 | 43 |
| **all** | 647 | 562 | 603 | 628 | 605 |

Steady state = a pass after the switch (66 / 66 lowcon, other categories unchanged from ratio 0). Over ten passes (table above) lowcon finds 637 of 660 because the first pass finds 43.

## Frames lost at the switch

A scene that needs ratio 1 (`lowcon`) is blind until the policy has seen 3 tagless frames and the register write has reached the sensor: frames 0 .. 3
(4 frames = 33 ms at 120 fps) give no tag, the first tag is found in frame 4, and from there the stream is as good as fixed ratio 1 (66 / 66). Latency 1: 3 frames lost
(642 of 660 over 100 frames), latency 3: 5 frames lost (629 of 660). Without auto, `lowcon` stays at 0 forever.
Scene changes (second table): noise first, lowcon, clutter, noise, lowcon again: auto 214, fixed 0 171, fixed 1 251 of 305. Fixed ratio 1 finds more in that order because the policy, sitting at ratio 1 after the first `lowcon` block, meets the second `noise` block, takes a row drop, goes back to ratio 0 and is locked out of ratio 1 for 32 frames, which covers most of the following `lowcon` block (that is the hysteresis price; compare the lockout against how often real scenes change). In every order tried, auto is above fixed 0.

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
