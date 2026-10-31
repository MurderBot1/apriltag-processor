/* Freestanding Cortex-M33 image of the C TPU for tools/m33_cycles.py: fixed buffers, two entry points called by the emulator. */
#include "../../firmware/core/attpu.h"

#define FB    ((uint32_t *)0x20020000u)     /* 128000 bytes binary frame */
#define CAND  ((uint32_t *)0x20040000u)     /* 64 x 16 words */
#define OUT   ((attpu_tag_t *)0x20041000u)
#define PARAM ((volatile uint32_t *)0x20042000u)   /* [0] cand_count [1] frame_id [2] maxham [3] -> ntags */

void bench_init(void) { attpu_init(); }
void bench_run(void) { PARAM[3] = (uint32_t)attpu_run(FB, CAND, PARAM[0], PARAM[1], PARAM[2], OUT); }
