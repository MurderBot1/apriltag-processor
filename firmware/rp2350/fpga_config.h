/* Loads the FPGA (Lattice ECP5) bitstream from a flash partition over the ECP5 slave-SPI configuration port.
 *
 * Partition format at FLASH_BITSTREAM_OFFSET (little endian):
 *   u32 magic   0x35504345 ("ECP5")
 *   u32 length  bitstream length in bytes (<= FLASH_BITSTREAM_MAX - 16)
 *   u32 crc32   CRC-32 (IEEE 802.3, reflected, init/xorout 0xFFFFFFFF) of the bitstream bytes
 *   u32 reserved
 *   u8  data[length]   the raw configuration bitstream (the bytes of the .bit file after its ASCII comment header, i.e. starting
 *                      with the 0xFF 0xFF 0xBD 0xB3 preamble), MSB first as in the file.
 */
#pragma once
#include <stdint.h>

#define FPGA_CFG_MAGIC 0x35504345u

typedef enum {
    FPGA_CFG_OK = 0,
    FPGA_CFG_ERR_NO_IMAGE,        /* bad magic / length in the partition */
    FPGA_CFG_ERR_CRC,             /* stored image fails its CRC */
    FPGA_CFG_ERR_INITN,           /* INITN did not go high after PROGRAMN */
    FPGA_CFG_ERR_BUSY,            /* device stayed busy after erase */
    FPGA_CFG_ERR_DONE             /* DONE did not go high after the bitstream */
} fpga_cfg_result_t;

/* Pulses PROGRAMN, streams the bitstream, waits for DONE.  Blocking, ~0.2 s typical.  Call after hal_flash is usable. */
fpga_cfg_result_t fpga_config_load(void);
/* Checks the partition header and CRC without touching the FPGA. */
fpga_cfg_result_t fpga_config_verify_image(uint32_t *length_out);
int fpga_config_done(void);                  /* DONE pin level */
