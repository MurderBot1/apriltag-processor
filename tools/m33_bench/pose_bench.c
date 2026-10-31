/* Cortex-M33 image of the pose solver for tools/m33_pose_cycles.py (inputs are written into fixed buffers by the emulator). */
#include "../../firmware/core/atpose.h"

#define FIELD ((at_field_t *)0x20030000u)
#define MEAS  ((at_meas_t *)0x20038000u)
#define OUT   ((at_pose_t *)0x2003B000u)
#define PARAM ((volatile uint32_t *)0x2003A000u)   /* [0] number of measurements, [1] result code */

void bench_run(void) { PARAM[1] = (uint32_t)at_solve(FIELD, MEAS, (int)PARAM[0], OUT); }
