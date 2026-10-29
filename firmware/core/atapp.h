/* Application layer of the camera MCU: field/calibration storage, FPGA results -> pose, USB protocol. */
#pragma once
#include "atpose.h"
#include "atproto.h"
#include "atae.h"

#define AT_FW_VERSION 0x00010000u
#define AT_FLASH_SLOTS 2
#define AT_FLASH_SLOT_BYTES 4096

/* FPGA address map (see rtl/cam_core.v) */
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
#define FPGA_REG_FT0      0x00006Cu    /* frame start timestamps per capture bank: LO, HI, (bank 1:) LO, HI */
#define AT_CLOCK_HZ       1000000u
#define AT_FRAME_PIXELS   1024000u
#define AT_SENSOR_EXP_LIMIT 800        /* SET_SENSOR accepts 1..800 lines, gain >= 0x10 */
#define FPGA_RES_BANK0    0x001000u
#define FPGA_RES_BANK1    0x002000u

typedef struct {
    void *ctx;
    int (*fpga_read)(void *ctx, uint32_t addr, uint32_t *words, size_t nwords);   /* 0 = ok */
    int (*fpga_write)(void *ctx, uint32_t addr, uint32_t value);
    int (*flash_read)(void *ctx, int slot, uint32_t off, void *buf, size_t n);
    int (*flash_erase)(void *ctx, int slot);
    int (*flash_write)(void *ctx, int slot, uint32_t off, const void *buf, size_t n);
    void (*tx)(void *ctx, const uint8_t *data, size_t n);
    uint32_t (*micros)(void *ctx);
} at_hal_t;

typedef struct {
    uint16_t id; uint8_t ham; real_t c[4][2];
} at_tag_obs_t;

typedef struct {
    at_hal_t hal;
    at_field_t field;
    at_rx_t rx;
    uint8_t streaming; uint16_t divider, div_cnt;
    uint32_t last_seq; int have_seq;
    uint32_t frame_id, solved, solve_fail, torn_reads, tx_msgs;
    at_pose_t pose; int pose_valid; uint32_t pose_frame; uint32_t pose_us; uint64_t pose_ts, frame_ts;
    at_tag_obs_t obs[AT_MAX_MEAS]; int nobs;
    uint32_t store_seq;
    at_ae_t ae; uint8_t ae_enabled, ae_synced; float ae_mean; uint32_t ae_updates;
} at_app_t;

void at_app_init(at_app_t *a, const at_hal_t *hal);       /* loads the stored field if one is valid */
void at_app_rx(at_app_t *a, const uint8_t *data, size_t n);
int  at_app_poll(at_app_t *a);                            /* 1 if a new result set was processed */

/* storage (exposed for tests) */
int  at_store_save(at_app_t *a);
int  at_store_load(at_app_t *a);
