Historical (old design, TPU inside the FPGA, 713,840 clocks per frame): produced by tests/analyze_tpu_budget.py as of commit 90940f6, since removed with the FPGA TPU. The A3 numbers are in results/frame_budget.md.

| category | frames | TPU clk median | worst | would drop @ real core (713840) | would drop @ sim core (832800) | CCL flags set | rows dropped (bit 0) |
|---|---|---|---|---|---|---|---|
| blur | 10 | 313612 | 467900 | 0 | 0 | 0 | 0 |
| bright | 10 | 427440 | 535702 | 0 | 0 | 0 | 0 |
| clutter | 10 | 1132059 | 1639421 | 7 | 7 | 2 | 0 |
| dark | 10 | 460428 | 2301041 | 3 | 3 | 0 | 0 |
| grad | 10 | 428871 | 1135044 | 2 | 1 | 0 | 0 |
| lowcon | 10 | 24 | 366474 | 0 | 0 | 0 | 0 |
| noise | 10 | 1015026 | 2553603 | 6 | 6 | 4 | 0 |
| normal | 10 | 376574 | 640158 | 0 | 0 | 0 | 0 |
| persp | 10 | 425408 | 481072 | 0 | 0 | 0 | 0 |
| shadow | 10 | 333365 | 1708784 | 2 | 1 | 0 | 0 |
| all | 100 | | | 20 | 18 | 6 | 0 |
