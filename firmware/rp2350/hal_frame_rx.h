#pragma once
#include "atapp.h"

/* FPGA frame bus receiver (PIO + DMA): AT_NBUF (3) frame buffers in SRAM, oldest packet first; a packet that finds no free buffer is dropped (counted in `lost`). */
void hal_frame_init(void);                                  /* call once the FPGA is configured */
int  hal_frame_get(void *ctx, at_frame_buf_t *b);           /* at_hal_t.frame_get */
void hal_frame_put(void *ctx);                              /* at_hal_t.frame_put */
