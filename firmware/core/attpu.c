/* Tag processing unit in C - bit-exact port of tools/tpu_prog.py (see attpu.h).
 *
 * Every arithmetic helper below mirrors one TPU ISA primitive exactly (tools/tpu_isa.py): 32-bit wrap-around integers, MULS = 64-bit
 * product with arithmetic shift, DIVQ = (|a| << 16) / |b| with the sign applied afterwards.  The control flow follows the assembly
 * program routine by routine (load_cand / coarse / refine / decode / emit); the comments name the TPU registers' roles.
 * Differences that do not change any result: scratch RAM words become local arrays, the tag matcher uses a bucket index instead of
 * scanning all 587 x 4 codes (same winner, see attpu_match), and the long division uses the CPU's 32-bit divider. */
#include "attpu.h"
#include "tag36h11_codes.h"

#ifndef ATTPU_FAST
#define ATTPU_FAST                      /* the RP2350 build puts the hot functions into SRAM (see firmware/rp2350/CMakeLists.txt) */
#endif

typedef int32_t s32;
typedef uint32_t u32;
typedef uint64_t u64;

/* ----------------------------------------------------------------------------- ISA primitives */
static inline s32 mul32(s32 a, s32 b) { return (s32)((u32)a * (u32)b); }
static inline s32 add32(s32 a, s32 b) { return (s32)((u32)a + (u32)b); }
static inline s32 sub32(s32 a, s32 b) { return (s32)((u32)a - (u32)b); }
static inline s32 abs32(s32 a) { return a < 0 ? (s32)(0u - (u32)a) : a; }
static inline s32 shl32(s32 a, unsigned n) { return (s32)((u32)a << n); }

int32_t attpu_muls(int32_t a, int32_t b, unsigned sh) { return (s32)(u32)(u64)(((int64_t)a * (int64_t)b) >> sh); }
static inline s32 muls16(s32 a, s32 b) { return (s32)(u32)(u64)(((int64_t)a * (int64_t)b) >> 16); }
static inline s32 muls12(s32 a, s32 b) { return (s32)(u32)(u64)(((int64_t)a * (int64_t)b) >> 12); }
static inline s32 muls24(s32 a, s32 b) { return (s32)(u32)(u64)(((int64_t)a * (int64_t)b) >> 24); }

/* (u1:u0) / v for u1 < v, v != 0 (Hacker's Delight divlu: two 32/16-bit steps on the hardware divider) */
static u32 divlu(u32 u1, u32 u0, u32 v)
{
    const u32 b = 65536u;
    int s = __builtin_clz(v);
    v <<= s;
    u32 vn1 = v >> 16, vn0 = v & 0xFFFFu;
    u32 un32 = s ? (u1 << s) | (u0 >> (32 - s)) : u1;
    u32 un10 = u0 << s;
    u32 un1 = un10 >> 16, un0 = un10 & 0xFFFFu;
    u32 q1 = un32 / vn1, rhat = un32 - q1 * vn1;
    while (q1 >= b || q1 * vn0 > b * rhat + un1) { q1--; rhat += vn1; if (rhat >= b) break; }
    u32 un21 = un32 * b + un1 - q1 * v;
    u32 q0 = un21 / vn1; rhat = un21 - q0 * vn1;
    while (q0 >= b || q0 * vn0 > b * rhat + un0) { q0--; rhat += vn1; if (rhat >= b) break; }
    return q1 * b + q0;
}

/* floor((ua << 16) / ub), ub != 0, result up to 47 bits */
static u64 udiv_q16(u32 ua, u32 ub)
{
    if (ua < 65536u) return (ua << 16) / ub;                         /* the common small case: one hardware divide */
    u32 hi = ua >> 16, lo = ua << 16;
    u32 qhi = 0;
    if (hi >= ub) { qhi = hi / ub; hi -= qhi * ub; }                 /* only when ub < 2^16 */
    return ((u64)qhi << 32) | divlu(hi, lo, ub);
}

int32_t attpu_divq(int32_t a, int32_t b)
{
    if (b == 0) return a >= 0 ? 0x7FFFFFFF : -0x7FFFFFFF;
    u32 ua = a < 0 ? 0u - (u32)a : (u32)a, ub = b < 0 ? 0u - (u32)b : (u32)b;
    u64 q = udiv_q16(ua, ub);
    if ((a < 0) != (b < 0)) q = 0 - q;
    return (s32)(u32)q;
}
#define divq attpu_divq

