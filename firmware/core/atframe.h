/* Frame packet that the FPGA streams to the MCU (rtl/mask_stream.v) and its validation.  The packet is received by the platform layer
 * (RP2350: PIO + DMA into a frame buffer); this file is plain C and is also built for the PC tests. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "attpu.h"

#define AT_PKT_MAGIC       0x4D335441u                       /* "AT3M" */
#define AT_PKT_HDR_WORDS   4
#define AT_PKT_MASK_WORDS  ATTPU_FB_WORDS                    /* 800 rows x 40 words */
#define AT_PKT_TRL_WORDS   4
#define AT_PKT_CAND_WORDS  (ATTPU_MAX_CAND * ATTPU_CAND_REC_WORDS)
#define AT_PKT_WORDS       (AT_PKT_HDR_WORDS + AT_PKT_MASK_WORDS + AT_PKT_TRL_WORDS + AT_PKT_CAND_WORDS)   /* 33032 */
#define AT_PKT_BYTES       (4u * AT_PKT_WORDS)               /* 132128 */

/* trailer status bits (T0[7:0]) */
#define AT_PKT_ST_CSI_BAD   0x01u      /* the sensor frame had a CRC / line-count error */
#define AT_PKT_ST_THR_BUSY  0x02u      /* threshold unit was still busy when the next row started (diagnostic) */
#define AT_PKT_ST_FIFO_OVF  0x04u      /* streamer FIFO overflowed: mask words lost */
#define AT_PKT_ST_SHORT     0x08u      /* fewer than 800 rows arrived: mask zero padded */
#define AT_PKT_ST_NO_CCL    0x10u      /* labeller result missing (timeout): no candidates */
#define AT_PKT_ST_DAMAGED   (AT_PKT_ST_CSI_BAD | AT_PKT_ST_FIFO_OVF | AT_PKT_ST_SHORT | AT_PKT_ST_NO_CCL)

typedef struct {
    uint32_t seq;                       /* FPGA packet counter (frame id) */
    uint64_t ts;                        /* device clock (us) at the start of the sensor frame */
    const uint32_t *mask;               /* 32000 words, borrowed from the packet */
    const uint32_t *cand;               /* 1024 words */
    uint32_t cand_count;                /* valid records (<= 64) */
    uint32_t ccl_flags;                 /* labeller diagnostics, see docs/protocol.md STATUS */
    uint32_t status;                    /* AT_PKT_ST_* */
    uint32_t frame_sum;                 /* sum of all pixels (auto exposure) */
    uint32_t max_row_cycles;
} at_frame_t;

/* Validate (size, magic, trailer check word) and unpack.  Returns 0 if the packet is usable, -1 if it is malformed. */
int at_frame_parse(const void *packet, size_t bytes, at_frame_t *f);
