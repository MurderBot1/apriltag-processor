#include "atproto.h"
#include <string.h>

uint16_t at_crc16(const uint8_t *d, size_t n)
{
    uint16_t c = 0xFFFF;
    while (n--) {
        c ^= (uint16_t)(*d++) << 8;
        for (int i = 0; i < 8; i++) c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1);
    }
    return c;
}

size_t at_frame_encode(uint8_t type, const uint8_t *body, size_t n, uint8_t *out, size_t cap)
{
    uint8_t raw[AT_MAX_FRAME];
    if (n > AT_MAX_BODY) return 0;
    raw[0] = type; memcpy(raw + 1, body, n);
    uint16_t crc = at_crc16(raw, n + 1);
    raw[n + 1] = crc & 0xFF; raw[n + 2] = crc >> 8;
    size_t rn = n + 3, o = 1, code_pos = 0;
    uint8_t code = 1;
    if (cap < rn + rn / 254 + 3) return 0;
    for (size_t i = 0; i < rn; i++) {
        if (raw[i] == 0) { out[code_pos] = code; code_pos = o++; code = 1; }
        else {
            out[o++] = raw[i]; code++;
            if (code == 0xFF) { out[code_pos] = code; code_pos = o++; code = 1; }
        }
    }
    out[code_pos] = code;
    out[o++] = 0;
    return o;
}

void at_rx_init(at_rx_t *r) { memset(r, 0, sizeof *r); }

static int cobs_decode(const uint8_t *in, size_t n, uint8_t *out, size_t *on)
{
    size_t i = 0, o = 0;
    while (i < n) {
        uint8_t code = in[i++];
        if (code == 0) return -1;
        for (uint8_t k = 1; k < code; k++) {
            if (i >= n) return -1;
            out[o++] = in[i++];
        }
        if (code != 0xFF && i < n) out[o++] = 0;
    }
    *on = o;
    return 0;
}

int at_rx_feed(at_rx_t *r, uint8_t b, uint8_t *type, const uint8_t **body, size_t *n)
{
    if (b != 0) {
        if (r->n < sizeof r->buf) r->buf[r->n++] = b; else r->overflow = 1;
        return 0;
    }
    size_t len = r->n; int ovf = r->overflow;
    r->n = 0; r->overflow = 0;
    if (len == 0) return 0;                          /* empty frame (resync) */
    uint8_t dec[AT_MAX_FRAME]; size_t dn = 0;
    if (ovf || cobs_decode(r->buf, len, dec, &dn) || dn < 3) { r->bad_frames++; return 0; }
    uint16_t crc = (uint16_t)(dec[dn - 2] | (dec[dn - 1] << 8));
    if (at_crc16(dec, dn - 2) != crc) { r->bad_frames++; return 0; }
    memcpy(r->buf, dec, dn - 2);
    *type = r->buf[0]; *body = r->buf + 1; *n = dn - 3;
    return 1;
}

void at_put_u16(uint8_t *p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }
void at_put_u32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (v >> (8 * i)) & 0xFF; }
void at_put_f32(uint8_t *p, float v) { uint32_t u; memcpy(&u, &v, 4); at_put_u32(p, u); }
uint16_t at_get_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
uint32_t at_get_u32(const uint8_t *p) { return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
float at_get_f32(const uint8_t *p) { uint32_t u = at_get_u32(p); float f; memcpy(&f, &u, 4); return f; }
