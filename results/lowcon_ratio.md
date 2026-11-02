# lowcon fix: contrast-ratio register (THRESH bits 31:30)

Cause (measured, `tools/golden.py:binarize`): a tile is only thresholded adaptively ("contrasty") if `diff >= 24` and `2*diff >= max`
(3x3-tile neighbourhood, binned 2x2 values). The `lowcon` frames compress the sensor contrast to 42 % ... 24 % around mid-grey: pixel range of
`lowcon_000` 60..186, `lowcon_009` 70..167, edge-tile `diff` 62..90 against `max` 150..168. `2*diff >= max` therefore fails for every tile (0 contrasty
tiles in `lowcon_009`), so every pixel is classified with `p < abs_black (64)`, and the black level is 59..69: nothing is black, 1 / 54 tags (`lowcon_000` keeps one).
The `diff >= 24` margin is not the problem: 2400..3600 tiles per frame pass it (flat background tiles have diff ~21..25, edge tiles 55..90).

Fix: the ratio test is a 2-bit field `ratio` of the THRESH register (bits 31:30, reset 0 = old behaviour): 0: `2*diff >= max`, 1: `3*diff >= max`,
2: `4*diff >= max`, 3: no ratio test. RTL `rtl/thresh_binarize.v` (`cfg_ratio`), golden `tools/golden.py:binarize(..., ratio)`, bit-exact (test
`tests/test_chain.py::test_lowcon_frame_with_ratio_register_bit_exact`; the default path is unchanged: the 100-frame default run is identical to the committed
`rtl_chain_results.json` for tags and corners).

Why the reset value stays 0: the `noise` frames (noise gain up to 4.5) have flat-background tiles with `diff` ~70..120 and `max` ~170..200; only the
`2*diff >= max` test keeps them from being thresholded as if they were edges. With ratio 1 or 2 those tiles become contrasty, the binary frame fills with speckle, the
labeller drops rows (CCL flag `row dropped`, max row time 1900 clocks against 686..800 per line) and the real tags are lost. The golden model without
capacity limits does not show this (57 / 57 for all ratios on the previous 90 degree dataset; not re-run on the CIL023 dataset), so it is a labeller capacity effect.

Dataset re-rendered with the CIL023 camera model (82.2 degrees, -5 % TV distortion; 570 detectable tags, previously 647 with the 90 degree model). The per-frame tile statistics and the golden-model sweeps in this file (edge-tile `diff` / `max` ranges, tile counts, noise tile values, the golden ratio sweep, the miss list for the other categories) are from the previous 90 degree frames and were not re-measured; the sensor model and the contrast / noise settings are unchanged. Only the chain table below is re-measured.

Full 100-frame RTL chain (CSI-2 at 120 fps timing -> `cam_core` -> C tag unit), detected / detectable GT tags, 0 false positives in every run:

| category | tags | ratio 0 (reset, before) | ratio 1 (3x) | ratio 2 (4x) |
|---|---|---|---|---|
| blur | 52 | 49 | 49 | 49 |
| bright | 78 | 77 | 78 | 78 |
| clutter | 51 | 47 | 47 | 47 |
| dark | 59 | 59 | 59 | 59 |
| grad | 66 | 66 | 66 | 66 |
| lowcon | 54 | 1 | **54** | **54** |
| noise | 50 | 50 | 29 | 19 |
| normal | 52 | 52 | 52 | 52 |
| persp | 66 | 62 | 62 | 62 |
| shadow | 42 | 38 | 38 | 38 |
| **all** | 570 | 501 | 534 | 524 |

Automatic per-frame ratio selection in the MCU firmware (lowcon 66 / 66 without the noise loss, simulated): `results/auto_ratio.md`.

Files: `rtl_chain_results.json` (ratio 0), `rtl_chain_results_ratio1.json`, `rtl_chain_results_ratio2.json`; reproduce with
`CHAIN_THR=420A4018 CHAIN_TAG=_r1 CHAIN_OUT=results/x.json py -3.12 tests/run_chain_dataset.py` (ratio 1; `820A4018` = ratio 2) and
`CHAIN_OUT=results/x.json py -3.12 tests/analyze_chain.py`. `chain.thr_word()` builds the register value. Bright gains one tag at ratio 1 / 2 (77 -> 78).

Golden-model sweep (ISS-equivalent C tag unit, 100 frames, no labeller capacity limit): ratio 2 / 3 / 4 / off with `diff_min = 24`: lowcon 0 / 66 / 66 / 66; ratio 8 (`8*diff >= max`)
loses normal and persp tags; no ratio test with `diff_min` 24 loses 12 tags (blur, grad, normal, shadow 2 each, persp 4).

Why frames miss tags in the other categories (report only, golden-model misses with the reset values; tags that the reference detector finds):
* `persp`: small and grazing tags: px_min_edge 10..15 px at 63..75 degrees incidence (persp_006/008/009). The CCL `min_dim` 10 and the 8x8 tile size cut these off.
* `blur` (blur 2.4..3): edge contrast after blur falls to 82..110 and tags have 34..52 px edges at 31..43 degrees (blur_003/008/009).
* `shadow`: shadow edges across the tag (shadow_002/006/007/008), 23..49 degrees, vis_fraction 0.87..1.0; the 3x3-tile min/max is dominated by the shadow, not by the tag.
* `clutter_008`: two 20 px tags at 57 degrees incidence.

Timing/fit (nextpnr-ecp5, ECP5-45F, seed 1, 85.714 MHz core, 200 MHz D-PHY; estimates, not signoff): after the change core 89.58 MHz PASS, D-PHY 207.90 MHz PASS, 12874 LUT4 (29 %), 56 / 108 DP16KD;
same flow on the unmodified main: 90.99 / 206.02 MHz PASS, 12956 LUT4, 56 DP16KD.