static inline s32 pix(const u32 *fb, s32 x, s32 y)
{
    if ((u32)x >= (u32)ATTPU_W || (u32)y >= (u32)ATTPU_H) return 0;
    return (s32)((fb[(u32)y * 40u + ((u32)x >> 5)] >> ((u32)x & 31u)) & 1u);
}

/* ----------------------------------------------------------------------------- tag matcher */
static u64 g_key[ATTPU_NCODES][4];                    /* codes rotated so that hamming(key[i][k], x) == hamming(codes[i], rot^k(x)) */
static uint16_t g_head[3][4097];                      /* bucket offsets per 12-bit chunk of the 36-bit code */
static uint16_t g_ids[3][ATTPU_NCODES * 4];           /* entry = i * 4 + k */
static int g_ready;

static u64 rot6(u64 code)                             /* rotate the 6x6 grid by 90 degrees clockwise (tools/tpu_isa.py rot6) */
{
    u64 v = 0;
    for (int r = 0; r < 6; r++)
        for (int c = 0; c < 6; c++) v = (v << 1) | ((code >> (35 - (6 * (5 - c) + r))) & 1u);
    return v;
}

static inline unsigned popcnt64(u64 v)
{
    u32 a = (u32)v, b = (u32)(v >> 32);
    a = a - ((a >> 1) & 0x55555555u); a = (a & 0x33333333u) + ((a >> 2) & 0x33333333u); a = (a + (a >> 4)) & 0x0F0F0F0Fu;
    b = b - ((b >> 1) & 0x55555555u); b = (b & 0x33333333u) + ((b >> 2) & 0x33333333u); b = (b + (b >> 4)) & 0x0F0F0F0Fu;
    return ((a + b) * 0x01010101u) >> 24;                              /* sum of both byte-wise counts <= 36 fits a byte */
}

void attpu_init(void)
{
    for (int i = 0; i < ATTPU_NCODES; i++) {
        u64 c = tag36h11_codes[i];
        u64 r[4] = {c, 0, 0, 0};
        for (int k = 1; k < 4; k++) r[k] = rot6(r[k - 1]);
        for (int k = 0; k < 4; k++) g_key[i][k] = r[(4 - k) & 3];     /* rot^-k(code) */
    }
    for (int j = 0; j < 3; j++) {
        static uint16_t cnt[4097];
        for (int q = 0; q <= 4096; q++) cnt[q] = 0;
        for (int e = 0; e < ATTPU_NCODES * 4; e++) cnt[((g_key[e >> 2][e & 3] >> (12 * j)) & 0xFFF) + 1]++;
        for (int q = 0; q < 4096; q++) cnt[q + 1] = (uint16_t)(cnt[q + 1] + cnt[q]);
        for (int q = 0; q <= 4096; q++) g_head[j][q] = cnt[q];
        for (int e = 0; e < ATTPU_NCODES * 4; e++) {
            unsigned key = (unsigned)((g_key[e >> 2][e & 3] >> (12 * j)) & 0xFFF);
            g_ids[j][cnt[key]++] = (uint16_t)e;
        }
    }
    g_ready = 1;
}

/* TAGMATCH: lowest hamming distance over (code i, rotation k), ties to the lowest i, then k - the old hardware scan order.  Valid
 * only if that distance is <= maxham.  Any code within maxham <= 2 bit errors of the input agrees with it on at least one of the
 * three 12-bit chunks, so scanning those three buckets finds every candidate and the same winner as a full scan. */
ATTPU_FAST int32_t attpu_match(uint32_t lo, uint32_t hi4, unsigned maxham)
{
    u64 x = ((u64)(hi4 & 0xFu) << 32) | lo;
    unsigned best_h = 99, best_e = 0;
    if (maxham <= ATTPU_FAST_MAXHAM) {
        for (int j = 0; j < 3; j++) {
            unsigned key = (unsigned)((x >> (12 * j)) & 0xFFF);
            for (unsigned p = g_head[j][key]; p < g_head[j][key + 1]; p++) {
                unsigned e = g_ids[j][p];
                unsigned h = popcnt64(x ^ g_key[e >> 2][e & 3]);
                if (h < best_h || (h == best_h && e < best_e)) { best_h = h; best_e = e; }
            }
        }
    } else {
        u64 rots[4] = {x, 0, 0, 0};
        for (int k = 1; k < 4; k++) rots[k] = rot6(rots[k - 1]);
        for (unsigned i = 0; i < ATTPU_NCODES; i++)
            for (unsigned k = 0; k < 4; k++) {
                unsigned h = popcnt64(tag36h11_codes[i] ^ rots[k]);
                if (h < best_h) { best_h = h; best_e = i * 4 + k; }
            }
    }
    if (best_h > maxham) return -1;
    return (s32)((best_e & 3) << 10 | (best_e >> 2) | (best_h << 12));
}

