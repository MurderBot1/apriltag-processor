#include "atframe.h"
#include <string.h>

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

/* ------------------------------------------------------------------------------------------ frame buffer pool */
void at_buf_init(at_bufpool_t *p, unsigned n)
{
    memset(p, 0, sizeof *p);
    p->n = (uint8_t)(n > AT_BUF_MAX ? AT_BUF_MAX : n);
    p->held = -1;
}

int at_buf_claim(at_bufpool_t *p)
{
    for (int i = 0; i < p->n; i++)
        if (p->state[i] == AT_BUF_FREE) { p->state[i] = AT_BUF_FILLING; return i; }
    return -1;
}

void at_buf_complete(at_bufpool_t *p, int idx)
{
    if (idx < 0 || idx >= p->n || p->state[idx] != AT_BUF_FILLING) { p->lost_nobuf++; return; }
    p->order[idx] = ++p->arrivals;
    p->state[idx] = AT_BUF_READY;
    p->received++;
    uint32_t d = 0;
    for (int i = 0; i < p->n; i++) d += (p->state[i] == AT_BUF_READY || p->state[i] == AT_BUF_BUSY);
    if (d > p->max_depth) p->max_depth = d;
}

void at_buf_abort(at_bufpool_t *p, int idx)
{
    if (idx >= 0 && idx < p->n && p->state[idx] == AT_BUF_FILLING) p->state[idx] = AT_BUF_FREE;
    p->lost_abort++;
}

int at_buf_acquire(at_bufpool_t *p)
{
    if (p->held >= 0) return -1;
    int pick = -1;
    for (int i = 0; i < p->n; i++)
        if (p->state[i] == AT_BUF_READY && (pick < 0 || p->order[i] < p->order[pick])) pick = i;
    if (pick >= 0) { p->state[pick] = AT_BUF_BUSY; p->held = (int8_t)pick; }
    return pick;
}

void at_buf_release(at_bufpool_t *p)
{
    if (p->held >= 0) { p->state[p->held] = AT_BUF_FREE; p->held = -1; }
}

uint32_t at_buf_lost(const at_bufpool_t *p) { return p->lost_nobuf + p->lost_abort; }
