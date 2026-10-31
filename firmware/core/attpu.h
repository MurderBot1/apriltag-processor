/* Tag processing unit in C.
 *
 * Bit-exact port of the program that used to be baked into the FPGA's TPU (tools/tpu_prog.py, golden model
 * tools/tpu_isa.py): candidate components + the binary frame -> decoded tag36h11 tags with sub-pixel corners.
 * Integer only (no FPU, no libgcc, no libc), so the same file runs on the RP2350 (Cortex-M33) and, for the tests, on a PC.
 *
 * Inputs (the layout the FPGA streams, see docs/fpga.md):
 *   fb    binary frame, 800 rows x 40 words, bit (x % 32) of word y*40 + x/32 is pixel (x, y); 1 = black
 *   cand  candidate records of the CCL unit, 16 words each (rtl/run_ccl.v)
 * Output: up to ATTPU_MAX_TAGS tags in the same order and with the same field values as the old result RAM.
 */
#pragma once
#include <stdint.h>

#define ATTPU_W 1280
#define ATTPU_H 800
#define ATTPU_FB_WORDS 32000u          /* 800 * 40 */
#define ATTPU_MAX_CAND 64
#define ATTPU_CAND_REC_WORDS 16
#define ATTPU_MAX_TAGS 31
#define ATTPU_NCODES 587
#define ATTPU_FAST_MAXHAM 2            /* bucket-indexed matcher covers maxham <= 2; larger values fall back to a full scan */

typedef struct {
    uint16_t id;
    uint8_t ham;                       /* bit errors of the 36 data bits */
    uint8_t rot;                       /* rotation (0..3) of the sampled grid that matched */
    int32_t c[8];                      /* corners TL,TR,BR,BL as (x,y) Q16.16 pixels, pixel centre of pixel (0,0) = (0,0) */
    uint32_t label;                    /* CCL label of the candidate */
    uint32_t area;                     /* component area (pixels) */
    uint32_t frame;                    /* frame id passed to attpu_run */
    uint32_t quad_area;                /* area of the coarse quad (pixels^2) */
} attpu_tag_t;

/* Build the tag lookup tables (587 codes x 4 rotations).  Call once before attpu_run (takes about a hundred microseconds). */
void attpu_init(void);

/* Run the TPU program.  `maxham` is the match threshold (the FPGA register THRESH[29:24], default 2).
 * Returns the number of tags written to out[] (at most ATTPU_MAX_TAGS). */
int attpu_run(const uint32_t *fb, const uint32_t *cand, unsigned cand_count, uint32_t frame_id, unsigned maxham, attpu_tag_t *out);

/* Fixed-point primitives of the TPU ISA, exported for the unit tests. */
int32_t attpu_divq(int32_t a, int32_t b);                  /* trunc((int64(a) << 16) / b), b == 0 -> +-0x7FFFFFFF, low 32 bits */
int32_t attpu_muls(int32_t a, int32_t b, unsigned sh);     /* (int64(a) * int64(b)) >> sh, low 32 bits */
/* Tag matcher: input 36-bit code, returns the old TAGMATCH result word (rot<<10 | id | ham<<12) or -1 */
int32_t attpu_match(uint32_t lo, uint32_t hi4, unsigned maxham);
/* Pack the tags like the old result RAM image: out[0] = count, record i at 16 + 16 i (w0 = 0x80000000 | ..., w1..w8 corners,
 * w9 label, w10 area, w11 frame, w12 quad area).  `words` must have 16 + 16 * n entries. */
void attpu_pack_results(const attpu_tag_t *tags, int n, uint32_t *words);
