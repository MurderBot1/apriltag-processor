# Production sourcing (checked 2026-10-31)

All stock and prices below were read from the vendor's own site on 2026-10-31 (LCSC product API, JLCPCB parts API, Mouser, DigiKey, Arrow, Commonlands, Amazon, MatterHackers, JLCPCB fee page). Raw LCSC/JLC readings: `results/bom_prices_2026-10-31.json`. Anything not read is marked unverified. `docs/bom/bom.json` is the source of truth for the BOM.

## 1. U1 FPGA: stock and the LFE5UM question

### Stock and price of the 45k ECP5 in caBGA-381

| Part | Channel | Stock | Price (USD) | Lead time |
|---|---|---|---|---|
| LFE5U-45F-8BG381C (design part) | LCSC C1551314 / JLC | 0 / 0 | 11.2791 @1, 10.9093 @10 (list, not buyable) | none stated |
| LFE5U-45F-8BG381C | [Mouser](https://www.mouser.com/en/ProductDetail/Lattice/LFE5U-45F-8BG381C) | 0, 90 on order expected 2027-06-15 | 67.15 @1, 58.45 @25 | 46 weeks |
| LFE5U-45F-8BG381C | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-45F-8BG381C/5250568) | 0, 90 expected 2026-11-30 | 56.76 @1, 49.39 @25, 45.76 @100 | 43 weeks |
| LFE5U-45F-8BG381C | [Arrow](https://www.arrow.com/en/products/lfe5u-45f-8bg381c/lattice-semiconductor) | "out of stock" | none shown | none shown |
| LFE5U-45F-8BG381C | Avnet search | "Part Not Found" | | |
| **LFE5U-45F-6BG381C** (speed grade 6) | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-45F-6BG381C/5250564) | **46 in stock** | 46.64 @1, 40.70 @25, 37.62 @100 | 43 weeks (standard) |
| LFE5U-45F-6BG381C | [Mouser](https://www.mouser.com/c/?q=LFE5U-45F-6BG381C) | **5 in stock**, 180 expected 2027-06-15 | 55.20 @1, 48.15 @25 | not read |
| LFE5U-45F-6BG381C | LCSC C1551300 | 0 | | |
| LFE5UM-45F-8BG381C (SERDES) | LCSC C1550814 / JLC | 6 / 6 | 35.28 @1, 34.12 @10 | none stated |
| LFE5UM-45F-8BG381C | [Mouser](https://www.mouser.com/en/ProductDetail/Lattice/LFE5UM-45F-8BG381C) | non-stocked | 77.15 @1, 67.20 @25 | 40 weeks |
| LFE5UM-45F-8BG381C | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5UM-45F-8BG381C/5250574) | 0, 90 expected 2027-05-26 | 65.23 @1, 56.82 @25, 52.58 @100 | 43 weeks |

Not read: Lattice has no stock page on its product page, and Future, Win Source and other brokers were not opened. Aggregator snapshots without a date are not used.

The only stock found for a buildable part today is the speed grade 6 (-6) part: 46 at DigiKey and 5 at Mouser, which covers a 10-board build at most (DigiKey 46). Footprint and balls are the same as the -8 part (same package, same die family). Whether the design closes timing at speed grade 6 is not checked: `docs/fpga.md` reports a core clock of 81.7 to 91.0 MHz at grade 8 and nobody has run place-and-route for grade 6. That must be run before ordering -6.

### Is LFE5UM-45F-8BG381C a drop-in? No, not without a PCB change

Source: Lattice, [ECP5U to ECP5UM caBGA381 Migration CSV](https://www.latticesemi.com/view_document?document_id=52306) (revision 1.0, 2018-03-19, linked from the [ECP5 product page](https://www.latticesemi.com/en/Products/FPGAandCPLD/ECP5)), and the [ECP5U-45 pinout](https://www.latticesemi.com/view_document?document_id=50486). Read 2026-10-31.

1. I/O balls used by this design: `python tools/pin_compat.py LFE5U-45F LFE5UM-45F` (Project Trellis database) reports all 31 balls identical in bank and function.
2. Whole table, ball by ball, from the Lattice migration CSV (381 rows): the LFE5U-45 and LFE5UM-45 columns have the same pin function name on every ball. Only the "Bank" field differs, on 20 balls (the SERDES data and reference clock balls W4, W5, W8, W9, W13, W14, W17, W18, W20, Y5-Y8, Y11, Y12, Y14-Y17, Y19, which show bank 50/51 on the UM part).
3. Lattice's migration note says that the SERDES power pins should be connected on the ECP5U device in the same way as on the ECP5UM so that the part can be swapped. The Lattice ECP5U-45 table names these balls as SERDES supplies: T6 and U6 VCCA0, T15 and U15 VCCA1, T7 VCCHTX0_D0CH0, T8 VCCHRX0_D0CH0, T9 VCCHRX1_D0CH1, T10 VCCHTX1_D0CH1, T11 VCCHTX0_D1CH0, T12 VCCHRX0_D1CH0, T13 VCCHRX1_D1CH1, T14 VCCHTX1_D1CH1, V10 and V11 VCCAUXA0, V17 and V18 VCCAUXA1.
4. This PCB (`pcb/ecp5_85f_bg381_pins.json` via `pcb/design.py`) ties all 16 of those balls to GND (the table lists them as GND). On the UM part these balls are supplies, so grounding them would short the rails (VCCA, VCCHTX, VCCHRX to GND, and VCCAUXA to GND). The 20 SERDES signal and reference clock balls are also tied to GND (W20, Y5-Y8, Y11, Y12, Y14-Y17, Y19) or marked no-connect (W4, W5, W8, W9, W13, W14, W17, W18) on this PCB. W10 and W11 are marked RESERVED in both tables.
5. Result: the UM part is not a drop-in. A board spin would have to route these 16 balls to supplies, and I did not read the datasheet's SERDES power sequencing and filtering rules (FPGA-DS-02012), so I cannot say what the filtering needs. No extra UM ball lands on one of the 31 signal nets of the design.
6. Separate finding: `pcb/design.py` builds the ball plan from a LFE5U-85F pin table (K16 and K17 are `PR29A` and `PR29B` I/O there, but the Lattice ECP5U-45 table lists K16 and K17 as NC). Those two balls are not used by the design (the 31 used balls are checked), but the net list assigns the 85F table to the 45F part. Check this against the Lattice 45F table in the next PCB spin.

Cost: the UM part at LCSC (6 pcs) is 24.00 more per board than the 45F U part, and at DigiKey and Mouser it is more expensive than the -6 part.

## 2. OV9281 (U10) and PCB fab

No seller with an exact MPN, a link and a usable stated price was found for the bare sensor. U10 stays `unverified`.

- Arrow lists [OV09281-H64A](https://www.arrow.com/en/products/ov09281-h64a/omnivision-technologies) (64-pin CSP-5, 4.46 x 5.24 mm, active) with the text "We don't have prices now".
- LCSC and JLC list OV09281-H64A (C5182169), OV9281 and OV9281_CSP5 with stock 0 and prices below USD 0.04 (placeholders, not used).
- Whether the OmniVision ordering code of the sensor used in `pcb/design.py` is H64A is not confirmed. The OmniVision datasheet was not read.
- Fallback with a stated price: finished module Camemake CM-MIPI-OV9281-Universal on [DigiKey Marketplace](https://www.digikey.com/en/products/detail/camemake/CM-MIPI-OV9281-Universal/27525168): 1,000 in stock, ships in about 25 days from Camemake, USD 77.84 @10, 14.01 @500, 12.01 @1,000, 9.01 @5,000. It is a module (not the bare sensor), so using it means a PCB re-spin around a connector.

PCB fabrication: the JLCPCB 4-layer price is not public as a table, and the quote page blocked the browser tool on 2026-10-31. No price was obtained, so the bare PCB is excluded from the totals below. The JLCPCB assembly fee page (last updated 2026-10-22 by JLCPCB) states these Standard double-side fees, used in the totals: setup 51.12, stencil 16.42, feeder loading 1.53 per unique part (37 parts = 56.61), SMT 0.0016 per joint (771 joints, joint count is a repo estimate), hand-soldering labor 3.58 per order. Not included: pre-reflow soldering 0.016 per joint, single-board surcharge 0.48, X-ray 1.64 per piece for 1-10 BGA/QFN parts, shipping, taxes, ENIG and impedance control.

## 3. Stock and EOL flags (all lines re-read 2026-10-31)

| Line | Finding |
|---|---|
| U1 LFE5U-45F-8BG381C | Out of stock everywhere read; see section 1. |
| U6 TLV75525PDBVR | LCSC 0, JLC 0. Only alternate: TLV75525PDRVR WSON-6 (C544744, 1,150, 0.225 @5), different footprint. |
| U8 TLV75528PDBVR | LCSC 0, JLC 0. Alternates: TLV75528PDYDR SOT-23-5 (C35061966, 24 at LCSC, 25 at JLC, 0.2383 @1, pinout not checked) and TLV75528PDRVR WSON-6 (C2865214, 120). |
| Y1 ABM8-272-T3 | LCSC stock 0 (was in stock 2026-10-29), JLC 5. Needs a second source. |
| Y2 O9322524MADA4SI | Low stock: LCSC 114, JLC 114. |
| SW1 PTS810 SJM 250 SMTR LFS | LCSC 327, JLC 852. Fine for 100 boards, thin for more. |
| L1 DFE252012F-3R3M=P2 | LCSC 2,950. Fine for 100 boards. |
| C 1 uF CL10A105KB8NNNC | LCSC 0 but JLC 12,244,708. JLC assembly can source it. |
| R8/R9 RC0402FR-0727RL | LCSC 0 but JLC 48,286. JLC assembly can source it. |
| LH1 CLA020-PC | Sold out at Commonlands (checked 2026-10-31, `available: false`). CLA021-LCP (7.4 mm tall) is available (USD 4.50) but has a different height. |
| U10 OV9281 | No priced seller; see section 2. |
| EOL | No line was found marked EOL or NRND on the pages read. Zenode marks OV09281-H64A as obsolete (search result snippet, page not opened). |

Price changes since 2026-10-29: TLV62569DBVR 0.0698 to 0.0692, USBLC6-2SC6 0.1815 to 0.1816, ABM8-272-T3 0.6647 to 0.6617, TYPE-C-31-M-12 0.1886 to 0.189, BLM18PG121SN1D 0.0149 to 0.0138, CL10A105KB8NNNC 0.0141 to 0.0144, CL21A226MAQNNNE 0.1936 to 0.1915, CL10A225KO8NNNC 0.0123 to 0.012, RC0402FR-0733RL 0.0028 to 0.0027, RC0402FR-0710KL 0.0028 to 0.0019, RC0402FR-075K1L 0.0025 to 0.0028. Commonlands (CLA020-PC 4.50, CIL018 lens 39.00, screws 12.00 per 25), the two Amazon packs (9.99 and 7.69) and the MatterHackers filament (19.99) are unchanged.

## 4. Cost per board at 1, 10 and 100 boards

Method: LCSC price at the largest break not above (qty per board x boards), or the first break. Commonlands prices are flat (no volume tiers were read). Amazon packs of 100 are bought whole. One roll of filament is counted per board (as in `bom.json`). Fixed JLCPCB fees (127.73: setup 51.12, stencil 16.42, feeder 56.61, hand-soldering 3.58) are spread over the boards. FPGA price per board is shown separately. **Excluded: bare PCB, OV9281 sensor, shipping, taxes, other JLCPCB extras (see section 2). The totals are therefore a floor, not a quote.**

| Item (USD per board) | 1 board | 10 boards | 100 boards |
|---|---|---|---|
| Passives/ICs/connectors at LCSC (excl. U1, U10) | 10.62 | 9.63 | 7.84 |
| Lens, lens holder, screws, inserts, filament | 62.50 | 46.59 | 45.53 |
| SMT placement (771 joints) | 1.23 | 1.23 | 1.23 |
| JLCPCB fixed fees, spread | 127.73 | 12.77 | 1.28 |
| Subtotal without FPGA | 202.08 | 70.22 | 55.88 |
| U1 at LCSC list price (0 stock, not buyable) | 11.28 | 10.91 | 10.91 |
| U1 LFE5U-45F-6BG381C, DigiKey (in stock 46, timing at grade 6 unchecked) | 46.64 | 46.64 | 37.62 (more than the 46 in stock) |
| U1 LFE5U-45F-8BG381C, DigiKey (0 stock, 43 weeks) | 56.76 | 56.76 | 45.76 |
| U1 LFE5U-45F-8BG381C, Mouser (0 stock, 46 weeks) | 67.15 | 67.15 | 58.45 |
| **Total with U1 DigiKey -6** | **248.72** | **116.86** | **93.50** |
| **Total with U1 DigiKey -8 (backorder)** | **258.84** | **126.98** | **101.64** |
| Total with U1 at LCSC list (not buyable) | 213.36 | 81.13 | 66.79 |

Notes on the table: the 100-board DigiKey -6 price needs 100 pieces but only 46 are in stock. The lens line dominates small builds (Commonlands lens 39.00 each, flat, no volume price was read). The `bom.json` page total (verified lines only) is generated by `docs/bom/build_bom.py`.

## 5. Risks and second sources

- U1 supply (largest risk). Both exact -8 part and the UM part have 40 to 46 week lead times and 90-piece incoming lots. Second sources: LFE5U-45F-6BG381C (same footprint, in stock in small numbers, needs a timing check). LFE5UM-45F-8BG381C needs a PCB change (section 1).
- U10 OV9281. No priced seller found. Needs a quote from an OmniVision distributor or a module re-spin. This blocks a priced production BOM.
- Bare PCB price. No JLCPCB 4-layer price was obtained. Get a live quote.
- U6 and U8 LDOs are out of stock in the SOT-23-5 package at LCSC/JLC. An alternate in the same package exists only for the 2.8 V part (TLV75528PDYDR, 24 at LCSC) and its pinout is not checked. Plan a footprint change (WSON-6) or buy elsewhere (not read).
- Y1 crystal out of stock at LCSC, 5 at JLC. No alternate was selected.
- LH1 lens holder sold out at Commonlands (restock on request). The 10 mm tall part also does not match the 6 mm height assumed in the housing (see `docs/bom/AUDIT.md`).
- Assembly: BGA and CSP parts and the lens holder need an assembly house that supports them. JLCPCB X-ray is charged per piece.
- Stock numbers move daily. Re-run the script (see `tools/costdown_prices.py`) before placing any order.

## 6. Lead times (only stated facts)

- LFE5U-45F-8BG381C: Mouser 46 weeks, DigiKey 43 weeks (standard), incoming 90 pcs at each (DigiKey 2026-11-30, Mouser 2027-06-15).
- LFE5UM-45F-8BG381C: Mouser 40 weeks, DigiKey 43 weeks.
- LFE5U-45F-6BG381C: DigiKey standard 43 weeks, 46 in stock now.
- Camemake OV9281 module: about 25 days (DigiKey Marketplace).
- All other parts are bought from LCSC/JLC stock. No lead time is stated on those pages, so none is claimed.
