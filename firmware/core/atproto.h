/* USB byte-stream protocol: frame = COBS( type | body | crc16-le ) 0x00, CRC-16/CCITT-FALSE over type|body. */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define AT_MAX_BODY 256
#define AT_MAX_FRAME (AT_MAX_BODY + 8)

enum {
    /* host -> device */
    AT_CMD_PING = 0x01, AT_CMD_SET_CALIB = 0x02, AT_CMD_CLEAR_MAP = 0x03, AT_CMD_ADD_TAG = 0x04, AT_CMD_COMMIT = 0x05,
    AT_CMD_GET_CONFIG = 0x06, AT_CMD_STREAM = 0x07, AT_CMD_SET_SENSOR = 0x08, AT_CMD_GET_STATUS = 0x09,
    AT_CMD_SET_TRACK = 0x0A, AT_CMD_GET_POSE = 0x0B, AT_CMD_GET_TAG = 0x0C, AT_CMD_GET_TAGS_RAW = 0x0D, AT_CMD_SET_AE = 0x0E, AT_CMD_GET_TIME = 0x0F,
    AT_CMD_SET_AUTO_RATIO = 0x10,
    /* device -> host */
    AT_RSP_ACK = 0x80, AT_RSP_PONG = 0x81, AT_RSP_POSE = 0x82, AT_RSP_TAGS = 0x83, AT_RSP_STATUS = 0x89, AT_RSP_TIME = 0x8A,
    AT_RSP_CONFIG = 0x86, AT_RSP_TAG = 0x87, AT_RSP_NAK = 0xFF
};
enum { AT_ERR_BAD_LEN = 1, AT_ERR_FULL = 2, AT_ERR_FLASH = 3, AT_ERR_UNKNOWN = 4, AT_ERR_NO_POSE = 5, AT_ERR_RANGE = 6 };

uint16_t at_crc16(const uint8_t *d, size_t n);
/* encodes into out (cap >= n + n/254 + 6); returns frame length including the trailing 0x00, 0 on overflow */
size_t at_frame_encode(uint8_t type, const uint8_t *body, size_t n, uint8_t *out, size_t cap);

typedef struct { uint8_t buf[AT_MAX_FRAME]; size_t n; uint8_t overflow; uint32_t bad_frames; } at_rx_t;
void at_rx_init(at_rx_t *r);
/* returns 1 when a valid frame completed: *type, *body (valid until the next feed), *n set */
int at_rx_feed(at_rx_t *r, uint8_t b, uint8_t *type, const uint8_t **body, size_t *n);

/* little-endian helpers */
void at_put_u16(uint8_t *p, uint16_t v); void at_put_u32(uint8_t *p, uint32_t v); void at_put_f32(uint8_t *p, float v);
uint16_t at_get_u16(const uint8_t *p); uint32_t at_get_u32(const uint8_t *p); float at_get_f32(const uint8_t *p);
