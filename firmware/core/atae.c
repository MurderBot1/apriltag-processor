#include "atae.h"

void at_ae_init(at_ae_t *ae, uint16_t exposure, uint8_t gain)
{
    ae->exposure = exposure < AT_AE_EXP_MIN ? AT_AE_EXP_MIN : exposure > AT_AE_EXP_MAX ? AT_AE_EXP_MAX : exposure;
    ae->gain = gain < AT_AE_GAIN_MIN ? AT_AE_GAIN_MIN : gain;
    ae->settle = AT_AE_SETTLE_FRAMES;
}

int at_ae_step(at_ae_t *ae, float mean)
{
    if (ae->settle) { ae->settle--; return 0; }
    float err = mean - (float)AT_AE_TARGET;
    if (err <= (float)AT_AE_DEADBAND && err >= -(float)AT_AE_DEADBAND) return 0;
    float ratio;
    if (mean >= 250.0f) ratio = AT_AE_STEP_DOWN_MIN;                   /* clipped: true brightness unknown, cut hard */
    else ratio = (float)AT_AE_TARGET / (mean < 1.0f ? 1.0f : mean);
    if (ratio > AT_AE_STEP_UP_MAX) ratio = AT_AE_STEP_UP_MAX;
    if (ratio < AT_AE_STEP_DOWN_MIN) ratio = AT_AE_STEP_DOWN_MIN;

    float total = (float)ae->exposure * (float)ae->gain / 16.0f * ratio;
    const float tmin = (float)AT_AE_EXP_MIN, tmax = (float)AT_AE_EXP_MAX * (float)AT_AE_GAIN_MAX / 16.0f;
    if (total < tmin) total = tmin;
    if (total > tmax) total = tmax;

    uint16_t e; uint8_t g;
    if (total <= (float)AT_AE_EXP_MAX) {
        e = (uint16_t)(total + 0.5f); g = AT_AE_GAIN_MIN;
    } else {
        e = AT_AE_EXP_MAX;
        float gv = total / (float)AT_AE_EXP_MAX * 16.0f + 0.5f;
        g = gv >= (float)AT_AE_GAIN_MAX ? AT_AE_GAIN_MAX : (uint8_t)gv;
    }
    if (e < AT_AE_EXP_MIN) e = AT_AE_EXP_MIN;
    if (e == ae->exposure && g == ae->gain) return 0;    /* at a limit or quantised to the same value */
    ae->exposure = e; ae->gain = g; ae->settle = AT_AE_SETTLE_FRAMES;
    return 1;
}
