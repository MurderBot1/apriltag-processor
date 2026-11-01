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

/* ------------------------------------------------------------------------------------------ frame buffer pool
 * Bookkeeping of the frame buffers of the receiver (plain C, no hardware: the RP2350 HAL uses it from its DMA / GPIO interrupts and from the main
 * loop, the PC tests drive it directly).  AT_NBUF buffers of AT_PKT_BYTES each; a buffer is FREE -> FILLING (the receiver claims it when a
 * packet starts) -> READY (packet complete) -> BUSY (held by the application; only one at a time) -> FREE.  Packets are handed out oldest first.
 * If no buffer is free when a packet starts the receiver sinks that packet and it is counted as lost (`lost_nobuf`); a packet that ends early
 * and is repaired by a resynchronisation is counted in `lost_abort`.  The caller must serialise calls (RP2350: interrupts disabled). */
#define AT_NBUF 3                       /* frame buffers in SRAM: 3 x 132,128 B = 396,384 B (see docs/architecture.md, results/frame_budget.md) */
#define AT_BUF_MAX 4

enum { AT_BUF_FREE = 0, AT_BUF_FILLING, AT_BUF_READY, AT_BUF_BUSY };

typedef struct {
    uint8_t n;                          /* buffers in use (<= AT_BUF_MAX) */
    uint8_t state[AT_BUF_MAX];
    int8_t held;                        /* buffer given to the application, -1 = none */
    uint32_t order[AT_BUF_MAX];         /* arrival number of a READY buffer */
    uint32_t arrivals;
    uint32_t lost_nobuf, lost_abort;    /* packets lost: no free buffer at the packet start / receiver resynchronisation */
    uint32_t received;                  /* packets stored completely */
    uint32_t max_depth;                 /* most packets ever waiting or in processing at once (READY + BUSY), a measure of the scheduling margin */
} at_bufpool_t;

void at_buf_init(at_bufpool_t *p, unsigned n);
int  at_buf_claim(at_bufpool_t *p);                    /* buffer for a packet that starts now (FREE -> FILLING), -1 if none is free */
void at_buf_complete(at_bufpool_t *p, int idx);        /* packet complete: idx = claimed buffer (-> READY) or -1 = it went to the sink (lost) */
void at_buf_abort(at_bufpool_t *p, int idx);           /* packet repaired by resync: idx (or -1) is freed again, counted as lost */
int  at_buf_acquire(at_bufpool_t *p);                  /* oldest READY buffer -> BUSY, -1 if none or one is already held */
void at_buf_release(at_bufpool_t *p);                  /* held buffer -> FREE */
uint32_t at_buf_lost(const at_bufpool_t *p);           /* lost_nobuf + lost_abort */

/* Validate (size, magic, trailer check word) and unpack.  Returns 0 if the packet is usable, -1 if it is malformed. */
int at_frame_parse(const void *packet, size_t bytes, at_frame_t *f);
