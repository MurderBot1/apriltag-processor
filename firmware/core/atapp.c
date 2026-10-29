#include "atapp.h"
#include <string.h>
#include <math.h>

/* ----------------------------------------------------------------------------------- storage
 * Two alternating 4 KB slots.  Slot layout (little endian):
 *   u32 magic 'ATF1' | u32 seq | u16 ntags | u16 reserved | 9 x f32 calib | ntags x tag(u16 id,u16 pad,f32 size,3xf32 pos,4xf32 quat) | u16 crc16
 * Loading picks the valid slot with the highest seq; a half-written slot fails its CRC and is ignored. */
#define MAGIC 0x31465441u
#define TAG_BYTES 36

static size_t store_size(uint16_t nt) { return 12 + 36 + (size_t)nt * TAG_BYTES + 2; }

static size_t store_pack(const at_app_t *a, uint32_t seq, uint8_t *b)
{
    at_put_u32(b, MAGIC); at_put_u32(b + 4, seq); at_put_u16(b + 8, a->field.ntags); at_put_u16(b + 10, 0);
    const at_calib_t *c = &a->field.cal;
    real_t cv[9] = {c->fx, c->fy, c->cx, c->cy, c->k1, c->k2, c->p1, c->p2, c->k3};
    for (int i = 0; i < 9; i++) at_put_f32(b + 12 + 4 * i, (float)cv[i]);
    size_t o = 48;
    for (int i = 0; i < a->field.ntags; i++) {
        const at_tag_t *t = &a->field.tags[i]; real_t q[4]; at_rot_to_quat(t->R, q);
        at_put_u16(b + o, t->id); at_put_u16(b + o + 2, 0); at_put_f32(b + o + 4, (float)t->size);
        for (int k = 0; k < 3; k++) at_put_f32(b + o + 8 + 4 * k, (float)t->pos[k]);
        for (int k = 0; k < 4; k++) at_put_f32(b + o + 20 + 4 * k, (float)q[k]);
        o += TAG_BYTES;
    }
    at_put_u16(b + o, at_crc16(b, o));
    return o + 2;
}

static int store_parse(at_field_t *f, uint32_t *seq, const uint8_t *b, size_t avail)
{
    if (avail < 50 || at_get_u32(b) != MAGIC) return -1;
    uint16_t nt = at_get_u16(b + 8);
    if (nt > AT_MAX_TAGS || store_size(nt) > avail) return -1;
    size_t n = store_size(nt);
    if (at_crc16(b, n - 2) != at_get_u16(b + n - 2)) return -1;
    *seq = at_get_u32(b + 4);
    real_t cv[9]; for (int i = 0; i < 9; i++) cv[i] = at_get_f32(b + 12 + 4 * i);
    f->cal = (at_calib_t){cv[0], cv[1], cv[2], cv[3], cv[4], cv[5], cv[6], cv[7], cv[8]};
    f->ntags = nt;
    size_t o = 48;
    for (int i = 0; i < nt; i++) {
        at_tag_t *t = &f->tags[i]; real_t q[4];
        t->id = at_get_u16(b + o); t->size = at_get_f32(b + o + 4);
        for (int k = 0; k < 3; k++) t->pos[k] = at_get_f32(b + o + 8 + 4 * k);
        for (int k = 0; k < 4; k++) q[k] = at_get_f32(b + o + 20 + 4 * k);
        at_quat_to_rot(q, t->R);
        o += TAG_BYTES;
    }
    return 0;
}

int at_store_save(at_app_t *a)
{
    static uint8_t buf[AT_FLASH_SLOT_BYTES];
    uint32_t seq = a->store_seq + 1;
    size_t n = store_pack(a, seq, buf);
    int slot = (int)(seq & 1);
    if (a->hal.flash_erase(a->hal.ctx, slot)) return -1;
    if (a->hal.flash_write(a->hal.ctx, slot, 0, buf, n)) return -1;
    /* verify */
    static uint8_t chk[AT_FLASH_SLOT_BYTES];
    if (a->hal.flash_read(a->hal.ctx, slot, 0, chk, n) || memcmp(buf, chk, n)) return -1;
    a->store_seq = seq;
    return 0;
}

