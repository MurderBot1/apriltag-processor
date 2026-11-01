# Production sourcing (checked 2026-10-31)

## Summary: U1 FPGA status (updated 2026-11-01)

- **U1 is now LFE5U-25F-8BG381I** (ECP5, 25k LUT, speed grade 8, industrial -40 to 100 C, same CABGA-381 footprint). It is buyable today: DigiKey 18 in stock (USD 36.85 @1), Mouser 90 in stock (USD 43.60 @1, 35.15 @90). Read on 2026-11-01.
- Why: the design closes timing only at speed grade 8 (`results/fpga_speed_grades.md`; grades 6 and 7 fail the core and D-PHY clocks). The previous part LFE5U-45F-8BG381C is out of stock everywhere (DigiKey 90 expected 2026-11-30, Mouser 90 expected 2027-06-15). The -I (industrial) part is the same speed grade 8 as the -C part; only the temperature range differs.
- **No PCB re-route is needed.** The 25F, 45F and 85F share the CABGA-381 footprint; `tools/pin_compat.py LFE5U-45F LFE5U-25F` and `LFE5U-85F LFE5U-25F` report all 31 used balls identical in bank and function. Supply balls and banks are the same, so only the value text of U1 changes (`pcb/design.py` and the files in `pcb/output/`).
- Design fit: nextpnr-ecp5 on the 25F at speed 8 (pinned OSS CAD Suite 2025-09-01, RTL at main 828bf22): 7 of 7 seeds close both clocks, 13,389 LUT4 (55 %), 56 of 56 block RAM (100 %, no margin). Seed 1 (the default of `tools/build_all.sh`): core 93.81 MHz (need 85.714), D-PHY 211.15 MHz (need 200). Estimates, not signoff. Run: GitHub Actions `fpga-timing` run 41313996641.
- Fallback: LFE5U-85F-8BG381C (same footprint, drop-in, about 2.5 times the price): DigiKey 17 in stock USD 90.70, Mouser 10, LCSC 8. nextpnr 85F speed 8: 6 of 7 seeds close (seed 3 fails the D-PHY clock), 16 % LUT, 26 % block RAM; seed 1 closes (88.17 / 220.95 MHz).
- **LFE5UM-45F-8BG381C (SERDES variant) is NOT a drop-in.** This PCB ties the 16 SERDES supply balls (T6-T15, U6, U15, V10, V11, V17, V18) to GND, but on the UM part they are VCCA, VCCHTX, VCCHRX and VCCAUXA supplies. A PCB change is needed.
- Speed grade 6 and 7 parts (in stock in small numbers) do not close timing and must not be used.

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

The -6 part is in stock but is not usable: speed grade 6 does not close timing (`results/fpga_speed_grades.md`). Section 1a lists the speed-8 parts that can be bought.

### 1a. Speed-8 ECP5 parts in CABGA-381 that can be bought (read 2026-11-01)

Pages read in the browser on 2026-11-01 (DigiKey, Mouser, Arrow, Newark via Findchips) and LCSC/JLC through the LCSC product API. Avnet's search page returned no results for the 25F (not a stock statement) and the Newark/Farnell/element14 product pages did not load (HTTP 403 or empty), so those two were not read directly; Newark's price and stock came from Findchips (0 in stock for the 25F-C). Snippets without a date from search engines are not used.

