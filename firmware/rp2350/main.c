/* AprilTag camera MCU firmware (RP2350).
 *
 * Everything runs on core 0 in one cooperative loop, so the shared at_app_t needs no locking:
 *   tud_task()            USB device stack
 *   CDC rx  -> at_app_rx  protocol commands (replies leave through the HAL tx callback)
 *   at_app_poll           frame packet from the FPGA (PIO + DMA, hal_frame_rx.c) -> tag unit (attpu.c, runs here) -> pose solve ->
 *                         optional POSE streaming, auto exposure
 *   watchdog_update       2 s watchdog; a hang resets the MCU (config is reloaded from flash, FPGA is reconfigured)
 * Core 1 is unused; flash programming therefore only has to stop core 0's interrupts (flash_safe_execute). */
#include "pico/stdlib.h"
#include "pico/flash.h"
#include "hardware/watchdog.h"
#include "tusb.h"
#include "atapp.h"
#include "pcb_pins.h"
#include "hal_spi_fpga.h"
#include "hal_flash.h"
#include "hal_frame_rx.h"
#include "fpga_config.h"

static at_app_t g_app;

static uint32_t hal_micros(void *ctx) { (void)ctx; return time_us_32(); }

/* tx towards the host: never block for long, drop output if nobody listens (port closed) or the host stops reading */
static void hal_tx(void *ctx, const uint8_t *data, size_t n)
{
    (void)ctx;
    if (!tud_cdc_connected()) return;
    absolute_time_t deadline = make_timeout_time_ms(20);
    while (n) {
        uint32_t room = tud_cdc_write_available();
        if (room == 0) {
            tud_task();
            tud_cdc_write_flush();
            if (absolute_time_diff_us(get_absolute_time(), deadline) <= 0) return;
            continue;
        }
        uint32_t k = n < room ? (uint32_t)n : room;
        tud_cdc_write(data, k);
        data += k; n -= k;
    }
    tud_cdc_write_flush();
}

static void led(int on) { gpio_put(PIN_LED_STAT, on); }

int main(void)
{
    gpio_init(PIN_LED_STAT);
    gpio_set_dir(PIN_LED_STAT, GPIO_OUT);
    led(1);

    flash_safe_execute_core_init();           /* allow flash_safe_execute() while only core 0 runs */
    hal_fpga_init();

    /* the FPGA must be configured before the first SPI access; do it before USB enumeration */
    fpga_cfg_result_t cfg = fpga_config_load();

    if (cfg == FPGA_CFG_OK) hal_frame_init();   /* frame bus receiver: only once the FPGA drives its pins */

    tusb_init();                              /* if cfg != OK we keep running: the host can still talk to the MCU, polling is skipped */

    const at_hal_t hal = {
        .ctx = NULL,
        .fpga_read = hal_fpga_read, .fpga_write = hal_fpga_write,
        .flash_read = hal_flash_read, .flash_erase = hal_flash_erase, .flash_write = hal_flash_write,
        .tx = hal_tx, .micros = hal_micros,
        .frame_get = hal_frame_get, .frame_put = hal_frame_put, .detect = NULL,
    };
    at_app_init(&g_app, &hal);

    watchdog_enable(2000, true);
    absolute_time_t led_t = get_absolute_time();
    int led_state = 0;
    uint8_t buf[64];
    for (;;) {
        tud_task();
        while (tud_cdc_available()) {
            uint32_t n = tud_cdc_read(buf, sizeof buf);
            at_app_rx(&g_app, buf, n);
        }
        if (cfg == FPGA_CFG_OK) at_app_poll(&g_app);
        watchdog_update();

        /* LED: 1 Hz heartbeat when healthy, 5 Hz when the FPGA failed to configure */
        int64_t period = cfg == FPGA_CFG_OK ? 500000 : 100000;
        if (absolute_time_diff_us(led_t, get_absolute_time()) > period) {
            led_t = get_absolute_time(); led_state ^= 1; led(led_state);
        }
    }
}
