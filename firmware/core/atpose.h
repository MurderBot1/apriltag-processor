/* Camera pose from tag corner estimates.
 * Conventions (see tools/geom.py): world Z-up; tag frame x right / y up / z out of the face; corners TL,TR,BR,BL
 * as seen from the front; camera frame OpenCV (x right, y down, z forward); pixel centre of the top-left pixel = (0,0).
 * Output pose is camera->world:  p_w = R * p_c + t.                                                         */
#pragma once
#include <stdint.h>

#ifndef AT_REAL
#define AT_REAL float
#endif
typedef AT_REAL real_t;

#define AT_MAX_TAGS 64
#define AT_MAX_MEAS 16

typedef struct { real_t fx, fy, cx, cy, k1, k2, p1, p2, k3; } at_calib_t;

typedef struct {
    uint16_t id;
    real_t size;          /* edge length of the black square (m) */
    real_t pos[3];        /* tag centre in world (m) */
    real_t R[9];          /* tag->world rotation, row-major */
} at_tag_t;

typedef struct {
    at_calib_t cal;
    uint16_t ntags;
    at_tag_t tags[AT_MAX_TAGS];
} at_field_t;

typedef struct { uint16_t id; real_t c[4][2]; } at_meas_t;       /* pixel corners TL,TR,BR,BL */

enum { AT_FLAG_AMBIGUOUS = 1, AT_FLAG_OUTLIER_DROPPED = 2, AT_FLAG_SINGLE_TAG = 4 };

typedef struct {
    real_t R[9];          /* camera->world */
    real_t t[3];
    real_t rms_px;        /* reprojection rms (pixels) */
    uint8_t ntags;        /* tags used */
    uint8_t flags;
} at_pose_t;

/* returns 0 on success, <0 on failure (-1 no known tags, -2 degenerate, -3 no convergence / behind camera) */
int at_solve(const at_field_t *f, const at_meas_t *m, int n, at_pose_t *out);

/* helpers exposed for tests */
void at_undistort(const at_calib_t *c, real_t u, real_t v, real_t *x, real_t *y);
void at_rot_to_quat(const real_t R[9], real_t q[4]);          /* w,x,y,z */
void at_quat_to_rot(const real_t q[4], real_t R[9]);
const at_tag_t *at_find_tag(const at_field_t *f, uint16_t id);
