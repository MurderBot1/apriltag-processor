# Noise / overflow sweep (golden models + TPU ISS, 500 frames, 2825 detectable tags)

`tests/sweep_noise.py`, `tests/sweep_candidates.py`. The overflow model reproduces the chip (119 modelled vs 123 measured overflow frames).

| variant | found | note |
|---|---|---|
| current chip (RTL chain run) | 2117 (75%) | overflow => 0 tags |
| baseline model | 2019 (71.5%) | 119 overflow frames |
| diff_min 32 / 48 / 64 | 2020 / 1985 / 1935 | raising the contrast threshold does not help |
| 2x2 / 3x3 pre-smoothing | 2077 / 2098 | still 103 / 94 overflow frames; loses tags once overflow is removed |
| no overflow reject, first 64 candidates (label order) | 2467 (87.3%) | no smoothing |
| + smoothing 3x3 | 2402 (85.0%) | smoothing hurts |
| + shape prefilter (fill ratio, aspect) | 2466 | no gain |
| **top 64 candidates by area** | **2651 (93.8%)** | 0 false positives |
| top 32 by area | 2587 (91.6%) | TPU max 843k cycles (fits one 120 fps frame) |
| top 128 / 256 by area | 2651 | no gain, TPU cycles double |

Capacity needed (no overflow rejection): runs/row 192 (64 today: 80 frames over), live+retained labels with recycling <= 2048 (1024 today:
3 frames over; without recycling the peak is the same order, the big fix is not discarding the frame).

Conclusion: smoothing is not the fix (the earlier recommendation is withdrawn). The fix is (1) never abandon the frame on a CCL overflow,
(2) raise runs/row to 192, (3) rank candidates by area and keep the best 64 (or 32 for the cycle budget). TPU worst case is ~1.5M cycles
(> one 832,800-clock frame), so heavy-clutter frames would be dropped in a stream, but each processed frame is complete.
Implemented in `rtl/run_ccl.v` (see `results/ccl_failure_mechanism.md` for why the three capacity limits alone were not enough: the labeller also had to
become ~7x faster per run because `ovf_row` was binding). RTL chain result on the same 500 frames: **2651 / 2825 (93.8 %), 0 false positives**
(`results/rtl_chain_results.json`), identical to the 'top 64 by area' model line above; before: 2158 / 2825 with the same readback harness.
