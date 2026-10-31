#pragma once
#include "atapp.h"

/* FPGA frame bus receiver (PIO + DMA): two frame buffers in SRAM, ping-pong; a third packet is dropped (counted in `lost`). */
void hal_frame_init(void);                                  /* call once the FPGA is configured */
int  hal_frame_get(void *ctx, at_frame_buf_t *b);           /* at_hal_t.frame_get */
void hal_frame_put(void *ctx);                              /* at_hal_t.frame_put */
