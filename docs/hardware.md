# Hardware

PCB: 48 x 48 mm, 4 layers (F.Cu signal / In1 GND plane / In2 3V3 plane / B.Cu signal), 1.6 mm, generated from
`pcb/design.py` (netlist + placement) by `pcb/build_pcb.py` (KiCad 10 Python API) and routed with Freerouting.
`pcb/pcb_params.json` is the mechanical contract shared with the housing.

| side | parts |
|---|---|
| top (lens side) | OV9281 (bare CSP) at (0,+9), M12 lens holder footprint (CLA021-LCP, 17x17 body, 20 mm screw spacing, two holes at (+-10, 9); the 2.6 mm holes are too large for the M1.6 screw heads, see `housing/README.md`), PWR + STAT LEDs (at (-21.5, -6.5) / (-21.5, -9.5) with their 1k resistors, under the flat part of the housing roof; the front cover has an engraved power symbol above the PWR light pipe and an engraved heartbeat/pulse symbol below the STAT light pipe) , 4 M2 mounting holes |
| bottom | ECP5 BG381 = LFE5U-25F-8BG381I (since 2026-11-01; same footprint as the 45F and 85F) at (0,-8), RP2350A, 16 MB QSPI flash, USB-C (left edge), all regulators, decoupling, JTAG header, test points, BOOTSEL button |

## Block / power tree

```
USB-C VBUS --ferrite--> +5V --+-- TLV62569 buck --> +3V3 (MCU, flash, FPGA banks 2/3/6/7/8, LDO inputs)
                              +-- TLV62569 buck --> +1V1 (ECP5 core, 20 balls)
+3V3 --+-- ME6211C25 LDO --> +2V5 (ECP5 VCCAUX)
       +-- TLV75518 LDO --> +1V8 (ECP5 banks 0/1/7 = MIPI + sensor control, 24 MHz oscillator, sensor DOVDD)
       +-- ME6211C28 LDO --> +2V8 (sensor AVDD/EVDD, via ferrite)
       +-- TLV75512 LDO --> +1V2 (sensor DVDD/PVDD, via ferrite)
RP2350 internal buck (VREG_LX, 3.3 uH) --> +1V1MCU (DVDD)
```
Power budget (typical): FPGA core ~0.4 A @1.1 V, aux 0.1 A, MCU ~50 mA, sensor ~120 mA -> about 1.1 W from 5 V (USB 2.0
limit 2.5 W). (These figures are from the original design; with architecture A3 the FPGA is smaller and the MCU busier - no new power estimate was made.) The USB-C receptacle presents 5.1 kOhm Rd on CC1/CC2 (default-power sink).

## FPGA pin plan (`tools/pins.py`, single source for the LPF and the PCB netlist)

| signal | ball | bank / standard | notes |
|---|---|---|---|
| `MIPI_CLK_P/N` | F2 / E2 | bank 7 (left), LVDS | `PCLKT7_0`: edge-clock capable pad, source of the DDR edge clock (IDDRX2F 4:1 gearing exists only on left/right banks - found by nextpnr) |
| `MIPI_D0_P/N` | G3 / F3 | bank 7, LVDS | |
| `MIPI_D1_P/N` | H4 / G5 | bank 7, LVDS | |
| 100 ohm across each pair | | | at the FPGA balls (D-PHY HS termination) |
| `CLK24M` | D12 | bank 1, 1.8 V | 24 MHz 1.8 V oscillator -> PLL (100 MHz core, 24 MHz sensor XVCLK) |
| `XVCLK`, `XSHUTDN`, `SCL`, `SDA` | B13, C13, A12, A13 | bank 1, 1.8 V | I2C pull-ups 2.2 k to 1.8 V |
| `SPI_SCK/CS/MOSI/MISO`, `FPGA_IRQ`, `FPGA_RST` | E16, E17, E18, F16, F18, G16 | bank 2, 3.3 V | to the RP2350 SPI0 |
| `FB_D0..FB_D7`, `FB_CLK`, `FB_FS` | P1 N1 M1 L1 K1 P2 N2 L2, K2, M3 | bank 6, 3.3 V | frame bus (mask + candidates) to the RP2350 GPIO16..23, 24, 25 (PIO + DMA) |
| `LED_STAT`, spare LEDs | D18, D19, E19, F19 | bank 2 | |
| configuration | CFG[2:0] = 001 (slave SPI) | bank 8 | RP2350 loads the bitstream (SPI1) after power-up: PROGRAMN, INITN, DONE, CCLK, MOSI (W2), MISO (V2), CSSPIN (R2) |
| JTAG | TCK T5, TMS U5, TDI R5, TDO V4 | | 1.27 mm 2x5 header |

## OV9281 connection (ball map from the Antmicro OV9281 dual camera board, open hardware)
Rails: DOVDD 1.8 V, AVDD/EVDD 2.8 V, DVDD/PVDD 1.2 V (ferrite-filtered, 100 nF + 1 uF each), VH/VN1-3 1 uF to GND,
EGND/AGND/DOGND to ground. MIPI lanes `MDP0/MDN0`, `MDP1/MDN1`, clock `MDCP/MDCN` to the FPGA bank 0 pairs.
`XVCLK` from the FPGA PLL (24 MHz), I2C address 0x60, `XSHUTDN` from the FPGA.

## Things that must be checked before ordering boards
These are limits of what could be verified without the physical parts and the vendor documents; they are listed
rather than hidden:
1. **OV9281 CSP footprint** (`OV9281_CSP` in `build_pcb.py`): the ball *map* comes from the open-hardware reference
   design above, but the ball *pitch* (0.5 mm) and pad size (0.25 mm) are assumptions. Replace with the dimensions from
   OmniVision's package drawing. Bare-CSP sensor assembly with a lens holder also needs a specialist assembler
   (active alignment/focus); the optical stack (M12, CIL023 f = 2.2 mm, 82 deg rectilinear HFOV, CLA021 holder) is in `housing/README.md`.