| Part | Channel | Stock | Price (USD) | Lead time |
|---|---|---|---|---|
| **LFE5U-25F-8BG381I** (chosen) | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-25F-8BG381I/5358092) 220-2056-ND | **18** | 36.85 @1, 32.07 @25, 29.70 @100 | 40 weeks (standard) |
| LFE5U-25F-8BG381I | [Mouser](https://www.mouser.com/c/?q=LFE5U-25F-8BG381I) 842-LFE5U25F8BG381I | **90** | 43.60 @1, 37.95 @25, 35.15 @90 | 40 weeks |
| LFE5U-25F-8BG381I | [Arrow](https://www.arrow.com/en/products/lfe5u-25f-8bg381i/lattice-semiconductor) | out of stock | | |
| LFE5U-25F-8BG381C | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-25F-8BG381C/5358091) 220-2055-ND | 0, 90 expected 2027-08-04 | 33.39 @1, 29.10 @25, 26.95 @100 | 40 weeks |
| LFE5U-25F-8BG381C | [Mouser](https://www.mouser.com/c/?q=LFE5U-25F-8BG381C) | non-stocked | 39.50 @1, 34.45 @25, 31.90 @90 | 40 weeks |
| LFE5U-25F-8BG381C | Newark (via Findchips) | 0 | CAD 33.95 @1 (not USD) | not read |
| LFE5U-25F-8BG381C | [Arrow](https://www.arrow.com/en/products/lfe5u-25f-8bg381c/lattice-semiconductor) | out of stock | | |
| LFE5U-25F-8BG381C | LCSC C1550939 / JLC | 5 / 5 | 44.17 @1, 40.00 @30 (LCSC API); JLC 44.24 @1 | none stated |
| **LFE5U-85F-8BG381C** (fallback) | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-85F-8BG381C/5395911) 220-2077-ND | **17** | 90.70 @1, 78.98 @25, 73.15 @100 | 43 weeks |
| LFE5U-85F-8BG381C | [Mouser](https://www.mouser.com/c/?q=LFE5U-85F-8BG381C) | **10**, 270 expected 2027-05-28 | 107.20 @1, 93.35 @25 | 46 weeks |
| LFE5U-85F-8BG381C | LCSC C1551826 / JLC | 8 / 8 | 100.13 @1, 96.85 @10 | none stated |
| LFE5U-85F-8BG381I | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-85F-8BG381I/5398971) 220-2177-ND | 37 | 99.88 @1, 86.96 @25, 80.58 @100 | 43 weeks |
| LFE5U-85F-8BG381I | Mouser | 1, 90 on order | 118.10 @1, 102.85 @25 | 40 weeks |
| LFE5U-45F-8BG381C (previous) | DigiKey / Mouser / LCSC | 0 / 0 / 0 | see section 1 | 43 / 46 weeks |
| LFE5U-45F-8BG381I | [DigiKey](https://www.digikey.com/en/products/detail/lattice-semiconductor-corporation/LFE5U-45F-8BG381I/5250569) 220-1993-ND | 0, 90 expected 2027-02-09 | 62.37 @1, 54.34 @25 | 43 weeks |
| LFE5U-45F-8BG381I | Mouser | 0, 41 expected 2026-12-28, 90 expected 2027-08-02 | | 44 weeks |

Industrial -I parts (TJ -40 to 100 C per the DigiKey page) have the same speed grade 8 and package as the -C parts (TJ 0 to 85 C), so the pin plan and the nextpnr timing are the same. The price is higher than the -C part where both exist (DigiKey 25F: 36.85 vs 33.39).

Unauthorised brokers: Findchips lists LFE5U-25F-8BG381C with Chip Stock 1,345, Shengyu Electronics 1,954 and Sense Electronic 440, all request-for-quote with no price shown (read 2026-11-01). These are **not authorised distributors**; parts bought there can be counterfeit, remarked or old stock, and they are not used in this BOM. The 25F-8BG381C also appears at other sites in search snippets without a date (for example USD 13 to 20); those were not accepted as prices. If a broker is used anyway, X-ray and decap/electrical test the parts on receipt.

Total stock at authorised channels for the chosen part is 108 pieces (DigiKey 18, Mouser 90), so a 100-board run cannot be built from stock today. DigiKey's 25F-8I shows "check for additional incoming stock"; Mouser's 25F-8I price list quotes 1,080 on request. For larger runs ask DigiKey/Mouser for a quote or order the 85F fallback.

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
| U1 LFE5U-25F-8BG381I | DigiKey 18, Mouser 90 in stock (section 1). The former 45F-8BG381C is out of stock everywhere read. |
| U6 ME6211C25M5G-N | Replaces TLV75525PDBVR (LCSC and JLC stock 0). LCSC C194395: 31,280 in stock (2026-11-01). Pinout and 400 mA checked against the MICRONE datasheet V20 (section 5). |
| U8 ME6211C28M5G-N | Replaces TLV75528PDBVR (LCSC and JLC stock 0). LCSC C53099: 17,280 in stock (2026-11-01). Pinout and 450 mA checked against the MICRONE datasheet V20 (section 5). |
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

Method (generated by `python tools/bom_cost_table.py` from `docs/bom/bom.json` and `results/bom_prices_2026-10-31.json`): LCSC price at the largest quantity break not above (qty per board x boards), or the first break; the two ME6211 LDOs have no ladder in the price file and use the `bom.json` unit price at every quantity. Commonlands lens and holder prices are flat (no volume tiers were read). Screw and insert packs (CLA904-SCR 25 per pack at 12.00, M2 screws 100 per pack at 9.99, inserts 100 per pack at 7.69) are bought whole, rounded up, and spread over the boards. Filament is pro-rated (18 g of a 1 kg roll, 0.36 per board, as in `bom.json`). Fixed JLCPCB fees (127.73: setup 51.12, stencil 16.42, feeder 56.61, hand-soldering 3.58) are spread over the boards. FPGA price per board is shown separately. **Excluded: bare PCB, OV9281 sensor, shipping, taxes, other JLCPCB extras (see section 2). The totals are therefore a floor, not a quote.**

| Item (USD per board) | 1 board | 10 boards | 100 boards |
|---|---|---|---|
| Passives/ICs/connectors at LCSC (excl. U1, U10) | 10.14 | 9.29 | 7.63 |
| Lens, lens holder, screws, inserts, filament | 73.54 | 46.83 | 45.53 |
| SMT placement (771 joints) | 1.23 | 1.23 | 1.23 |
| JLCPCB fixed fees, spread | 127.73 | 12.77 | 1.28 |
| Subtotal without FPGA | 212.64 | 70.13 | 55.67 |
| U1 LFE5U-25F-8BG381I, DigiKey (stock 18; the 25 / 100 tiers need more than that) | 36.85 | 36.85 | 29.70 (needs 100, only 18 + 90 at Mouser in stock) |
| U1 LFE5U-25F-8BG381I, Mouser (stock 90) | 43.60 | 43.60 | 35.15 (90 tier, 90 in stock) |
| U1 LFE5U-85F-8BG381C fallback, DigiKey (stock 17) | 90.70 | 90.70 | 73.15 (needs 100, 17 in stock) |
| **Total with U1 DigiKey 25F-8I** | **249.49** | **106.98** | **85.37** |
| **Total with U1 Mouser 25F-8I** | **256.24** | **113.73** | **90.82** |
| Total with U1 DigiKey 85F-8C (fallback) | 303.34 | 160.83 | 128.82 |

The former rows "U1 45F at LCSC list" (11.28, not buyable, 0 stock) and "45F at DigiKey" (0 stock) were removed: that part cannot be bought. An earlier version of this table showed 62.50 for the mechanical line and 10.62 for the LCSC line at 1 board; those were stale (hand-calculated before the LDO and holder changes) and are replaced by the script output.

### Why the BOM page total differs from this table

The BOM page (`docs/bom/index.html`, built by `docs/bom/build_bom.py`) shows "verified per-board 92.51 + one-time 124.15 = 216.66 (1 board)". This table gives 249.49 for one board with the DigiKey 25F. The difference is 32.83 and is fully accounted for:

| Item | USD (1 board) |
|---|---|
| BOM page total (verified lines only, bom.json unit prices; U1 at 36.85) | 216.66 |
| Packs bought whole instead of per-unit price (screws 12.00 + M2 screws 9.99 + inserts 7.69 = 29.68, versus 0.96 + 0.40 + 0.31 = 1.67 per-unit in bom.json) | +28.01 |
| SMT placement 771 x 0.0016 (line is `unverified` in bom.json: the joint count is an estimate, so the page leaves it out of its total) | +1.23 |
| Hand-soldering labor per order (fee page, not a line in bom.json) | +3.58 |
| This table, 1 board, DigiKey 25F | 249.49 (sum 249.48, rounding) |

The two agree on everything else: LCSC parts (10.14 here equals 14.64 on the page minus the 4.50 holder), lens 39.00, holder 4.50, U1 36.85, fixed fees 124.15 + 3.58 = 127.73. The BOM page uses one fixed unit price per line (the tier noted in each row) and never rounds pack purchases up, so it understates a small build; for 100 boards use this table, which applies the LCSC quantity tiers.

Notes on the table: the 100-board 25F prices need 100 pieces but only 108 are in stock at DigiKey and Mouser together (and the tier prices are per vendor). DigiKey totals at 1 and 10 boards use DigiKey's 1-piece price 36.85 (the 25-piece tier needs 25 pieces). The lens line dominates small builds (Commonlands lens 39.00 each, flat, no volume price was read).

## 5. Risks and second sources

- U1 supply (largest risk). The chosen 25F-8I has 108 pieces in stock at authorised channels (DigiKey 18, Mouser 90) and 40 week lead time for more. Second sources: LFE5U-85F-8BG381C (drop-in, DigiKey 17, Mouser 10, LCSC 8, about 2.5 times the price, timing closes on 6 of 7 seeds) and the LFE5U-45F-8BG381C when it returns (DigiKey 90 expected 2026-11-30). Speed grade 6 or 7 parts do not close timing. LFE5UM-45F-8BG381C needs a PCB change (section 1). The 25F uses 56 of 56 block RAM: any RTL growth in block RAM needs the 45F or 85F.
- U10 OV9281. No priced seller found. Needs a quote from an OmniVision distributor or a module re-spin. This blocks a priced production BOM.
- Bare PCB price. No JLCPCB 4-layer price was obtained. Get a live quote.
- U6 and U8 are now ME6211C25M5G-N and ME6211C28M5G-N (SOT-23-5, LCSC 31,280 and 17,280 in stock on 2026-11-01), replacing the TLV75525/TLV75528 that are out of stock. MICRONE ME6211 datasheet V20 (PDF copies from chipdip.ru and elecfans.com; the LCSC-hosted PDF could not be downloaded) states for SOT23-5: 1 VIN, 2 VSS, 3 CE, 4 NC, 5 VOUT, which matches the board (CE tied to VIN). Maximum output current: 400 mA (C25) and 450 mA (C28); dropout typical 110 mV at 100 mA and 220 mV at 200 mA; VIN maximum 6.5 V; CE high threshold 1.0 V; test condition input and output 1 uF (the board has 1 uF in, 2.2 uF out). Loads: ECP5 VCCAUX (2.5 V, tens of mA) and the OV9281 rail (2.8 V, current not verified). Datasheet shows typical, not guaranteed, dropout. Still to do: compare the revision with the LCSC-hosted datasheet at order time.
- Y1 crystal out of stock at LCSC, 5 at JLC. No alternate was selected.
- LH1 lens holder sold out at Commonlands (restock on request). The 10 mm tall part also does not match the 6 mm height assumed in the housing (see `docs/bom/AUDIT.md`).
- Assembly: BGA and CSP parts and the lens holder need an assembly house that supports them. JLCPCB X-ray is charged per piece.
- Stock numbers move daily. Re-run the script (see `tools/costdown_prices.py`) before placing any order.

## 6. Lead times (only stated facts)

- LFE5U-45F-8BG381C: Mouser 46 weeks, DigiKey 43 weeks (standard), incoming 90 pcs at each (DigiKey 2026-11-30, Mouser 2027-06-15).
- LFE5UM-45F-8BG381C: Mouser 40 weeks, DigiKey 43 weeks.
- LFE5U-25F-8BG381I: DigiKey 40 weeks standard, Mouser 40 weeks; 18 (DigiKey) and 90 (Mouser) in stock on 2026-11-01.
- LFE5U-85F-8BG381C: DigiKey 43 weeks, Mouser 46 weeks.
- LFE5U-45F-6BG381C: DigiKey standard 43 weeks (grade 6, does not close timing).
- Camemake OV9281 module: about 25 days (DigiKey Marketplace).
- All other parts are bought from LCSC/JLC stock. No lead time is stated on those pages, so none is claimed.