/* ----------------------------------------------------------------------------- the program */
typedef struct {
    s32 pts[16];      /* PTS: 8 extreme points (x, y) in pixels */
    s32 cc[8];        /* CC: coarse quad, Q16 */
    s32 rc[8];        /* RC: refined corners, Q16 */
    s32 ln[16];       /* LN: 4 lines (a, b, c) with a x + b y = c, Q16 */
    s32 cinfo[8];     /* 0 area, 1 label, 2 width, 3 height, 4 quad area */
} tpu_t;

static void load_cand(tpu_t *t, const u32 *c)
{
    t->cinfo[0] = (s32)c[0];
    t->cinfo[1] = (s32)c[9];
    u32 w10 = c[10], w11 = c[11];
    t->cinfo[2] = (s32)((w10 >> 16) - (w10 & 0xFFFFu) + 1u);
    t->cinfo[3] = (s32)((w11 >> 16) - (w11 & 0xFFFFu) + 1u);
    for (int k = 0; k < 8; k++) {
        u32 w = c[1 + k];
        s32 sc = (s32)(int16_t)(w & 0xFFFFu), aux = (s32)((w >> 16) & 0x7FFu), x, y;
        switch (k) {
        case 0: x = sc; y = aux; break;
        case 1: x = -sc; y = aux; break;
        case 2: x = aux; y = sc; break;
        case 3: x = aux; y = -sc; break;
        case 4: x = aux; y = sc - aux; break;
        case 5: x = aux; y = -sc - aux; break;
        case 6: x = aux; y = aux - sc; break;
        default: x = aux; y = sc + aux; break;
        }
        t->pts[2 * k] = x; t->pts[2 * k + 1] = y;
    }
}

/* clockwise order E,SE,S,SW,W,NW,N,NE = dirs 0,4,2,7,1,5,3,6; set A = E,S,W,N; set B = SE,SW,NW,NE.  Returns 1 if the quad is plausible. */
static s32 shoelace(const s32 *p, const int *ks)
{
    s32 res = 0;
    for (int i = 0; i < 4; i++) {
        int k0 = ks[i], k1 = ks[(i + 1) & 3];
        s32 x0 = p[2 * k0], y0 = p[2 * k0 + 1], x1 = p[2 * k1], y1 = p[2 * k1 + 1];
        res = add32(res, sub32(mul32(x0, y1), mul32(x1, y0)));
    }
    return res;
}

static int coarse(tpu_t *t)
{
    static const int setA[4] = {0, 2, 1, 3}, setB[4] = {4, 7, 5, 6};
    s32 a2 = shoelace(t->pts, setA), b2 = shoelace(t->pts, setB);
    const int *ks = setA;
    if (!(a2 >= b2)) { ks = setB; a2 = b2; }
    s32 quad = a2 >> 1;
    if (quad < 80) return 0;                                         /* MIN_QUAD_AREA */
    s32 comp = t->cinfo[0];
    if (shl32(comp, 2) < quad) return 0;                             /* component area < 25 % of the quad */
    if (mul32(quad, 11) < mul32(comp, 10)) return 0;                 /* component area > 1.1 x quad area */
    t->cinfo[4] = quad;
    for (int i = 0; i < 4; i++) {
        t->cc[2 * i] = shl32(t->pts[2 * ks[i]], 16);
        t->cc[2 * i + 1] = shl32(t->pts[2 * ks[i] + 1], 16);
    }
    return 1;
}

/* refine: src = 4 corners (Q16 x,y), K = search half-width in pixels; result in t->rc.  Per side: sample 16 positions along the
 * edge, scan 2K+1 pixels across for the black/white transition, least-squares fit of the offsets, then intersect adjacent lines. */
