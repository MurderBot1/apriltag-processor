# FPGA place and route, architecture A3 (generated from sim/fpga_s*/nextpnr.log by the commands below)

`FPGA_OUT=sim/fpga_s<N> bash tools/fpga_flow.sh <N> 85.714` (LFE5U-45F, CABGA381, speed 8; yosys 0.66, nextpnr-ecp5 0.7). nextpnr estimates, not signoff.

| seed | core clk100 fmax (target 85.714) | D-PHY sclk fmax (target 200) | LUT4 | DP16KD |
|---|---|---|---|---|
| 1 | 89.57 MHz PASS | 209.86 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 2 | 86.24 MHz PASS | 206.14 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 3 | 91.40 MHz PASS | 195.69 MHz FAIL | 12227/43848    27% | 56/  108    51% |
| 4 | 89.09 MHz PASS | 193.61 MHz FAIL | 12227/43848    27% | 56/  108    51% |
| 5 | 86.78 MHz PASS | 206.44 MHz PASS | 12227/43848    27% | 56/  108    51% |
| 6 | 84.07 MHz FAIL | 193.27 MHz FAIL | 12227/43848    27% | 56/  108    51% |

Trial on the ECP5-25F (`FPGA_DEVICE=25k`, CABGA381, speed 8, seed 1, one run only): LUT4 12227/24288    50%, DP16KD 56/   56   100%, core 87.66 MHz PASS, D-PHY 208.46 MHz PASS. It fits only because every block RAM is used (100 %); the LCSC 25F listings are speed grades 6/7 (docs/costdown.md section 4), which cannot receive the 800 Mb/s lanes, and no speed-8 25F price was found.
