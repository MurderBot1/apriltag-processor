/* Application layer of the camera MCU: field/calibration storage, FPGA results -> pose, USB protocol. */
#pragma once
#include "atpose.h"
#include "attpu.h"
#include "atproto.h"
#include "atae.h"
#include "atratio.h"
#include "atframe.h"

#define AT_FW_VERSION 0x00010000u
#define AT_FLASH_SLOTS 2
#define AT_FLASH_SLOT_BYTES 4096

/* FPGA register map (SPI, see rtl/cam_core.v); frames arrive separately on the MCU frame bus (atframe.h) */
#define FPGA_REG_ID       0x000000u
#define FPGA_REG_CTRL     0x000008u
#define FPGA_REG_THRESH   0x00000Cu
#define FPGA_REG_STATUS   0x000018u
#define FPGA_REG_FRAME    0x00001Cu
#define FPGA_REG_CCL      0x000028u
#define FPGA_REG_DROPPED  0x000030u
#define FPGA_REG_TOTAL    0x000034u
#define FPGA_REG_PROC     0x000038u
#define FPGA_REG_I2C      0x000040u
#define FPGA_REG_I2C_DATA 0x000044u
#define FPGA_REG_FRAME_SUM 0x000060u   /* sum of all pixels of the last frame; mean = sum / AT_FRAME_PIXELS */
#define FPGA_REG_TIME_LO  0x000064u    /* device clock, 64 bit us counter; reading LO latches HI */
#define FPGA_REG_TIME_HI  0x000068u
#define AT_THRESH_RESET   0x020A4018u  /* FPGA reset value: diff 24, abs_black 64, mindim 10, maxham 2, ratio 0 */
#define AT_CLOCK_HZ       1000000u
#define AT_FRAME_PIXELS   1024000u
#define AT_SENSOR_EXP_LIMIT 800        /* SET_SENSOR accepts 1..800 lines, gain >= 0x10 */

typedef struct {
    const void *data;       /* oldest complete packet that has not been released yet (valid until frame_put) */
    size_t bytes;           /* length actually received */
    uint32_t lost;          /* running total of packets the receiver could not deliver (no free buffer, resync, short packet) */
    uint32_t max_depth;     /* most packets ever waiting or in processing at once (at_bufpool_t.max_depth) */
} at_frame_buf_t;

typedef struct {
    void *ctx;
    int (*fpga_read)(void *ctx, uint32_t addr, uint32_t *words, size_t nwords);   /* 0 = ok */
    int (*fpga_write)(void *ctx, uint32_t addr, uint32_t value);
    int (*flash_read)(void *ctx, int slot, uint32_t off, void *buf, size_t n);
    int (*flash_erase)(void *ctx, int slot);
    int (*flash_write)(void *ctx, int slot, uint32_t off, const void *buf, size_t n);
    void (*tx)(void *ctx, const uint8_t *data, size_t n);
    uint32_t (*micros)(void *ctx);
    int (*frame_get)(void *ctx, at_frame_buf_t *b);       /* 1 if a packet is ready in *b; always updates b->lost */
    void (*frame_put)(void *ctx);                         /* release the packet returned by the last frame_get */
    /* optional test hook: returns the number of injected tags written to out, or < 0 to run the real tag unit; NULL on the device */
    int (*detect)(void *ctx, const at_frame_t *f, attpu_tag_t *out, unsigned max);
} at_hal_t;

typedef struct {
    uint16_t id; uint8_t ham; real_t c[4][2];
} at_tag_obs_t;

typedef struct {
    at_hal_t hal;
    at_field_t field;
    at_rx_t rx;
    uint8_t streaming; uint16_t divider, div_cnt;
    uint32_t frame_id, solved, solve_fail, torn_reads, tx_msgs;       /* torn_reads (legacy name, wire field unchanged): damaged / rejected packets */
    uint32_t frames_done, rx_lost, rx_max_depth; uint8_t maxham;
    at_pose_t pose; int pose_valid; uint32_t pose_frame; uint32_t pose_us; uint64_t pose_ts, frame_ts;
    at_tag_obs_t obs[AT_MAX_MEAS]; int nobs;
    uint32_t store_seq;
    uint32_t thresh; at_ar_t ar; uint8_t ar_enabled;            /* THRESH register as last written (reset value 0x020A4018); automatic ratio policy */
    at_ae_t ae; uint8_t ae_enabled, ae_synced; float ae_mean; uint32_t ae_updates;
} at_app_t;

void at_app_init(at_app_t *a, const at_hal_t *hal);       /* loads the stored field if one is valid */
void at_app_rx(at_app_t *a, const uint8_t *data, size_t n);
int  at_app_poll(at_app_t *a);                            /* 1 if a frame packet was received and processed */

/* storage (exposed for tests) */
int  at_store_save(at_app_t *a);
int  at_store_load(at_app_t *a);
