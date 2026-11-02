# C TPU on a Cortex-M33 (RP2350 core): estimated time per frame, RTL-chain packets

`py -3.12 tools/m33_cycles.py --opt=-O3 --packets sim/chain_packets` (packets written by tests/run_chain_dataset.py). Unicorn executes the real Thumb-2 image of firmware/core/attpu.c (checked equal to the PC build on all 100 frames) and a table-driven Cortex-M33 cycle model costs it (see the script header). 150 MHz, one core, -O3 (the firmware setting). ESTIMATE, not measured on silicon.

attpu_init: 626360 instr, optimistic 4.484 ms, nominal 5.632 ms, pessimistic 6.420 ms

Cortex-M33 @ 150 MHz, one core, -O3; frame period 8.33 ms; budget (doc experiment 1): median <= 6 ms, worst <= 12 ms
| category | frames | tags | cand (median) | instr (median) | optimistic med/max ms | nominal med/max ms | pessimistic med/max ms |
|---|---|---|---|---|---|---|---|
| blur | 10 | 49 | 6 | 113390 | 0.88 / 1.55 | 1.12 / 1.96 | 1.33 / 2.33 |
| bright | 10 | 77 | 8 | 160773 | 1.25 / 1.42 | 1.59 / 1.80 | 1.89 / 2.14 |
| clutter | 10 | 49 | 30 | 364691 | 2.82 / 5.41 | 3.54 / 6.76 | 4.20 / 7.99 |
| dark | 10 | 60 | 8 | 159854 | 1.25 / 6.88 | 1.58 / 8.64 | 1.88 / 10.26 |
| grad | 10 | 66 | 8 | 153216 | 1.19 / 3.17 | 1.51 / 4.00 | 1.79 / 4.74 |
| lowcon | 10 | 1 | 0 | 32 | 0.00 / 0.71 | 0.00 / 0.89 | 0.00 / 1.05 |
| noise | 10 | 50 | 23 | 314779 | 2.44 / 7.78 | 3.08 / 9.77 | 3.65 / 11.58 |
| normal | 10 | 52 | 5 | 102048 | 0.80 / 1.57 | 1.00 / 1.98 | 1.19 / 2.36 |
| persp | 10 | 63 | 8 | 151585 | 1.18 / 1.41 | 1.49 / 1.78 | 1.77 / 2.12 |
| shadow | 10 | 38 | 7 | 102970 | 0.80 / 4.24 | 1.00 / 5.32 | 1.19 / 6.32 |
| all | 100 | 505 | 8 | 157790 | 1.22 / 7.78 | 1.54 / 9.77 | 1.82 / 11.58 |
optimistic   median 1.22 ms  p95 5.44  max 7.78  frames > 8.33 ms: 0  > 12 ms: 0
nominal      median 1.54 ms  p95 6.79  max 9.77  frames > 8.33 ms: 3  > 12 ms: 0
pessimistic  median 1.82 ms  p95 8.03  max 11.58  frames > 8.33 ms: 5  > 12 ms: 0

Pose solver: `py -3.12 tools/m33_pose_cycles.py` (float = single-precision FPU build, double = software doubles, the real firmware with the RP2350 DCP lies between):

pose solve, float (FPU): frames with tags 91; nominal median 1.504 ms  p95 2.849  max 3.255  (optimistic max 2.358, pessimistic max 3.953)
pose solve, double (software): frames with tags 91; nominal median 2.699 ms  p95 4.515  max 7.809  (optimistic max 6.619, pessimistic max 8.907)
