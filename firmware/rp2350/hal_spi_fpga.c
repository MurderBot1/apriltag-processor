#include "hal_spi_fpga.h"
#include "pcb_pins.h"
#include "hardware/gpio.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"

/* rtl/spi_slave.v protocol (SPI mode 0, MSB first):
 *   read : 0x03 a[23:16] a[15:8] a[7:0] <dummy byte> d0 d1 d2 ...   bytes of consecutive little-endian words
 *   write: 0x02 a[23:16] a[15:8] a[7:0] w0b0 w0b1 w0b2 w0b3 w1b0 ...  (word aligned)
 * The slave samples SCK with its core clock: SCK must stay <= clk/6 (16 MHz at 100 MHz), we run 12 MHz.
 * Chip select is driven by software and framed around the whole transaction. */

#define CMD_READ  0x03
#define CMD_WRITE 0x02

static inline void cs_low(void)  { gpio_put(PIN_FPGA_SPI_CSN, 0); __asm volatile("nop\nnop\nnop\nnop\nnop\nnop\nnop\nnop"); }
static inline void cs_high(void) { __asm volatile("nop\nnop\nnop\nnop\nnop\nnop\nnop\nnop"); gpio_put(PIN_FPGA_SPI_CSN, 1); }

void hal_fpga_init(void)
{
    spi_init(FPGA_SPI_INST, FPGA_SPI_HZ);
    spi_set_format(FPGA_SPI_INST, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(PIN_FPGA_SPI_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_FPGA_SPI_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(PIN_FPGA_SPI_MISO, GPIO_FUNC_SPI);
    gpio_init(PIN_FPGA_SPI_CSN);
    gpio_set_dir(PIN_FPGA_SPI_CSN, GPIO_OUT);
    gpio_put(PIN_FPGA_SPI_CSN, 1);
    gpio_init(PIN_FPGA_IRQ);
    gpio_set_dir(PIN_FPGA_IRQ, GPIO_IN);
}

int hal_fpga_read(void *ctx, uint32_t addr, uint32_t *words, size_t nwords)
{
    (void)ctx;
    if (!words || nwords == 0 || (addr & 3u) || addr > 0xFFFFFFu) return -1;
    const uint8_t hdr[5] = {CMD_READ, (uint8_t)(addr >> 16), (uint8_t)(addr >> 8), (uint8_t)addr, 0x00 /* dummy */};
    uint8_t *dst = (uint8_t *)words;                 /* RP2350 is little endian: bytes land directly as LE words */
    size_t n = nwords * 4u;
    cs_low();
    int w = spi_write_blocking(FPGA_SPI_INST, hdr, sizeof hdr);
    int r = spi_read_blocking(FPGA_SPI_INST, 0x00, dst, n);
    cs_high();
    return (w == (int)sizeof hdr && r == (int)n) ? 0 : -1;
}

int hal_fpga_write(void *ctx, uint32_t addr, uint32_t value)
{
    (void)ctx;
    if ((addr & 3u) || addr > 0xFFFFFFu) return -1;
    const uint8_t msg[8] = {CMD_WRITE, (uint8_t)(addr >> 16), (uint8_t)(addr >> 8), (uint8_t)addr,
                            (uint8_t)value, (uint8_t)(value >> 8), (uint8_t)(value >> 16), (uint8_t)(value >> 24)};
    cs_low();
    int w = spi_write_blocking(FPGA_SPI_INST, msg, sizeof msg);
    cs_high();
    sleep_us(1);                                      /* let the slave commit the word before the next transaction */
    return w == (int)sizeof msg ? 0 : -1;
}
