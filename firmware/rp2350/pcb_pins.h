/* RP2350 pin assignments for the AprilTag camera board.
 *
 * !! PROVISIONAL !!  The GPIO numbers below are the working assumption of the firmware team; the PCB engineer must confirm
 * (or change) them against the schematic.  Every pin used by the firmware is listed here and ONLY here.
 *
 *  Signal              GPIO  Function      Direction (MCU)  Connects to
 *  ------------------  ----  ------------  ---------------  -------------------------------------------------------
 *  FPGA_SPI_SCK         2    SPI0 SCK      out              FPGA spi_slave sck   (mode 0, <= 12 MHz)
 *  FPGA_SPI_MOSI        3    SPI0 TX       out              FPGA spi_slave mosi
 *  FPGA_SPI_MISO        4    SPI0 RX       in               FPGA spi_slave miso  (FPGA tri-states when CS high)
 *  FPGA_SPI_CSN         5    SIO (GPIO)    out, idle high   FPGA spi_slave cs_n   (driven by software, not the SPI block)
 *  FPGA_PROGRAMN        6    SIO           out, idle high   ECP5 PROGRAMN  (low pulse restarts configuration)
 *  FPGA_INITN           7    SIO           in, pull-up      ECP5 INITN     (open drain, high = ready for bitstream)
 *  FPGA_DONE            8    SIO           in, pull-up      ECP5 DONE      (high = configured)
 *  FPGA_IRQ             9    SIO           in               FPGA result-ready / frame-done (optional, polled today)
 *  LED_STAT            10    SIO           out              status LED
 *  FB_D0..FB_D7        16-23 PIO0          in               FPGA frame bus data (rtl/mask_stream.v mcu_d[0..7]); D0 must be the PIO IN base
 *  FB_CLK              24    PIO0          in               FPGA frame bus strobe (mcu_clk) = IN base + 8
 *  FB_FS               25    SIO           in (IRQ)         FPGA frame bus packet-valid level (mcu_fs)
 *  FPGA_CFG_SCK        14    SPI1 SCK      out              ECP5 CCLK   (slave SPI configuration port)
 *  FPGA_CFG_MOSI       15    SPI1 TX       out              ECP5 MOSI   (SI)
 *  FPGA_CFG_MISO       12    SPI1 RX       in               ECP5 MISO   (SO)
 *  FPGA_CFG_CSN        13    SIO           out, idle high   ECP5 CSSPIN / SN
 *  BOOT button         --    BOOTSEL       in               dedicated QSPI_SS pin, not a GPIO (used only by the boot ROM)
 *
 * SPI1 pin function check (RP2350): GPIO12 = SPI1 RX, GPIO13 = SPI1 CSn (used as plain GPIO here), GPIO14 = SPI1 SCK,
 * GPIO15 = SPI1 TX.  SPI0: GPIO2 = SCK, GPIO3 = TX, GPIO4 = RX, GPIO5 = CSn (plain GPIO here).
 */
#pragma once

#define PIN_FPGA_SPI_SCK    2
#define PIN_FPGA_SPI_MOSI   3
#define PIN_FPGA_SPI_MISO   4
#define PIN_FPGA_SPI_CSN    5
#define PIN_FPGA_PROGRAMN   6
#define PIN_FPGA_INITN      7
#define PIN_FPGA_DONE       8
#define PIN_FPGA_IRQ        9
#define PIN_LED_STAT        10
#define PIN_FB_D0           16     /* ... PIN_FB_D0 + 7 = 23 */
#define PIN_FB_CLK          24     /* must equal PIN_FB_D0 + 8: frame_rx.pio waits on 'pin 8' */
#define PIN_FB_FS           25
#define PIN_FPGA_CFG_SCK    14
#define PIN_FPGA_CFG_MOSI   15
#define PIN_FPGA_CFG_MISO   12
#define PIN_FPGA_CFG_CSN    13

#define FPGA_SPI_INST       spi0
#define FPGA_SPI_HZ         (12u * 1000u * 1000u)     /* rtl/spi_slave.v: SCK <= clk/6 (16 MHz at 100 MHz) */
#define FPGA_CFG_SPI_INST   spi1
#define FPGA_CFG_SPI_HZ     (25u * 1000u * 1000u)     /* ECP5 slave SPI: up to 60 MHz; keep margin for the board */

/* Flash layout (16 MB QSPI):
 *   0x000000 - 0x0FFFFF   firmware image (1 MB)
 *   0x100000 - 0x3FFFFF   FPGA bitstream partition (3 MB, header + raw .bit, see fpga_config.h)
 *   0xFFE000 - 0xFFFFFF   two 4 KB configuration slots (field map + calibration), see hal_flash.c
 */
#define FLASH_TOTAL_BYTES        (16u * 1024u * 1024u)
#define FLASH_BITSTREAM_OFFSET   0x00100000u
#define FLASH_BITSTREAM_MAX      0x00300000u
#define FLASH_CONFIG_OFFSET      (FLASH_TOTAL_BYTES - 2u * 4096u)
