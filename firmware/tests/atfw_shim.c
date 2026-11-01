/* Test-only helpers exported from libatfw: opaque app allocation and statistics access. */
#include "../core/atapp.h"
#include <stdlib.h>

size_t atfw_sizeof_app(void) { return sizeof(at_app_t); }
at_app_t *atfw_app_new(void) { return (at_app_t *)calloc(1, sizeof(at_app_t)); }
void atfw_app_free(at_app_t *a) { free(a); }
/* out[0..15]: solved, solve_fail, torn_reads, tx_msgs, frame_id, store_seq, ae_updates, nobs, pose_valid,
 *             ae_exposure, ae_gain, ae_enabled, streaming, ntags, divider, rx_bad_frames */
void atfw_stats(const at_app_t *a, uint32_t *o)
{
    o[0] = a->solved; o[1] = a->solve_fail; o[2] = a->torn_reads; o[3] = a->tx_msgs; o[4] = a->frame_id; o[5] = a->store_seq;
    o[6] = a->ae_updates; o[7] = (uint32_t)a->nobs; o[8] = (uint32_t)a->pose_valid; o[9] = a->ae.exposure; o[10] = a->ae.gain;
    o[11] = a->ae_enabled; o[12] = a->streaming; o[13] = a->field.ntags; o[14] = a->divider; o[15] = a->rx.bad_frames;
}
uint32_t atfw_rx_max_depth(const at_app_t *a) { return a->rx_max_depth; }
uint32_t atfw_rx_lost(const at_app_t *a) { return a->rx_lost; }
/* frame buffer pool, for the scheduling tests */
at_bufpool_t *atfw_pool_new(unsigned n) { at_bufpool_t *p = (at_bufpool_t *)calloc(1, sizeof *p); at_buf_init(p, n); return p; }
void atfw_pool_free(at_bufpool_t *p) { free(p); }
unsigned atfw_pool_state(const at_bufpool_t *p, unsigned i) { return p->state[i]; }
float atfw_ae_mean(const at_app_t *a) { return a->ae_mean; }