ATTPU_FAST static int refine(tpu_t *t, const s32 *src, s32 K, const u32 *fb)
{
    for (int side = 0; side < 4; side++) {
        s32 xa = src[2 * side], ya = src[2 * side + 1];
        int nx = (side + 1) & 3;
        s32 xb = src[2 * nx], yb = src[2 * nx + 1];
        s32 dx = sub32(xb, xa), dy = sub32(yb, ya);
        s32 aS, aE, cS, dAlong, dCross, so;
        int v;
        if (!(abs32(dx) >= abs32(dy))) {                             /* vertical-ish edge: along = y, cross = x */
            aS = ya; aE = yb; cS = xa; dAlong = dy; dCross = dx; v = 1;
            so = (0 >= dy) ? -1 : 1;
        } else {
            aS = xa; aE = xb; cS = ya; dAlong = dx; dCross = dy; v = 0;
            so = (dx < 0) ? 1 : -1;
        }
        if (dAlong == 0) return 0;
        s32 m = divq(dCross, dAlong);                                /* slope, Q16 */
        if (abs32(m) >= 0x20000) return 0;                           /* |m| >= 2.0 -> degenerate */
        s32 tm = add32(add32(aS, aE) >> 1, 0x8000) >> 16 ;
        s32 n = 0, St = 0, Stt = 0, Sd = 0, Std = 0;
        for (int j = 0; j < 16; j++) {
            s32 u = add32(mul32(2 * j + 1, 1638), 6554);
            s32 tq = add32(muls16(u, dAlong), aS);
            s32 tt = add32(tq, 0x8000) >> 16;                        /* integer position along the edge */
            s32 yc = add32(muls16(sub32(shl32(tt, 16), aS), m), cS); /* chord position across, Q16 */
            s32 c0 = add32(add32(yc, 0x8000) >> 16, mul32(so, K));
            s32 i = 0, cnt = 2 * K + 1, found = 0;
            if (v) {                                                 /* x = c0 scans along row tt */
                if ((u32)tt < (u32)ATTPU_H) {
                    const u32 *row = fb + (u32)tt * 40u;
                    do {
                        if ((u32)c0 < (u32)ATTPU_W && ((row[(u32)c0 >> 5] >> ((u32)c0 & 31u)) & 1u)) { found = 1; break; }
                        i++; c0 = sub32(c0, so);
                    } while (i < cnt);
                }
            } else {                                                 /* y = c0 scans down column tt */
                if ((u32)tt < (u32)ATTPU_W) {
                    const u32 *col = fb + ((u32)tt >> 5);
                    unsigned sh = (u32)tt & 31u;
                    do {
                        if ((u32)c0 < (u32)ATTPU_H && ((col[(u32)c0 * 40u] >> sh) & 1u)) { found = 1; break; }
                        i++; c0 = sub32(c0, so);
                    } while (i < cnt);
                }
            }
            if (!found || i == 0) continue;                          /* black at the outermost pixel: invalid */
            s32 edge = add32(shl32(c0, 4), shl32(so, 3));
            s32 d = sub32(edge, yc >> 12);                           /* Q4 offset of the edge from the chord */
            s32 tc = sub32(tt, tm);
            n++; St = add32(St, tc); Stt = add32(Stt, mul32(tc, tc));
            Sd = add32(Sd, d); Std = add32(Std, mul32(tc, d));
        }
        if (n < 6) return 0;
        s32 den = sub32(mul32(n, Stt), mul32(St, St));
        if (0 >= den) return 0;
        s32 num = sub32(mul32(n, Std), mul32(St, Sd));
        s32 a = divq(num, den) >> 4;
        s32 b = divq(sub32(Sd, muls12(a, St)), n) >> 4;
        s32 M = add32(m, a);
        s32 Cc = sub32(cS, muls16(m, aS));
        Cc = sub32(Cc, mul32(a, tm)); Cc = add32(Cc, b);
        s32 *l = &t->ln[4 * side];
        if (!v) { l[0] = sub32(0, M); l[1] = 0x10000; l[2] = Cc; }   /* -M x + y = Cc */
        else    { l[0] = 0x10000; l[1] = sub32(0, M); l[2] = Cc; }   /* x - M y = Cc */
    }
    for (int i = 0; i < 4; i++) {
        const s32 *l1 = &t->ln[4 * ((i + 3) & 3)], *l2 = &t->ln[4 * i];
        s32 A1 = l1[0], B1 = l1[1], C1 = l1[2], A2 = l2[0], B2 = l2[1], C2 = l2[2];
        s32 det = sub32(muls16(A1, B2), muls16(A2, B1));
        if (abs32(det) < 3277) return 0;
        s32 xn = sub32(muls16(C1, B2), muls16(C2, B1));
        s32 yn = sub32(muls16(A1, C2), muls16(A2, C1));
        t->rc[2 * i] = divq(xn, det);
        t->rc[2 * i + 1] = divq(yn, det);
    }
    return 1;
}