2. **ECP5 IDDRX2F bit order and the D-PHY SoT hunt** are verified against a behavioural model only. The receiver tries
   both nibble orders so it does not depend on the convention, but it has not been run on silicon; bring-up should start
   with the `status`/lock bits of `dphy_rx` (LED) and the CSI-2 ECC/CRC counters in the registers.
3. **No external schematic capture**: the design is netlist-first (`pcb/design.py`); `pcb/output/netlist.txt` and
   `bom.csv` are generated from it. ERC-style checks (single-pin nets, power pin coverage) are in `tests/test_pcb.py`.
4. The RP2350 slave-SPI FPGA configuration opcodes (`firmware/rp2350/fpga_config.c`) come from memory of Lattice
   TN1260 and are unverified.

## Architecture A3 board status (2026-11-01, production-readiness pass)

`pcb/design.py` (netlist source of truth) has U1 = `LFE5U-25F-8BG381I` (value changed from the 45F on 2026-11-01 for stock reasons; same CABGA-381 footprint, no re-route; `tools/pin_compat.py`: all 31 used balls have the same bank and
pad function as on the 85F) and the 10 frame-bus nets `FB_D0..FB_D7`, `FB_CLK`, `FB_FS` (FPGA bank 6 outer ball row facing the MCU <-> RP2350 GPIO16..25). The board
was re-routed completely with the repository's grid router (`pcb/route_sweep.py`, seed 128).

Production pass (`pcb/fix_power_links.py`, `pcb/apply_prod.py`, `tests/test_pcb_erc.py`):

- **Unconnected items.** KiCad DRC reported 10 unconnected items. They were not harmless: the router treats "pad + via" as connected to the +3V3 plane on In2, but In2 also carries
  signals and the +1V1 island, and the +3V3 pour is cut into islands by the BGA via lattice and by signal tracks. Six +3V3 pad clusters (U1 balls L6/L7/M6, P9, P10, L14/L15/M15, capacitors C2, C4,
  resistor R2, and **U2 pads 20 and 11, two RP2350 IOVDD pins**) hung on vias that touch no pour and so were electrically floating, and two GND pairs (C48 pad 2, U1 P11/P12 vias) were
  likewise split. They were fixed with short single-net links found by an A* search on a 0.05 mm grid (vias 0.45/0.2 mm, hole clearance 0.25 mm respected), plus a local re-route of one
  signal (QSPI_SD0) that blocked the escape of U2 pad 20. **After: 0 unconnected items, no clearance / short / hole violations.**
- **Dangling vias (24 left, was 26).** These are plane-stitch vias at power pads whose pad is connected by other copper (DRC reports no unconnected item for them); harmless.
- **Remaining DRC items** are silk overlap (9), silk over copper (32), dangling vias (24), 2 library-footprint warnings (sensor and lens-holder placeholders): all cosmetic.
- **Lens holder screw holes** are 1.9 mm (M1.6 self-tapping screws bear on the FR4); they were 2.6 mm.
- **Parts**: flash label `W25Q128JVPIQ` (WSON-8 package), LDOs U6/U8 = `ME6211C25M5G-N` / `ME6211C28M5G-N` (same SOT-23-5 pinout, in stock), crystal load check in `docs/bom/bom.json`
  (CL = 15*15/30 + 3 pF stray = 10.5 pF for the 10 pF ABM8-272-T3).

How it got there: an incremental route (`pcb/route_a3.py`, `pcb/ripup_region.py`: keep all other copper, rip up the 20-25 signal nets crossing the MCU's left/bottom
escape area, re-route with `pcb/router/router14.exe`) routed only 9 of the 10 nets whichever MCU pad, FPGA ball or seed was used (the 7th data bit stayed open;
Freerouting 2.1.0 with fixed copper timed out). The full re-route found complete solutions on a minority of seeds; seeds 11, 36 and 128 had no router violations and
128 had the best KiCad DRC (11: 73 + 15, 36: 75 + 23). One router flaw is patched after the fact: the +1V1MCU stub on the 0.2 mm DVDD pad is narrowed from 0.3 to
0.2 mm (clearance to the neighbouring QFN pads); `pcb/router/export_problem.py` now also treats In2 copper as an obstacle (needed for incremental routing).
The 3D renders and the site PCB pages were regenerated from the new board.

## Firmware image build (RP2350)

The firmware (`firmware/rp2350`: `atapp`, `atframe`, `attpu`, `atpose`, `frame_rx.pio`, TinyUSB CDC) builds into `apriltag_cam.uf2/.elf/.bin` with Pico SDK 2.1.1 and
arm-none-eabi-gcc 13.2.1 on Linux (CI: `.github/workflows/firmware.yml`; release: `tools/build_all.sh`). The build host must be Linux: the Windows msys
`ld` 2.47 rejects the SDK linker script ("pico_flash_region.ld appears multiple times"). See the README section "Build and release" for the commands.
`tools/fw_size.py` reports the image against the limits: flash 16 MB (fitted W25Q128), SRAM 520 KB. Sizes are posted on every firmware PR (see the comment
of the `firmware` workflow); they are static allocation only, with no stack-depth or runtime measurement.
Not verified (no hardware in the project): PIO frame capture on GPIO16..25, 21 MB/s frame bus timing and margin, DMA versus CPU SRAM contention,
USB enumeration, BOOTSEL flashing of the `.uf2`, FPGA slave-SPI configuration from the RP2350.
