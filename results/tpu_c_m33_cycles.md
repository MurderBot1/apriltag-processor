# C TPU on a Cortex-M33 (RP2350 core): estimated time per frame, RTL-chain packets

`py -3.12 tools/m33_cycles.py --opt=-O3 --packets sim/chain_packets` (packets written by tests/run_chain_dataset.py). Unicorn executes the real Thumb-2 image of firmware/core/attpu.c (checked equal to the PC build on all 100 frames) and a table-driven Cortex-M33 cycle model costs it (see the script header). 150 MHz, one core, -O3 (the firmware setting). ESTIMATE, not measured on silicon.

Cortex-M33 @ 150 MHz, one core, -O3; frame period 8.33 ms; budget (doc experiment 1): median <= 6 ms, worst <= 12 ms
| category | frames | tags | cand (median) | instr (median) | optimistic med/max ms | nominal med/max ms | pessimistic med/max ms |
|---|---|---|---|---|---|---|---|
| blur | 10 | 54 | 7 | 117214 | 0.92 / 1.37 | 1.16 / 1.74 | 1.38 / 2.07 |
| bright | 10 | 80 | 8 | 161106 | 1.26 / 1.58 | 1.59 / 2.00 | 1.89 / 2.37 |
| clutter | 10 | 57 | 29 | 419247 | 3.24 / 4.61 | 4.08 / 5.81 | 4.83 / 6.90 |
| dark | 10 | 70 | 8 | 174707 | 1.36 / 6.56 | 1.72 / 8.26 | 2.04 / 9.79 |
| grad | 10 | 75 | 8 | 162184 | 1.26 / 3.28 | 1.60 / 4.13 | 1.90 / 4.90 |
| lowcon | 10 | 0 | 0 | 32 | 0.00 / 1.02 | 0.00 / 1.28 | 0.00 / 1.52 |
| noise | 10 | 57 | 30 | 378790 | 2.94 / 7.39 | 3.71 / 9.29 | 4.40 / 11.02 |
| normal | 10 | 62 | 7 | 141899 | 1.11 / 1.87 | 1.40 / 2.36 | 1.66 / 2.80 |
| persp | 10 | 65 | 9 | 158345 | 1.23 / 1.42 | 1.56 / 1.79 | 1.85 / 2.13 |
| shadow | 10 | 43 | 7 | 126254 | 0.98 / 4.91 | 1.23 / 6.17 | 1.46 / 7.33 |
| all | 100 | 563 | 8 | 160747 | 1.25 / 7.39 | 1.59 / 9.29 | 1.89 / 11.02 |
optimistic   median 1.25 ms  p95 4.99  max 7.39  frames > 8.33 ms: 0  > 12 ms: 0
nominal      median 1.59 ms  p95 6.26  max 9.29  frames > 8.33 ms: 3  > 12 ms: 0
pessimistic  median 1.89 ms  p95 7.43  max 11.02  frames > 8.33 ms: 5  > 12 ms: 0

Pose solver: `py -3.12 tools/m33_pose_cycles.py` (float = single-precision FPU build, double = software doubles, the real firmware with the RP2350 DCP lies between):

pose solve, float (FPU): frames with tags 90; nominal median 1.801 ms  p95 2.982  max 3.607  (optimistic max 2.611, pessimistic max 4.382)
pose solve, double (software): frames with tags 90; nominal median 3.049 ms  p95 4.956  max 8.827  (optimistic max 7.487, pessimistic max 10.067)
