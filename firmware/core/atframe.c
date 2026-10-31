#include "atframe.h"

int at_frame_parse(const void *packet, size_t bytes, at_frame_t *f)
{
    if (!packet || bytes != AT_PKT_BYTES) return -1;
    const uint32_t *w = (const uint32_t *)packet;
    const uint32_t *t = w + AT_PKT_HDR_WORDS + AT_PKT_MASK_WORDS;
    if (w[0] != AT_PKT_MAGIC || t[3] != ~w[1]) return -1;
    uint32_t cnt = (t[0] >> 16) & 0xFFu;
    if (cnt > ATTPU_MAX_CAND) return -1;
    f->seq = w[1];
    f->ts = (uint64_t)w[2] | ((uint64_t)w[3] << 32);
    f->mask = w + AT_PKT_HDR_WORDS;
    f->cand = t + AT_PKT_TRL_WORDS;
    f->cand_count = cnt;
    f->ccl_flags = (t[0] >> 8) & 15u;
    f->status = t[0] & 0xFFu;
    f->frame_sum = t[1];
    f->max_row_cycles = t[2] & 0xFFFFu;
    return 0;
}