int at_store_load(at_app_t *a)
{
    static uint8_t buf[AT_FLASH_SLOT_BYTES];
    int found = 0; uint32_t best = 0; at_field_t tmp;
    for (int s = 0; s < AT_FLASH_SLOTS; s++) {
        uint32_t seq;
        if (a->hal.flash_read(a->hal.ctx, s, 0, buf, sizeof buf)) continue;
        if (store_parse(&tmp, &seq, buf, sizeof buf)) continue;
        if (!found || seq > best) { best = seq; a->field = tmp; found = 1; }
    }
    if (found) a->store_seq = best;
    return found ? 0 : -1;
}

/* ----------------------------------------------------------------------------------- tx helpers */
static void send(at_app_t *a, uint8_t type, const uint8_t *body, size_t n)
{
    uint8_t out[AT_MAX_FRAME + 8];
    size_t m = at_frame_encode(type, body, n, out, sizeof out);
    if (m) { a->hal.tx(a->hal.ctx, out, m); a->tx_msgs++; }
}
static void ack(at_app_t *a, uint8_t cmd) { send(a, AT_RSP_ACK, &cmd, 1); }
static void nak(at_app_t *a, uint8_t cmd, uint8_t err) { uint8_t b[2] = {cmd, err}; send(a, AT_RSP_NAK, b, 2); }

static void send_pose(at_app_t *a)
{
    uint8_t b[80]; real_t q[4]; at_rot_to_quat(a->pose.R, q);
    at_put_u32(b, a->pose_frame); at_put_u32(b + 4, a->pose_us);
    b[8] = a->pose.ntags; b[9] = a->pose.flags; at_put_u16(b + 10, (uint16_t)a->nobs);
    for (int i = 0; i < 3; i++) at_put_f32(b + 12 + 4 * i, (float)a->pose.t[i]);
    for (int i = 0; i < 4; i++) at_put_f32(b + 24 + 4 * i, (float)q[i]);
    at_put_f32(b + 40, (float)a->pose.rms_px);
    at_put_u32(b + 44, (uint32_t)a->pose_ts); at_put_u32(b + 48, (uint32_t)(a->pose_ts >> 32));
    send(a, AT_RSP_POSE, b, 52);
}

static void send_tags(at_app_t *a)
{
    uint8_t b[AT_MAX_BODY]; size_t o = 5;
    at_put_u32(b, a->pose_frame); b[4] = (uint8_t)a->nobs;
    for (int i = 0; i < a->nobs && o + 35 <= AT_MAX_BODY; i++) {
        at_put_u16(b + o, a->obs[i].id); b[o + 2] = a->obs[i].ham; o += 3;
        for (int c = 0; c < 4; c++) { at_put_f32(b + o, (float)a->obs[i].c[c][0]); at_put_f32(b + o + 4, (float)a->obs[i].c[c][1]); o += 8; }
    }
    b[4] = (uint8_t)((o - 5) / 35);
    send(a, AT_RSP_TAGS, b, o);
}

/* ----------------------------------------------------------------------------------- sensor */
/* exposure (lines) -> regs 0x3500..0x3502 = exposure<<4, gain -> 0x3509, with group hold; returns 0 on success */
static int sensor_write(at_app_t *a, uint16_t exposure, uint8_t gain)
{
    uint32_t e = (uint32_t)exposure << 4; int bad = 0;
    const struct { uint16_t reg; uint8_t v; } w[] = {{0x3308, 1}, {0x3500, (uint8_t)(e >> 16)}, {0x3501, (uint8_t)(e >> 8)},
                                                     {0x3502, (uint8_t)e}, {0x3509, gain}, {0x3308, 0}};
    for (unsigned i = 0; i < sizeof w / sizeof w[0]; i++) {
        bad |= a->hal.fpga_write(a->hal.ctx, FPGA_REG_I2C_DATA, w[i].v);
        bad |= a->hal.fpga_write(a->hal.ctx, FPGA_REG_I2C, 0x80000000u | (0x60u << 16) | w[i].reg);
        for (int spin = 0; spin < 2000; spin++) { uint32_t s; if (a->hal.fpga_read(a->hal.ctx, FPGA_REG_I2C_DATA, &s, 1) == 0 && !(s & 0x100)) break; }
    }
    return bad;
}