/* decode: homography unit square -> refined quad, sample the 6x6 cells, match.  Returns the match word or -1. */
ATTPU_FAST static s32 decode(const tpu_t *t, const u32 *fb, unsigned maxham)
{
    const s32 *rc = t->rc;
    s32 x0 = rc[0], y0 = rc[1], x1 = rc[2], y1 = rc[3], x2 = rc[4], y2 = rc[5], x3 = rc[6], y3 = rc[7];
    s32 dx1 = sub32(x1, x2), dx2 = sub32(x3, x2), dx3 = add32(sub32(x0, x1), sub32(x2, x3));
    s32 dy1 = sub32(y1, y2), dy2 = sub32(y3, y2), dy3 = add32(sub32(y0, y1), sub32(y2, y3));
    s32 D = sub32(muls24(dx1, dy2), muls24(dx2, dy1));
    if (abs32(D) < 4096) return -1;
    s32 ng = sub32(muls24(dx3, dy2), muls24(dx2, dy3));
    s32 nh = sub32(muls24(dx1, dy3), muls24(dx3, dy1));
    s32 g = divq(ng, D), h = divq(nh, D);
    s32 a = add32(sub32(x1, x0), muls16(g, x1));
    s32 b = add32(sub32(x3, x0), muls16(h, x3));
    s32 d = add32(sub32(y1, y0), muls16(g, y1));
    s32 e = add32(sub32(y3, y0), muls16(h, y3));
    u32 lo = 0, hi = 0;
    for (int row = 0; row < 6; row++) {
        s32 v = (s32)((u32)(2 * row + 3) << 12);
        for (int col = 0; col < 6; col++) {
            s32 u = (s32)((u32)(2 * col + 3) << 12);
            s32 w = add32(add32(muls16(g, u), muls16(h, v)), 0x10000);
            s32 xn = add32(add32(muls16(a, u), muls16(b, v)), x0);
            s32 yn = add32(add32(muls16(d, u), muls16(e, v)), y0);
            s32 X = add32(divq(xn, w), 0x8000) >> 16, Y = add32(divq(yn, w), 0x8000) >> 16;
            u32 bit = (u32)(1 - pix(fb, X, Y));                      /* data bit: white = 1 */
            hi = (hi << 1) | (lo >> 31);
            lo = (lo << 1) | bit;
        }
    }
    return attpu_match(lo, hi & 15u, maxham);
}

ATTPU_FAST int attpu_run(const uint32_t *fb, const uint32_t *cand, unsigned cand_count, uint32_t frame_id, unsigned maxham, attpu_tag_t *out)
{
    tpu_t t;
    int tags = 0;
    if (!g_ready) attpu_init();
    if (cand_count > ATTPU_MAX_CAND) cand_count = ATTPU_MAX_CAND;     /* the CCL table holds 64 records */
    for (unsigned ci = 0; ci < cand_count; ci++) {
        load_cand(&t, cand + ci * ATTPU_CAND_REC_WORDS);
        if (!coarse(&t)) continue;
        s32 K = (t.cinfo[2] > t.cinfo[3] ? t.cinfo[2] : t.cinfo[3]) >> 4;
        if (K < 3) K = 3;
        if (K > 8) K = 8;
        if (!refine(&t, t.cc, K, fb)) continue;
        if (!refine(&t, t.rc, 3, fb)) continue;
        s32 m = decode(&t, fb, maxham);
        if (m == -1) continue;
        attpu_tag_t *o = &out[tags];
        unsigned rot = ((u32)m >> 10) & 3;
        o->id = (uint16_t)((u32)m & 0x3FFu); o->rot = (uint8_t)rot; o->ham = (uint8_t)(((u32)m >> 12) & 63u);
        for (unsigned i = 0; i < 4; i++) {                           /* rotate so corner 0 is the tag's top-left */
            unsigned src = (i - rot) & 3;
            o->c[2 * i] = t.rc[2 * src]; o->c[2 * i + 1] = t.rc[2 * src + 1];
        }
        o->label = (u32)t.cinfo[1]; o->area = (u32)t.cinfo[0]; o->frame = frame_id; o->quad_area = (u32)t.cinfo[4];
        if (++tags >= ATTPU_MAX_TAGS) break;
    }
    return tags;
}

void attpu_pack_results(const attpu_tag_t *tags, int n, uint32_t *w)
{
    w[0] = (uint32_t)n;
    for (int i = 0; i < n; i++) {
        uint32_t *r = w + 16 + 16 * i;
        for (int k = 0; k < 16; k++) r[k] = 0;
        r[0] = 0x80000000u | ((u32)tags[i].ham << 12) | ((u32)tags[i].rot << 10) | tags[i].id;
        for (int k = 0; k < 8; k++) r[1 + k] = (u32)tags[i].c[k];
        r[9] = tags[i].label; r[10] = tags[i].area; r[11] = tags[i].frame; r[12] = tags[i].quad_area;
    }
}
