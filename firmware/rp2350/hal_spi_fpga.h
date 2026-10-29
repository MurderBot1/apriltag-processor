/* SPI0 master towards rtl/spi_slave.v (24-bit byte address bus, little-endian 32-bit words). */
#pragma once
#include <stddef.h>
#include <stdint.h>

void hal_fpga_init(void);
/* at_hal_t.fpga_read:  0x03, a2 a1 a0, dummy byte, then 4*nwords data bytes (auto-increment).  Returns 0 on success. */
int hal_fpga_read(void *ctx, uint32_t addr, uint32_t *words, size_t nwords);
/* at_hal_t.fpga_write: 0x02, a2 a1 a0, then the word as 4 bytes little endian.  Returns 0 on success. */
int hal_fpga_write(void *ctx, uint32_t addr, uint32_t value);