/* ----------------------------------------------------------------------------------- commands */
static void on_frame(at_app_t *a, uint8_t type, const uint8_t *p, size_t n)
{
    switch (type) {
    case AT_CMD_PING: {
        uint8_t b[12]; uint32_t id = 0;
        if (n >= 4) memcpy(b, p, 4); else memset(b, 0, 4);
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_ID, &id, 1);
        at_put_u32(b + 4, AT_FW_VERSION); at_put_u32(b + 8, id); send(a, AT_RSP_PONG, b, 12); break; }
    case AT_CMD_SET_CALIB:
        if (n != 36) { nak(a, type, AT_ERR_BAD_LEN); break; }
        { real_t v[9]; for (int i = 0; i < 9; i++) v[i] = at_get_f32(p + 4 * i);
          if (!(v[0] > 1) || !(v[1] > 1)) { nak(a, type, AT_ERR_RANGE); break; }
          a->field.cal = (at_calib_t){v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]}; ack(a, type); }
        break;
    case AT_CMD_CLEAR_MAP: a->field.ntags = 0; ack(a, type); break;
    case AT_CMD_ADD_TAG:
        if (n != 2 + 4 + 12 + 16) { nak(a, type, AT_ERR_BAD_LEN); break; }
        { uint16_t id = at_get_u16(p); at_tag_t *t = 0;
          for (int i = 0; i < a->field.ntags; i++) if (a->field.tags[i].id == id) t = &a->field.tags[i];
          if (!t) { if (a->field.ntags >= AT_MAX_TAGS) { nak(a, type, AT_ERR_FULL); break; } t = &a->field.tags[a->field.ntags++]; }
          real_t q[4]; t->id = id; t->size = at_get_f32(p + 2);
          for (int k = 0; k < 3; k++) t->pos[k] = at_get_f32(p + 6 + 4 * k);
          for (int k = 0; k < 4; k++) q[k] = at_get_f32(p + 18 + 4 * k);
          at_quat_to_rot(q, t->R); ack(a, type); }
        break;
    case AT_CMD_COMMIT:
        if (at_store_save(a)) nak(a, type, AT_ERR_FLASH); else ack(a, type);
        break;
    case AT_CMD_GET_CONFIG: {
        uint8_t b[40]; const at_calib_t *c = &a->field.cal;
        real_t cv[9] = {c->fx, c->fy, c->cx, c->cy, c->k1, c->k2, c->p1, c->p2, c->k3};
        for (int i = 0; i < 9; i++) at_put_f32(b + 4 * i, (float)cv[i]);
        at_put_u16(b + 36, a->field.ntags); at_put_u16(b + 38, 0); send(a, AT_RSP_CONFIG, b, 40); break; }
    case AT_CMD_GET_TAG: {
        if (n != 2) { nak(a, type, AT_ERR_BAD_LEN); break; }
        uint16_t i = at_get_u16(p);
        if (i >= a->field.ntags) { nak(a, type, AT_ERR_RANGE); break; }
        const at_tag_t *t = &a->field.tags[i]; real_t q[4]; uint8_t b[36]; at_rot_to_quat(t->R, q);
        at_put_u16(b, t->id); at_put_u16(b + 2, 0); at_put_f32(b + 4, (float)t->size);
        for (int k = 0; k < 3; k++) at_put_f32(b + 8 + 4 * k, (float)t->pos[k]);
        for (int k = 0; k < 4; k++) at_put_f32(b + 20 + 4 * k, (float)q[k]);
        send(a, AT_RSP_TAG, b, 36); break; }
    case AT_CMD_STREAM:
        if (n != 3) { nak(a, type, AT_ERR_BAD_LEN); break; }
        a->streaming = p[0] != 0; a->divider = at_get_u16(p + 1) ? at_get_u16(p + 1) : 1; a->div_cnt = 0; ack(a, type); break;
    case AT_CMD_SET_SENSOR: {
        if (n != 3) { nak(a, type, AT_ERR_BAD_LEN); break; }
        uint16_t e = at_get_u16(p);
        if (e < 1 || e > AT_SENSOR_EXP_LIMIT || p[2] < AT_AE_GAIN_MIN) { nak(a, type, AT_ERR_RANGE); break; }
        a->ae_enabled = 0;                                   /* manual control disables auto exposure */
        if (sensor_write(a, e, p[2])) { nak(a, type, AT_ERR_FLASH); break; }
        a->ae.exposure = e; a->ae.gain = p[2]; a->ae_synced = 1;
        ack(a, type); break; }
    case AT_CMD_SET_AE:
        if (n != 1) { nak(a, type, AT_ERR_BAD_LEN); break; }
        if (p[0] && !a->ae_enabled) at_ae_init(&a->ae, a->ae.exposure, a->ae.gain);
        a->ae_enabled = p[0] != 0; ack(a, type); break;
    case AT_CMD_SET_TRACK:
        if (n != 4) { nak(a, type, AT_ERR_BAD_LEN); break; }
        a->hal.fpga_write(a->hal.ctx, FPGA_REG_THRESH, (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)(p[3] & 63) << 24));
        ack(a, type); break;
    case AT_CMD_GET_STATUS: {
        uint32_t st[16] = {0}; uint8_t b[64] = {0};
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_STATUS, st, 1);
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_CCL, st + 1, 1);
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_DROPPED, st + 2, 3);
        at_put_u32(b, st[0]); at_put_u32(b + 4, st[1]); at_put_u32(b + 8, st[2]); at_put_u32(b + 12, st[3]); at_put_u32(b + 16, st[4]);
        at_put_u32(b + 20, a->solved); at_put_u32(b + 24, a->solve_fail); at_put_u32(b + 28, a->torn_reads);
        at_put_u32(b + 32, a->frame_id); at_put_u16(b + 36, a->field.ntags); b[38] = (uint8_t)a->pose_valid; b[39] = a->streaming;
        at_put_u16(b + 40, a->ae.exposure); b[42] = a->ae.gain; b[43] = a->ae_enabled;
        at_put_u16(b + 44, (uint16_t)(a->ae_mean * 256.0f)); at_put_u16(b + 46, 0);
        send(a, AT_RSP_STATUS, b, 48); break; }
    case AT_CMD_GET_TIME: {
        if (n != 0) { nak(a, type, AT_ERR_BAD_LEN); break; }
        uint32_t w[2] = {0}; uint8_t b[20];
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_TIME_LO, w, 2);
        uint64_t now = (uint64_t)w[0] | ((uint64_t)w[1] << 32);
        at_put_u32(b, (uint32_t)now); at_put_u32(b + 4, (uint32_t)(now >> 32));
        at_put_u32(b + 8, (uint32_t)a->frame_ts); at_put_u32(b + 12, (uint32_t)(a->frame_ts >> 32));
        at_put_u32(b + 16, AT_CLOCK_HZ);
        send(a, AT_RSP_TIME, b, 20); break; }
    case AT_CMD_GET_POSE:
        if (!a->pose_valid) nak(a, type, AT_ERR_NO_POSE); else send_pose(a);
        break;
    case AT_CMD_GET_TAGS_RAW: send_tags(a); break;
    default: nak(a, type, AT_ERR_UNKNOWN);
    }
}

