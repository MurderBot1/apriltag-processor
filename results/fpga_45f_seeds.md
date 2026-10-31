# FPGA place and route, architecture A3 (generated from sim/fpga_s*/nextpnr.log by the commands below)

`FPGA_OUT=sim/fpga_s<N> bash tools/fpga_flow.sh <N> 85.714` (LFE5U-45F, CABGA381, speed 8; yosys 0.66, nextpnr-ecp5 0.7; frame-bus pins in bank 6). nextpnr estimates, not signoff.

| seed | core clk100 fmax (target 85.714) | D-PHY sclk fmax (target 200) | LUT4 | DP16KD |
|---|---|---|---|---|
| 1 | 90.99 MHz PASS | 206.02 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 2 | 85.48 MHz FAIL | 216.64 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 3 | 87.50 MHz PASS | 217.49 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 4 | 87.47 MHz PASS | 211.86 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 5 | 81.73 MHz FAIL | 204.88 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 6 | 87.91 MHz PASS | 201.53 MHz PASS | 12227/43848    27% | 56/  108    51% |

Trial on the ECP5-25F (`FPGA_DEVICE=25k`, CABGA381, speed 8, seed 1, one run only): LUT4 12227/24288    50%, DP16KD 56/   56   100%, core 93.11 MHz PASS, D-PHY 216.31 MHz PASS. It fits only because every block RAM is used (100 %); the LCSC 25F listings are speed grades 6/7 (docs/costdown.md section 4), which cannot receive the 800 Mb/s lanes, and no speed-8 25F price was found.
