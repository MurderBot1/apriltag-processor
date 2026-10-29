/* Auto exposure / gain controller.  Pure function of (mean brightness, current exposure, current gain): no I/O.
 * Model: image brightness ~ exposure * gain.  The controller works on "total" = exposure * gain/16 (in sensor lines at 1x),
 * moves it towards target/mean with a bounded ratio per step, ignores frames while a previous change is still in flight,
 * and does nothing inside a deadband.  Exposure is preferred up to AT_AE_EXP_MAX lines, gain is used beyond that. */
#pragma once
#include <stdint.h>

#define AT_AE_TARGET        110      /* target mean (0..255); tag scenes are white dominated */
#define AT_AE_DEADBAND      12       /* |mean - target| <= deadband -> no change */
#define AT_AE_EXP_MIN       8
#define AT_AE_EXP_MAX       400
#define AT_AE_GAIN_MIN      0x10     /* 1x */
#define AT_AE_GAIN_MAX      0xFF
#define AT_AE_STEP_UP_MAX   4.0f     /* max total multiplier per step */
#define AT_AE_STEP_DOWN_MIN 0.25f    /* min total multiplier per step */
#define AT_AE_SETTLE_FRAMES 1        /* frames to ignore after a change (sensor/pipeline latency) */
#define AT_AE_INIT_EXPOSURE 100
#define AT_AE_INIT_GAIN     0x10

typedef struct { uint16_t exposure; uint8_t gain; uint8_t settle; } at_ae_t;

void at_ae_init(at_ae_t *ae, uint16_t exposure, uint8_t gain);
/* feed one frame's mean (0..255).  Returns 1 and updates ae->exposure/gain when the sensor must be rewritten. */
int  at_ae_step(at_ae_t *ae, float mean);