void at_app_rx(at_app_t *a, const uint8_t *data, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        uint8_t type; const uint8_t *body; size_t bn;
        if (at_rx_feed(&a->rx, data[i], &type, &body, &bn)) on_frame(a, type, body, bn);
    }
}

void at_app_init(at_app_t *a, const at_hal_t *hal)
{
    memset(a, 0, sizeof *a);
    a->hal = *hal; at_rx_init(&a->rx); a->divider = 1;
    at_ae_init(&a->ae, AT_AE_INIT_EXPOSURE, AT_AE_INIT_GAIN); a->ae_enabled = 1;
    a->field.cal = (at_calib_t){640, 640, 639.5f, 399.5f, 0, 0, 0, 0, 0};
    at_store_load(a);
}

/* ----------------------------------------------------------------------------------- auto exposure */
static void run_ae(at_app_t *a)
{
    if (!a->ae_enabled) return;
    if (!a->ae_synced) {                                      /* first frame: put the sensor into the state the controller assumes */
        if (sensor_write(a, a->ae.exposure, a->ae.gain) == 0) a->ae_synced = 1;
        return;
    }
    uint32_t sum;
    if (a->hal.fpga_read(a->hal.ctx, FPGA_REG_FRAME_SUM, &sum, 1)) return;
    a->ae_mean = (float)((double)sum / (double)AT_FRAME_PIXELS);
    if (at_ae_step(&a->ae, a->ae_mean)) {
        if (sensor_write(a, a->ae.exposure, a->ae.gain) == 0) a->ae_updates++;
    }
}

