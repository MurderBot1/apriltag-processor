#include "atpose.h"
#include <math.h>
#include <string.h>

#define MAXPTS (AT_MAX_MEAS * 4)

static void mat_mul(const real_t *a, const real_t *b, real_t *o)     /* 3x3 */
{
    real_t t[9];
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            t[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
    memcpy(o, t, sizeof t);
}
static void mat_vec(const real_t *a, const real_t *v, real_t *o)
{
    real_t t0 = a[0] * v[0] + a[1] * v[1] + a[2] * v[2];
    real_t t1 = a[3] * v[0] + a[4] * v[1] + a[5] * v[2];
    real_t t2 = a[6] * v[0] + a[7] * v[1] + a[8] * v[2];
    o[0] = t0; o[1] = t1; o[2] = t2;
}
static void cross3(const real_t *a, const real_t *b, real_t *o)
{
    real_t x = a[1] * b[2] - a[2] * b[1], y = a[2] * b[0] - a[0] * b[2], z = a[0] * b[1] - a[1] * b[0];
    o[0] = x; o[1] = y; o[2] = z;
}
static real_t dot3(const real_t *a, const real_t *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

static void orthonormalize(real_t *R)
{
    /* Gram-Schmidt on columns then a few polar iterations R <- 1.5 R - 0.5 R R^T R */
    real_t c0[3] = {R[0], R[3], R[6]}, c1[3] = {R[1], R[4], R[7]}, c2[3];
    real_t n = sqrt(dot3(c0, c0)); for (int i = 0; i < 3; i++) c0[i] /= n;
    real_t d = dot3(c0, c1); for (int i = 0; i < 3; i++) c1[i] -= d * c0[i];
    n = sqrt(dot3(c1, c1)); for (int i = 0; i < 3; i++) c1[i] /= n;
    cross3(c0, c1, c2);
    for (int i = 0; i < 3; i++) { R[i * 3] = c0[i]; R[i * 3 + 1] = c1[i]; R[i * 3 + 2] = c2[i]; }
}

/* rotation by rotation vector w (Rodrigues) */
static void rodrigues(const real_t w[3], real_t R[9])
{
    real_t th2 = dot3(w, w), th = sqrt(th2), a, b;
    if (th < (real_t)1e-6) { a = 1 - th2 / 6; b = (real_t)0.5 - th2 / 24; }
    else { a = sin(th) / th; b = (1 - cos(th)) / th2; }
    real_t K[9] = {0, -w[2], w[1], w[2], 0, -w[0], -w[1], w[0], 0};
    real_t K2[9]; mat_mul(K, K, K2);
    for (int i = 0; i < 9; i++) R[i] = (i % 4 == 0 ? 1 : 0) + a * K[i] + b * K2[i];
}

const at_tag_t *at_find_tag(const at_field_t *f, uint16_t id)
{
    for (int i = 0; i < f->ntags; i++) if (f->tags[i].id == id) return &f->tags[i];
    return 0;
}

void at_undistort(const at_calib_t *c, real_t u, real_t v, real_t *x, real_t *y)
{
    real_t xd = (u - c->cx) / c->fx, yd = (v - c->cy) / c->fy, xu = xd, yu = yd;
    for (int i = 0; i < 10; i++) {
        real_t r2 = xu * xu + yu * yu, rad = 1 + r2 * (c->k1 + r2 * (c->k2 + r2 * c->k3));
        real_t dx = 2 * c->p1 * xu * yu + c->p2 * (r2 + 2 * xu * xu);
        real_t dy = c->p1 * (r2 + 2 * yu * yu) + 2 * c->p2 * xu * yu;
        xu = (xd - dx) / rad; yu = (yd - dy) / rad;
    }
    *x = xu; *y = yu;
}

void at_quat_to_rot(const real_t q[4], real_t R[9])
{
    real_t w = q[0], x = q[1], y = q[2], z = q[3], n = sqrt(w * w + x * x + y * y + z * z);
    w /= n; x /= n; y /= n; z /= n;
    R[0] = 1 - 2 * (y * y + z * z); R[1] = 2 * (x * y - z * w);     R[2] = 2 * (x * z + y * w);
    R[3] = 2 * (x * y + z * w);     R[4] = 1 - 2 * (x * x + z * z); R[5] = 2 * (y * z - x * w);
    R[6] = 2 * (x * z - y * w);     R[7] = 2 * (y * z + x * w);     R[8] = 1 - 2 * (x * x + y * y);
}

void at_rot_to_quat(const real_t R[9], real_t q[4])
{
    real_t t = R[0] + R[4] + R[8], s;
    if (t > 0) { s = sqrt(t + 1) * 2; q[0] = s / 4; q[1] = (R[7] - R[5]) / s; q[2] = (R[2] - R[6]) / s; q[3] = (R[3] - R[1]) / s; }
    else if (R[0] > R[4] && R[0] > R[8]) { s = sqrt(1 + R[0] - R[4] - R[8]) * 2; q[0] = (R[7] - R[5]) / s; q[1] = s / 4; q[2] = (R[1] + R[3]) / s; q[3] = (R[2] + R[6]) / s; }
    else if (R[4] > R[8]) { s = sqrt(1 + R[4] - R[0] - R[8]) * 2; q[0] = (R[2] - R[6]) / s; q[1] = (R[1] + R[3]) / s; q[2] = s / 4; q[3] = (R[5] + R[7]) / s; }
    else { s = sqrt(1 + R[8] - R[0] - R[4]) * 2; q[0] = (R[3] - R[1]) / s; q[1] = (R[2] + R[6]) / s; q[2] = (R[5] + R[7]) / s; q[3] = s / 4; }
    if (q[0] < 0) for (int i = 0; i < 4; i++) q[i] = -q[i];
}

/* ------------------------------------------------------------------ problem data */
typedef struct {
    int n;
    real_t X[MAXPTS][3];      /* world points */
    real_t u[MAXPTS][2];      /* undistorted normalised image points */
    int tag_of[MAXPTS];       /* index into measurement list */
} prob_t;

/* solve A x = b (6x6, symmetric positive definite) by Cholesky; returns 0 on success */
static int chol6(real_t A[6][6], const real_t b[6], real_t x[6])
{
    real_t L[6][6] = {{0}};
    for (int i = 0; i < 6; i++)
        for (int j = 0; j <= i; j++) {
            real_t s = A[i][j];
            for (int k = 0; k < j; k++) s -= L[i][k] * L[j][k];
            if (i == j) { if (s <= 1e-18) return -1; L[i][i] = sqrt(s); }
            else L[i][j] = s / L[j][j];
        }
    real_t y[6];
    for (int i = 0; i < 6; i++) { real_t s = b[i]; for (int k = 0; k < i; k++) s -= L[i][k] * y[k]; y[i] = s / L[i][i]; }
    for (int i = 5; i >= 0; i--) { real_t s = y[i]; for (int k = i + 1; k < 6; k++) s -= L[k][i] * x[k]; x[i] = s / L[i][i]; }
    return 0;
}

/* cost = sum of squared normalised residuals; also reports min depth */
static real_t cost_of(const prob_t *p, const real_t R[9], const real_t t[3], real_t *minz)
{
    real_t c = 0, mz = 1e9;
    for (int i = 0; i < p->n; i++) {
        real_t P[3]; mat_vec(R, p->X[i], P); P[0] += t[0]; P[1] += t[1]; P[2] += t[2];
        if (P[2] < mz) mz = P[2];
        if (P[2] < (real_t)1e-4) { c += 1e6; continue; }
        real_t ex = P[0] / P[2] - p->u[i][0], ey = P[1] / P[2] - p->u[i][1];
        c += ex * ex + ey * ey;
    }
    if (minz) *minz = mz;
    return c;
}

/* Levenberg-Marquardt on (R_cw, t_cw) with left-multiplicative rotation updates */
static real_t refine(const prob_t *p, real_t R[9], real_t t[3])
{
    real_t lambda = (real_t)1e-4, cost = cost_of(p, R, t, 0);
    for (int it = 0; it < 40; it++) {
        real_t A[6][6] = {{0}}, g[6] = {0};
        for (int i = 0; i < p->n; i++) {
            real_t RX[3]; mat_vec(R, p->X[i], RX);
            real_t P[3] = {RX[0] + t[0], RX[1] + t[1], RX[2] + t[2]};
            if (P[2] < (real_t)1e-4) continue;
            real_t iz = 1 / P[2], x = P[0] * iz, y = P[1] * iz;
            real_t rx = x - p->u[i][0], ry = y - p->u[i][1];
            /* d(proj)/dP */
            real_t dp[2][3] = {{iz, 0, -x * iz}, {0, iz, -y * iz}};
            /* dP/d(w) = -[RX]x ; dP/dt = I */
            real_t M[3][6] = {{0, RX[2], -RX[1], 1, 0, 0}, {-RX[2], 0, RX[0], 0, 1, 0}, {RX[1], -RX[0], 0, 0, 0, 1}};
            real_t J[2][6];
            for (int r = 0; r < 2; r++)
                for (int c = 0; c < 6; c++) J[r][c] = dp[r][0] * M[0][c] + dp[r][1] * M[1][c] + dp[r][2] * M[2][c];
            for (int a = 0; a < 6; a++) {
                g[a] += J[0][a] * rx + J[1][a] * ry;
                for (int b = 0; b < 6; b++) A[a][b] += J[0][a] * J[0][b] + J[1][a] * J[1][b];
            }
        }
        int accepted = 0;
        for (int tries = 0; tries < 8 && !accepted; tries++) {
            real_t Al[6][6], dx[6], mg[6];
            memcpy(Al, A, sizeof A);
            for (int a = 0; a < 6; a++) { Al[a][a] += lambda * (A[a][a] + (real_t)1e-12); mg[a] = -g[a]; }
            if (chol6(Al, mg, dx)) { lambda *= 10; continue; }
            real_t dR[9], Rn[9], tn[3];
            rodrigues(dx, dR); mat_mul(dR, R, Rn);
            tn[0] = t[0] + dx[3]; tn[1] = t[1] + dx[4]; tn[2] = t[2] + dx[5];   /* P' = dR*(R X) + t + dt */
            real_t cn = cost_of(p, Rn, tn, 0);
            if (cn < cost) {
                memcpy(R, Rn, sizeof Rn); memcpy(t, tn, sizeof tn);
                real_t step = 0; for (int a = 0; a < 6; a++) step += dx[a] * dx[a];
                real_t dc = cost - cn; cost = cn; lambda *= (real_t)0.3; accepted = 1;
                if (step < (real_t)1e-18 || dc < (real_t)1e-16 * (1 + cost)) return cost;
            } else lambda *= 10;
        }
        if (!accepted) break;
    }
    return cost;
}

/* DLT homography of 4 correspondences (plane (X,Y) -> normalised image (x,y)), h33 = 1; gaussian elimination */
static int homography4(const real_t P[4][2], const real_t Q[4][2], real_t H[9])
{
    real_t A[8][9];
    for (int i = 0; i < 4; i++) {
        real_t X = P[i][0], Y = P[i][1], x = Q[i][0], y = Q[i][1];
        real_t r0[9] = {X, Y, 1, 0, 0, 0, -x * X, -x * Y, x}, r1[9] = {0, 0, 0, X, Y, 1, -y * X, -y * Y, y};
        memcpy(A[2 * i], r0, sizeof r0); memcpy(A[2 * i + 1], r1, sizeof r1);
    }
    for (int c = 0; c < 8; c++) {
        int piv = c; for (int r = c + 1; r < 8; r++) if (fabs(A[r][c]) > fabs(A[piv][c])) piv = r;
        if (fabs(A[piv][c]) < 1e-12) return -1;
        if (piv != c) for (int k = 0; k < 9; k++) { real_t t = A[c][k]; A[c][k] = A[piv][k]; A[piv][k] = t; }
        for (int r = 0; r < 8; r++) if (r != c) {
            real_t f = A[r][c] / A[c][c];
            for (int k = c; k < 9; k++) A[r][k] -= f * A[c][k];
        }
    }
    for (int i = 0; i < 8; i++) H[i] = A[i][8] / A[i][i];
    H[8] = 1;
    return 0;
}

static const real_t CORNER_SIGN[4][2] = {{-1, 1}, {1, 1}, {1, -1}, {-1, -1}};   /* TL TR BR BL in tag frame */

int at_solve(const at_field_t *f, const at_meas_t *m, int n, at_pose_t *out)
{
    static prob_t P;
    int tag_idx[AT_MAX_MEAS], nt = 0;
    P.n = 0;
    for (int k = 0; k < n && nt < AT_MAX_MEAS; k++) {
        const at_tag_t *tg = at_find_tag(f, m[k].id);
        if (!tg) continue;
        for (int c = 0; c < 4; c++) {
            real_t loc[3] = {CORNER_SIGN[c][0] * tg->size / 2, CORNER_SIGN[c][1] * tg->size / 2, 0};
            real_t w[3]; mat_vec(tg->R, loc, w);
            for (int i = 0; i < 3; i++) P.X[P.n][i] = w[i] + tg->pos[i];
            at_undistort(&f->cal, m[k].c[c][0], m[k].c[c][1], &P.u[P.n][0], &P.u[P.n][1]);
            P.tag_of[P.n] = nt; P.n++;
        }
        tag_idx[nt++] = k;
    }
    if (nt == 0) return -1;

    /* initial pose(s) from the homography of the tag with the largest image area */
    int best = 0; real_t bestA = -1;
    for (int t = 0; t < nt; t++) {
        real_t a = 0;
        for (int c = 0; c < 4; c++) {
            const real_t *p0 = P.u[t * 4 + c], *p1 = P.u[t * 4 + ((c + 1) & 3)];
            a += p0[0] * p1[1] - p1[0] * p0[1];
        }
        if (fabs(a) > bestA) { bestA = fabs(a); best = t; }
    }
    const at_tag_t *tg = at_find_tag(f, m[tag_idx[best]].id);
    real_t plane[4][2], img[4][2];
    for (int c = 0; c < 4; c++) {
        plane[c][0] = CORNER_SIGN[c][0] * tg->size / 2; plane[c][1] = CORNER_SIGN[c][1] * tg->size / 2;
        img[c][0] = P.u[best * 4 + c][0]; img[c][1] = P.u[best * 4 + c][1];
    }
    real_t H[9];
    if (homography4(plane, img, H)) return -2;
    real_t h1[3] = {H[0], H[3], H[6]}, h2[3] = {H[1], H[4], H[7]}, h3[3] = {H[2], H[5], H[8]};
    real_t lam = 2 / (sqrt(dot3(h1, h1)) + sqrt(dot3(h2, h2)));
    real_t Rct[9], tct[3], r3[3];
    real_t r1[3] = {h1[0] * lam, h1[1] * lam, h1[2] * lam}, r2[3] = {h2[0] * lam, h2[1] * lam, h2[2] * lam};
    for (int i = 0; i < 3; i++) tct[i] = h3[i] * lam;
    if (tct[2] < 0) { for (int i = 0; i < 3; i++) { r1[i] = -r1[i]; r2[i] = -r2[i]; tct[i] = -tct[i]; } }
    cross3(r1, r2, r3);
    for (int i = 0; i < 3; i++) { Rct[i * 3] = r1[i]; Rct[i * 3 + 1] = r2[i]; Rct[i * 3 + 2] = r3[i]; }
    orthonormalize(Rct);
    /* world->camera:  R_cw = R_ct R_wt^T ,  t_cw = t_ct - R_cw p_t */
    real_t Rcw[9], tcw[3], tmp[3];
    {
        real_t RwtT[9] = {tg->R[0], tg->R[3], tg->R[6], tg->R[1], tg->R[4], tg->R[7], tg->R[2], tg->R[5], tg->R[8]};
        mat_mul(Rct, RwtT, Rcw);
    }
    mat_vec(Rcw, tg->pos, tmp);
    for (int i = 0; i < 3; i++) tcw[i] = tct[i] - tmp[i];

    real_t R1[9], t1[3]; memcpy(R1, Rcw, sizeof R1); memcpy(t1, tcw, sizeof t1);
    real_t c1 = refine(&P, R1, t1);
    real_t Rb[9], tb[3], cb = c1; memcpy(Rb, R1, sizeof Rb); memcpy(tb, t1, sizeof tb);
    uint8_t flags = 0;
    if (nt == 1) {
        flags |= AT_FLAG_SINGLE_TAG;
        /* planar ambiguity: reflect the plane normal about the line of sight and re-optimise */
        real_t nw[3] = {tg->R[2], tg->R[5], tg->R[8]}, nc[3], ctr[3];
        mat_vec(R1, nw, nc); mat_vec(R1, tg->pos, ctr);
        for (int i = 0; i < 3; i++) ctr[i] += t1[i];
        real_t L = sqrt(dot3(ctr, ctr)); for (int i = 0; i < 3; i++) ctr[i] /= L;
        real_t d = dot3(nc, ctr), np[3];
        for (int i = 0; i < 3; i++) np[i] = 2 * d * ctr[i] - nc[i];
        real_t ax[3]; cross3(nc, np, ax);
        real_t s = sqrt(dot3(ax, ax)), cs = dot3(nc, np);
        if (s > (real_t)1e-6) {
            real_t ang = atan2(s, cs), w[3] = {ax[0] / s * ang, ax[1] / s * ang, ax[2] / s * ang}, dR[9], R2[9], t2[3];
            rodrigues(w, dR);
            /* rotate about the tag centre: R2 = dR R1 ; keep the tag centre fixed in camera space */
            mat_mul(dR, R1, R2);
            real_t c0[3]; mat_vec(R1, tg->pos, c0); for (int i = 0; i < 3; i++) c0[i] += t1[i];
            real_t c2[3]; mat_vec(R2, tg->pos, c2);
            for (int i = 0; i < 3; i++) t2[i] = c0[i] - c2[i];
            real_t c2cost = refine(&P, R2, t2);
            real_t mz; cost_of(&P, R2, t2, &mz);
            if (mz > 0 && c2cost < c1) { memcpy(Rb, R2, sizeof Rb); memcpy(tb, t2, sizeof tb); cb = c2cost; }
            if (fabs(sqrt(c2cost / P.n) - sqrt(c1 / P.n)) * f->cal.fx < 0.15) flags |= AT_FLAG_AMBIGUOUS;
        }
    }
    real_t mz; cost_of(&P, Rb, tb, &mz);
    if (mz <= 0) return -3;
    real_t rms = sqrt(cb / (2 * P.n)) * f->cal.fx;

    /* leave-one-out outlier rejection when several tags disagree */
    if (nt >= 3 && rms > 2.5f) {
        int worst = -1; real_t wc = 1e30; real_t Rw[9] = {0}, tw[3] = {0};
        for (int drop = 0; drop < nt; drop++) {
            static prob_t Q; Q.n = 0;
            for (int i = 0; i < P.n; i++) if (P.tag_of[i] != drop) { memcpy(Q.X[Q.n], P.X[i], sizeof Q.X[0]); memcpy(Q.u[Q.n], P.u[i], sizeof Q.u[0]); Q.tag_of[Q.n] = P.tag_of[i]; Q.n++; }
            real_t Rt[9], tt[3]; memcpy(Rt, Rb, sizeof Rt); memcpy(tt, tb, sizeof tt);
            real_t c = refine(&Q, Rt, tt);
            if (c / Q.n < wc) { wc = c / Q.n; worst = drop; memcpy(Rw, Rt, sizeof Rw); memcpy(tw, tt, sizeof tw); }
        }
        real_t r2 = sqrt(wc / 2) * f->cal.fx;
        if (worst >= 0 && r2 < rms * (real_t)0.5) { memcpy(Rb, Rw, sizeof Rb); memcpy(tb, tw, sizeof tb); rms = r2; flags |= AT_FLAG_OUTLIER_DROPPED; nt--; }
    }

    /* camera->world */
    real_t Rwc[9] = {Rb[0], Rb[3], Rb[6], Rb[1], Rb[4], Rb[7], Rb[2], Rb[5], Rb[8]}, twc[3];
    mat_vec(Rwc, tb, twc);
    memcpy(out->R, Rwc, sizeof Rwc);
    for (int i = 0; i < 3; i++) out->t[i] = -twc[i];
    out->rms_px = rms; out->ntags = (uint8_t)nt; out->flags = flags;
    return 0;
}
