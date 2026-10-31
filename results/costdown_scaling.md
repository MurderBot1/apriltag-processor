Required PC-core equivalents = per-frame detector time on the Ryzen 9 7900X (single thread) / 8.33 ms; "!" marks needs above the chip capacity.

| CPU (LCSC 1+ price) | PC-core equivalents (x 0.85) | W1 need mean / p95 / max | W2 need mean / p95 / max | W3 need mean / p95 / max | W4 need mean / p95 / max |
|---|---|---|---|---|---|
| RV1106G3 (1x A7 1.2 GHz) $25.39 | 0.07 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0! / 2.3! / 7.1! |
| T113-S3 (2x A7 1.2 GHz) $21.44 | 0.14 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0! / 2.3! / 7.1! |
| i.MX 8M Mini (4x A53 1.8 GHz) $23.49 | 0.48 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0! / 2.3! / 7.1! |
| RK3566 (4x A55 1.8 GHz) $14.65 | 0.52 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0! / 2.3! / 7.1! |
| V853 (1x A7 + NPU) $5.94 | 0.06 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0! / 2.3! / 7.1! |
| RK3576 (4x A72 2.2 GHz + 4x A53 2.0 GHz) $22.82 | 1.14 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0 / 2.3! / 7.1! |
| RK3588 (4x A76 2.35 GHz + 4x A55 1.8 GHz) $65.95 | 1.63 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0 / 2.3! / 7.1! |
| Raspberry Pi 5 BCM2712 (4x A76 2.4 GHz) [not a purchasable chip, reference]  | 1.15 | 6.0! / 7.8! / 8.5! | 10.0! / 12.6! / 13.2! | 2.7! / 3.1! / 3.4! | 1.0 / 2.3! / 7.1! |

Workload times (ms, 7900X single thread): W1 gray, full res, sigma 0.8 (632/647 tags): mean 49.9 p95 65.3 max 70.8; W2 gray, full res, no blur (626/647): mean 83.2 p95 104.9 max 109.7; W3 gray, decimate 2, no blur (613/647): mean 22.4 p95 25.9 max 28.2; W4 after FPGA threshold+despeckle (556/647): mean 8.0 p95 19.0 max 59.1
