#include "atratio.h"

void at_ar_init(at_ar_t *s)
{
    s->ratio = 0; s->confirmed = 0; s->zeros = 0; s->goods = 0; s->lockout = 0; s->backoff = AT_AR_LOCK_MIN; s->switches = 0;
}

static void fail_trial(at_ar_t *s)
{
    s->ratio = 0; s->confirmed = 0; s->zeros = 0; s->goods = 0; s->lockout = s->backoff; s->switches++;
    s->backoff = (uint16_t)(s->backoff * 2 > AT_AR_LOCK_MAX ? AT_AR_LOCK_MAX : s->backoff * 2);
}

unsigned at_ar_step(at_ar_t *s, unsigned ntags, unsigned ccl_flags)
{
    if (s->lockout) s->lockout--;
    if (ntags) s->zeros = 0; else if (s->zeros < 0xFFFF) s->zeros++;
    if (s->ratio == 0) {
        if (s->zeros >= AT_AR_ZERO_FRAMES && !s->lockout) {
            s->ratio = 1; s->confirmed = 0; s->zeros = 0; s->goods = 0; s->switches++;
        }
        return s->ratio;
    }
    if (ccl_flags & AT_AR_FLAG_ROW_DROPPED) { fail_trial(s); return 0; }       /* the labeller is overloaded at ratio 1: back off */
    if (ntags) {
        if (s->goods < AT_AR_CONFIRM_FRAMES && ++s->goods >= AT_AR_CONFIRM_FRAMES) { s->confirmed = 1; s->backoff = AT_AR_LOCK_MIN; }
    } else if (s->zeros >= AT_AR_TRIAL_FRAMES) {
        if (s->confirmed) { s->ratio = 0; s->confirmed = 0; s->zeros = 0; s->goods = 0; s->switches++; }   /* scene gone: probe again soon */
        else fail_trial(s);
    }
    return s->ratio;
}
