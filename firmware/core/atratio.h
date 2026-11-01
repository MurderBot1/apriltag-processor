/* Automatic tile contrast-ratio selection (THRESH register field `ratio`, bits 31:30).  Pure function of per-frame feedback, no I/O.
 * Ratio 0 is the robust default (noisy frames); ratio 1 recovers low-contrast scenes (lowcon: 0 -> 66 / 66 tags) but turns flat noisy tiles
 * into contrasty ones, which overloads the labeller (CCL flag "row dropped").  Policy:
 *   ratio 0: AT_AR_ZERO_FRAMES frames in a row without any tag -> try ratio 1 (unless locked out)
 *   ratio 1: a frame with the row-dropped flag, or AT_AR_TRIAL_FRAMES frames in a row without a tag -> back to ratio 0 and lock the
 *            trial out for `backoff` frames (doubles at every failed trial up to AT_AR_LOCK_MAX); AT_AR_CONFIRM_FRAMES frames with tags
 *            at ratio 1 count as success and reset the backoff to AT_AR_LOCK_MIN. */
#pragma once
#include <stdint.h>

#define AT_AR_ZERO_FRAMES    3        /* tagless frames at ratio 0 before ratio 1 is tried */
#define AT_AR_TRIAL_FRAMES   6        /* tagless frames at ratio 1 before giving up */
#define AT_AR_CONFIRM_FRAMES 8        /* frames with tags at ratio 1 that end the "trial" state */
#define AT_AR_LOCK_MIN       32       /* frames a failed trial is locked out (0.27 s at 120 fps) */
#define AT_AR_LOCK_MAX       512
#define AT_AR_FLAG_ROW_DROPPED 1u     /* bit 0 of at_frame_t.ccl_flags (CCL register bit 8) */

typedef struct {
    uint8_t ratio;                    /* ratio the policy wants in the THRESH register (0 or 1) */
    uint8_t confirmed;                /* ratio 1 has produced AT_AR_CONFIRM_FRAMES frames with tags */
    uint16_t zeros;                   /* consecutive tagless frames */
    uint16_t goods;                   /* frames with tags at ratio 1 since the switch (saturates at AT_AR_CONFIRM_FRAMES) */
    uint16_t lockout;                 /* frames left before ratio 1 may be tried again */
    uint16_t backoff;                 /* lockout applied at the next failed trial */
    uint32_t switches;                /* number of ratio changes, for diagnostics */
} at_ar_t;

void at_ar_init(at_ar_t *s);
/* Feed one processed frame: tags found in it and its CCL flags.  Returns the ratio to use from now on (0 or 1). */
unsigned at_ar_step(at_ar_t *s, unsigned ntags, unsigned ccl_flags);
