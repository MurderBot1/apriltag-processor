#include "hal_flash.h"
#include "pcb_pins.h"
#include <string.h>
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "hardware/regs/addressmap.h"
#include "pico/flash.h"

/* Flash programming stalls XIP, so the erase/program routines must run from RAM with interrupts off and the other core parked.
 * flash_safe_execute() (pico_flash) does exactly that: it disables interrupts on this core and uses multicore lockout /
 * the flash-safe handshake for core 1.  This firmware runs on core 0 only, so the lockout is trivial. */

#define SLOT_BYTES 4096u

_Static_assert(FLASH_SECTOR_SIZE == SLOT_BYTES, "a configuration slot must be exactly one erase sector");
_Static_assert(FLASH_BITSTREAM_OFFSET + FLASH_BITSTREAM_MAX <= FLASH_CONFIG_OFFSET, "bitstream partition overlaps the config slots");

typedef struct { uint32_t off; const uint8_t *src; size_t n; int op; } flash_job_t;   /* op 0 = erase, 1 = program */

static void flash_job_run(void *p)
{
    flash_job_t *j = (flash_job_t *)p;
    if (j->op == 0) flash_range_erase(j->off, SLOT_BYTES);
    else flash_range_program(j->off, j->src, j->n);          /* off and n are multiples of FLASH_PAGE_SIZE here */
}

static int run_job(flash_job_t *j)
{
    return flash_safe_execute(flash_job_run, j, 500) == PICO_OK ? 0 : -1;
}

static uint32_t slot_base(int slot) { return FLASH_CONFIG_OFFSET + (uint32_t)slot * SLOT_BYTES; }

const uint8_t *hal_flash_xip_ptr(uint32_t flash_offset) { return (const uint8_t *)(XIP_BASE + flash_offset); }

int hal_flash_read(void *ctx, int slot, uint32_t off, void *buf, size_t n)
{
    (void)ctx;
    if (slot < 0 || slot >= 2 || off > SLOT_BYTES || n > SLOT_BYTES - off) return -1;
    memcpy(buf, hal_flash_xip_ptr(slot_base(slot) + off), n);
    return 0;
}

int hal_flash_erase(void *ctx, int slot)
{
    (void)ctx;
    if (slot < 0 || slot >= 2) return -1;
    flash_job_t j = {slot_base(slot), 0, 0, 0};
    return run_job(&j);
}

int hal_flash_write(void *ctx, int slot, uint32_t off, const void *buf, size_t n)
{
    (void)ctx;
    if (slot < 0 || slot >= 2 || off > SLOT_BYTES || n > SLOT_BYTES - off) return -1;
    const uint8_t *src = (const uint8_t *)buf;
    uint8_t page[FLASH_PAGE_SIZE];
    while (n) {
        uint32_t page_off = off & ~(uint32_t)(FLASH_PAGE_SIZE - 1u);
        uint32_t in_page = off - page_off;
        size_t take = FLASH_PAGE_SIZE - in_page;
        if (take > n) take = n;
        memset(page, 0xFF, sizeof page);                      /* bytes outside the request stay erased (0xFF programs nothing) */
        memcpy(page + in_page, src, take);
        flash_job_t j = {slot_base(slot) + page_off, page, FLASH_PAGE_SIZE, 1};
        if (run_job(&j)) return -1;
        off += (uint32_t)take; src += take; n -= take;
    }
    return 0;
}