/* ----------------------------------------------------------------------------------- FPGA results */
int at_app_poll(at_app_t *a)
{
    uint32_t st;
    if (a->hal.fpga_read(a->hal.ctx, FPGA_REG_STATUS, &st, 1)) return 0;
    if (!(st & 1)) return 0;                                  /* no result yet */
    uint32_t seq = st >> 16;
    if (a->have_seq && seq == a->last_seq) return 0;
    for (int attempt = 0; attempt < 3; attempt++) {
        uint32_t bank = (st >> 1) & 1, count = (st >> 8) & 0xFF, fid = 0;
        if (count > 31) count = 31;
        uint32_t words[16 + 16 * 31];
        uint32_t base = bank ? FPGA_RES_BANK1 : FPGA_RES_BANK0;
        if (a->hal.fpga_read(a->hal.ctx, base, words, 16 + 16 * count)) return 0;
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_FRAME, &fid, 1);
        uint32_t st2; a->hal.fpga_read(a->hal.ctx, FPGA_REG_STATUS, &st2, 1);
        if ((st2 >> 16) != seq) { a->torn_reads++; st = st2; seq = st >> 16; continue; }     /* a newer result landed mid-read */
        uint32_t t0 = a->hal.micros(a->hal.ctx);
        a->nobs = 0;
        at_meas_t meas[AT_MAX_MEAS];
        for (uint32_t i = 0; i < words[0] && i < count && a->nobs < AT_MAX_MEAS; i++) {
            const uint32_t *r = words + 16 + 16 * i;
            if (!(r[0] & 0x80000000u)) continue;
            at_tag_obs_t *o = &a->obs[a->nobs];
            o->id = (uint16_t)(r[0] & 0x3FF); o->ham = (uint8_t)((r[0] >> 12) & 63);
            for (int c = 0; c < 4; c++) {
                o->c[c][0] = (real_t)((int32_t)r[1 + 2 * c]) / 65536; o->c[c][1] = (real_t)((int32_t)r[2 + 2 * c]) / 65536;
                meas[a->nobs].c[c][0] = o->c[c][0]; meas[a->nobs].c[c][1] = o->c[c][1];
            }
            meas[a->nobs].id = o->id; a->nobs++;
        }
        uint32_t ft[4] = {0};
        a->hal.fpga_read(a->hal.ctx, FPGA_REG_FT0, ft, 4);
        a->frame_ts = bank ? ((uint64_t)ft[2] | ((uint64_t)ft[3] << 32)) : ((uint64_t)ft[0] | ((uint64_t)ft[1] << 32));
        a->have_seq = 1; a->last_seq = seq; a->frame_id = fid;
        at_pose_t p;
        if (a->nobs && at_solve(&a->field, meas, a->nobs, &p) == 0) {
            a->pose = p; a->pose_valid = 1; a->pose_frame = fid; a->pose_ts = a->frame_ts; a->solved++;
            a->pose_us = a->hal.micros(a->hal.ctx) - t0;
            if (a->streaming && ++a->div_cnt >= a->divider) { a->div_cnt = 0; send_pose(a); }
        } else if (a->nobs) a->solve_fail++;
        run_ae(a);
        return 1;
    }
    return 0;
}
