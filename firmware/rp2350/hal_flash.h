/* Two 4 KB configuration slots at the end of the 16 MB QSPI flash (see pcb_pins.h for the layout). */
#pragma once
#include <stddef.h>
#include <stdint.h>

int hal_flash_read(void *ctx, int slot, uint32_t off, void *buf, size_t n);          /* via XIP, 0 = ok */
int hal_flash_erase(void *ctx, int slot);                                              /* erases the 4 KB sector */
int hal_flash_write(void *ctx, int slot, uint32_t off, const void *buf, size_t n);   /* any off/n inside the slot */

/* generic helpers used by fpga_config.c (absolute flash offsets) */
const uint8_t *hal_flash_xip_ptr(uint32_t flash_offset);
