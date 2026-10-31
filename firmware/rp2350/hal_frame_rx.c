/* Receiver of the FPGA frame bus: PIO state machine (frame_rx.pio) -> DMA -> frame buffers in SRAM.
 *
 * One packet = AT_PKT_BYTES (132,128) bytes = one DMA transfer.  The DMA channel is re-armed from its own completion interrupt: to a free
 * buffer if there is one, otherwise to a dummy word (write address not incremented), so the byte stream always stays aligned with the
 * packet boundaries even when the application is busy.  A packet that ends early (FS falls before the transfer count reached zero) or a
 * stall is repaired by aborting the transfer, flushing the PIO and starting over; that packet is counted as lost.
 * The gap between packets is >= 1.5 ms (vertical blanking), the interrupt work takes microseconds.
 *
 * Pins (pcb_pins.h): D0..D7 = PIN_FB_D0.., CLK = PIN_FB_CLK (must be PIN_FB_D0 + 8), FS = PIN_FB_FS.
 * NOT verified on hardware (see docs/fpga.md "MCU frame bus"): input timing margin, DMA/CPU SRAM arbitration at 21 Mbyte/s with the tag unit running. */
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "hardware/structs/bus_ctrl.h"
#include "hal_frame_rx.h"
#include "pcb_pins.h"
#include "frame_rx.pio.h"

#define NBUF 2

static uint32_t g_buf[NBUF][AT_PKT_WORDS] __attribute__((aligned(4)));
static uint32_t g_trash;
enum { S_FREE = 0, S_FILLING, S_READY, S_BUSY };
static volatile uint8_t g_state[NBUF];
static volatile uint32_t g_order[NBUF];          /* arrival number of a READY buffer */
static volatile uint32_t g_arrivals;
static volatile int g_cur = -1;                  /* buffer being filled, -1 = dummy sink */
static volatile uint32_t g_lost;
static volatile int g_held = -1;                 /* buffer handed to the application */
static PIO g_pio = pio0;
static uint g_sm, g_dma;
static uint g_offset;

static void arm_dma(void)
{
    int pick = -1;
    for (int i = 0; i < NBUF; i++) if (g_state[i] == S_FREE) { pick = i; break; }
    g_cur = pick;
    dma_channel_config c = dma_channel_get_default_config(g_dma);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, false);
    channel_config_set_dreq(&c, pio_get_dreq(g_pio, g_sm, false));
    if (pick >= 0) {
        g_state[pick] = S_FILLING;
        channel_config_set_write_increment(&c, true);
        dma_channel_configure(g_dma, &c, g_buf[pick], &g_pio->rxf[g_sm], AT_PKT_WORDS, true);
    } else {
        channel_config_set_write_increment(&c, false);
        dma_channel_configure(g_dma, &c, &g_trash, &g_pio->rxf[g_sm], AT_PKT_WORDS, true);
    }
}

static void dma_done_isr(void)
{
    dma_hw->ints0 = 1u << g_dma;
    if (g_cur >= 0) { g_order[g_cur] = ++g_arrivals; g_state[g_cur] = S_READY; }
    else g_lost++;
    arm_dma();
}

/* restart reception from scratch: stop the transfer, empty the PIO, drop the partial packet */
static void resync(void)
{
    uint32_t irq = save_and_disable_interrupts();
    dma_channel_abort(g_dma);
    pio_sm_set_enabled(g_pio, g_sm, false);
    pio_sm_clear_fifos(g_pio, g_sm);
    pio_sm_restart(g_pio, g_sm);
    pio_sm_exec(g_pio, g_sm, pio_encode_jmp(g_offset));
    if (g_cur >= 0) g_state[g_cur] = S_FREE;
    g_lost++;
    dma_hw->ints0 = 1u << g_dma;
    arm_dma();
    pio_sm_set_enabled(g_pio, g_sm, true);
    restore_interrupts(irq);
}

/* FS fell 100 us ago: the packet must be complete by now (DMA idle or already re-armed with a full count) */
static int64_t fs_check(alarm_id_t id, void *user)
{
    (void)id; (void)user;
    if (!gpio_get(PIN_FB_FS) && dma_channel_is_busy(g_dma) && dma_hw->ch[g_dma].transfer_count != AT_PKT_WORDS)
        resync();                                        /* transfer started but did not finish although the FPGA stopped sending */
    return 0;
}

static void fs_irq(uint gpio, uint32_t events)
{
    (void)gpio;
    if (events & GPIO_IRQ_EDGE_FALL) add_alarm_in_us(100, fs_check, NULL, true);
}

void hal_frame_init(void)
{
    for (int i = 0; i <= 8; i++) { gpio_init(PIN_FB_D0 + i); gpio_set_dir(PIN_FB_D0 + i, GPIO_IN); gpio_pull_down(PIN_FB_D0 + i); }
    gpio_init(PIN_FB_FS); gpio_set_dir(PIN_FB_FS, GPIO_IN); gpio_pull_down(PIN_FB_FS);
    g_offset = pio_add_program(g_pio, &frame_rx_program);
    g_sm = pio_claim_unused_sm(g_pio, true);
    for (int i = 0; i <= 8; i++) pio_gpio_init(g_pio, PIN_FB_D0 + i);
    pio_sm_config c = frame_rx_program_get_default_config_for(g_offset, PIN_FB_D0);
    pio_sm_init(g_pio, g_sm, g_offset, &c);
    g_dma = dma_claim_unused_channel(true);
    bus_ctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_R_BITS | BUSCTRL_BUS_PRIORITY_DMA_W_BITS;   /* the FIFO must be drained within ~1.5 us */
    dma_channel_set_irq0_enabled(g_dma, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_done_isr);
    irq_set_priority(DMA_IRQ_0, 0);
    irq_set_enabled(DMA_IRQ_0, true);
    gpio_set_irq_enabled_with_callback(PIN_FB_FS, GPIO_IRQ_EDGE_FALL, true, fs_irq);
    memset((void *)g_state, 0, sizeof g_state);
    arm_dma();
    pio_sm_set_enabled(g_pio, g_sm, true);
}

int hal_frame_get(void *ctx, at_frame_buf_t *b)
{
    (void)ctx;
    uint32_t irq = save_and_disable_interrupts();
    int pick = -1;
    for (int i = 0; i < NBUF; i++) if (g_state[i] == S_READY && (pick < 0 || g_order[i] < g_order[pick])) pick = i;
    b->lost = g_lost;
    if (pick >= 0 && g_held < 0) { g_state[pick] = S_BUSY; g_held = pick; b->data = g_buf[pick]; b->bytes = AT_PKT_BYTES; }
    else pick = -1;
    restore_interrupts(irq);
    return pick >= 0;
}

void hal_frame_put(void *ctx)
{
    (void)ctx;
    uint32_t irq = save_and_disable_interrupts();
    if (g_held >= 0) { g_state[g_held] = S_FREE; g_held = -1; }
    restore_interrupts(irq);
}
