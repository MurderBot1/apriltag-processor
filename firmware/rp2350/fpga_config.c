#include "fpga_config.h"
#include "pcb_pins.h"
#include "hal_flash.h"
#include "hardware/gpio.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"
#include "pico/time.h"
#include <string.h>

/* ECP5 slave SPI configuration (Lattice TN-02039 "ECP5 and ECP5-5G sysCONFIG Usage Guide", slave SPI port).  The flow below uses the
 * documented ISC command set; the opcode values are taken from that guide and have NOT been checked on hardware.
 *   1. PROGRAMN low (>= 25 ns, we hold 10 us), release; INITN must go low then high (device cleared and ready).
 *   2. READ_ID (0xE0) - sanity check that the port answers.
 *   3. ISC_ENABLE (0xC6), ISC_ERASE (0x0E, SRAM), poll LSC_CHECK_BUSY (0xF0) until idle.
 *   4. LSC_INIT_ADDRESS (0x46), LSC_BITSTREAM_BURST (0x7A) then the raw bitstream in the same chip-select window.
 *   5. ISC_DISABLE (0x26); DONE goes high when the device enters user mode.
 * With FPGA_CFG_RAW_STREAM=1 (CFG pins strapped for the plain slave-SPI stream mode) steps 2-3 and the opcodes are skipped and the
 * bitstream is clocked in directly after INITN rises. */
#ifndef FPGA_CFG_RAW_STREAM
#define FPGA_CFG_RAW_STREAM 0
#endif

#define OP_READ_ID    0xE0
#define OP_ISC_ENABLE 0xC6
#define OP_ISC_ERASE  0x0E
#define OP_CHECK_BUSY 0xF0
#define OP_INIT_ADDR  0x46
#define OP_BURST      0x7A
#define OP_ISC_DISABLE 0x26

#define HDR_BYTES 16u

static uint32_t crc32_update(uint32_t crc, const uint8_t *p, uint32_t n)
{
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++) crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)-(int32_t)(crc & 1u));
    }
    return crc;
}

static inline void cfg_cs(int level) { gpio_put(PIN_FPGA_CFG_CSN, level); }

static void cfg_cmd(uint8_t op, uint8_t *rx, size_t rx_n)
{
    const uint8_t cmd[4] = {op, 0, 0, 0};
    cfg_cs(0);
    spi_write_blocking(FPGA_CFG_SPI_INST, cmd, 4);
    if (rx_n) spi_read_blocking(FPGA_CFG_SPI_INST, 0x00, rx, rx_n);
    cfg_cs(1);
}

int fpga_config_done(void) { return gpio_get(PIN_FPGA_DONE); }

fpga_cfg_result_t fpga_config_verify_image(uint32_t *length_out)
{
    const uint8_t *p = hal_flash_xip_ptr(FLASH_BITSTREAM_OFFSET);
    uint32_t magic, len, crc;
    memcpy(&magic, p, 4); memcpy(&len, p + 4, 4); memcpy(&crc, p + 8, 4);
    if (magic != FPGA_CFG_MAGIC || len < 1024 || len > FLASH_BITSTREAM_MAX - HDR_BYTES) return FPGA_CFG_ERR_NO_IMAGE;
    if (~crc32_update(0xFFFFFFFFu, p + HDR_BYTES, len) != crc) return FPGA_CFG_ERR_CRC;
    if (length_out) *length_out = len;
    return FPGA_CFG_OK;
}

static int wait_pin(uint pin, int level, uint32_t timeout_ms)
{
    absolute_time_t end = make_timeout_time_ms(timeout_ms);
    while (gpio_get(pin) != level) {
        if (absolute_time_diff_us(get_absolute_time(), end) <= 0) return -1;
        tight_loop_contents();
    }
    return 0;
}

fpga_cfg_result_t fpga_config_load(void)
{
    uint32_t len = 0;
    fpga_cfg_result_t r = fpga_config_verify_image(&len);
    if (r != FPGA_CFG_OK) return r;

    gpio_init(PIN_FPGA_PROGRAMN); gpio_put(PIN_FPGA_PROGRAMN, 1); gpio_set_dir(PIN_FPGA_PROGRAMN, GPIO_OUT);
    gpio_init(PIN_FPGA_INITN);    gpio_set_dir(PIN_FPGA_INITN, GPIO_IN);  gpio_pull_up(PIN_FPGA_INITN);
    gpio_init(PIN_FPGA_DONE);     gpio_set_dir(PIN_FPGA_DONE, GPIO_IN);   gpio_pull_up(PIN_FPGA_DONE);
    gpio_init(PIN_FPGA_CFG_CSN);  gpio_put(PIN_FPGA_CFG_CSN, 1); gpio_set_dir(PIN_FPGA_CFG_CSN, GPIO_OUT);

    spi_init(FPGA_CFG_SPI_INST, FPGA_CFG_SPI_HZ);
    spi_set_format(FPGA_CFG_SPI_INST, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(PIN_FPGA_CFG_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_FPGA_CFG_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(PIN_FPGA_CFG_MISO, GPIO_FUNC_SPI);

    /* 1. restart configuration */
    gpio_put(PIN_FPGA_PROGRAMN, 0);
    sleep_us(10);
    gpio_put(PIN_FPGA_PROGRAMN, 1);
    sleep_ms(1);
    if (wait_pin(PIN_FPGA_INITN, 1, 100)) return FPGA_CFG_ERR_INITN;
    sleep_us(100);

#if !FPGA_CFG_RAW_STREAM
    uint8_t id[4];
    cfg_cmd(OP_READ_ID, id, 4);                                /* result is informational; a dead port shows up as DONE timeout */
    cfg_cmd(OP_ISC_ENABLE, 0, 0);
    cfg_cmd(OP_ISC_ERASE, 0, 0);
    for (int i = 0;; i++) {
        uint8_t busy = 0xFF;
        cfg_cmd(OP_CHECK_BUSY, &busy, 1);
        if (!(busy & 0x80)) break;
        if (i > 1000) return FPGA_CFG_ERR_BUSY;
        sleep_ms(1);
    }
    cfg_cmd(OP_INIT_ADDR, 0, 0);
    const uint8_t burst[4] = {OP_BURST, 0, 0, 0};
#endif

    /* 2. stream the bitstream straight out of XIP flash in one chip-select window */
    const uint8_t *bs = hal_flash_xip_ptr(FLASH_BITSTREAM_OFFSET) + HDR_BYTES;
    cfg_cs(0);
#if !FPGA_CFG_RAW_STREAM
    spi_write_blocking(FPGA_CFG_SPI_INST, burst, 4);
#endif
    for (uint32_t off = 0; off < len; ) {
        uint32_t chunk = len - off > 4096 ? 4096 : len - off;
        spi_write_blocking(FPGA_CFG_SPI_INST, bs + off, chunk);
        off += chunk;
    }
    cfg_cs(1);

#if !FPGA_CFG_RAW_STREAM
    cfg_cmd(OP_ISC_DISABLE, 0, 0);
#endif
    /* >= 49 spare clocks with CS high help some devices leave configuration mode */
    uint8_t pad[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    spi_write_blocking(FPGA_CFG_SPI_INST, pad, sizeof pad);

    if (wait_pin(PIN_FPGA_DONE, 1, 200)) return FPGA_CFG_ERR_DONE;
    return FPGA_CFG_OK;
}
