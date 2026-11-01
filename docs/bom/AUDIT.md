# BOM audit, 2026-10-29

Scope: `docs/bom/bom.json` (rendered to `docs/bom/index.html` by `build_bom.py`) against `pcb/output/bom.csv`,
`pcb/design.py`, `pcb/output/apriltag_cam.kicad_pcb`, `housing/README.md`, `pcb/pcb_params.json`, `docs/hardware.md`.
Prices and stock were re-read on 2026-10-29. Method notes are at the end.

**Status note (2026-11-01):** this is the dated audit record. Since then: U1 is LFE5U-25F-8BG381I (not the 85F or 45F named below), U6/U8 are ME6211C25M5G-N / ME6211C28M5G-N (not TLV75525/TLV75528), the flash label is W25Q128JVPIQ, the lens is CIL023 (82.2 deg HFOV) on CLA021-LCP. Current parts and prices: `docs/bom/bom.json`, `docs/bom/PRODUCTION.md`.

## 1. Cross-check of the four sources

| Check | Result |
|---|---|
| `design.py` `bom()` groups vs `bom.csv` (38 groups, value + footprint + designators) | identical |
| KiCad PCB (152 footprints) vs `bom.csv`, per reference (value + footprint) | identical. Only difference: parts deliberately not in the BOM (U10 sensor, LH1 holder, 4 mounting holes, 10 test points) |
| `bom.json` designators/qty vs `bom.csv` | every one of the 150 BOM designators appears exactly once, quantities match (e.g. 46x 100n, 12x 1u, 6x 10k) |
| `bom.json` value/package vs `bom.csv` footprint | all match (0402/0603/0805 sizes, 1008 inductors, SOT-23-5/6, caBGA-381, QFN-60, WSON-8) |

So the designator/quantity/footprint data in `bom.json` was not stale. The staleness was in prices, stock and a few MPNs (below).

## 2. Discrepancies found

| # | Item | Finding | Action |
|---|---|---|---|
| 1 | U1 LFE5U-85F-8BG381C | LCSC price is now USD 100.13 (1+) / 96.85 (10+), stock 8 pcs; BOM said 36.31 / 1 pc. Single-board total moves by about USD 64. Mouser (about 33.41, 0 stock) and DigiKey (38 pcs, about USD 80, 40 weeks) could not be fetched. | Price/stock updated; other channels left as aggregator snapshots in the note. |
| 2 | U3 flash | LCSC/JLC price is USD 3.42 (1+), not 0.8679. Separately the design value `W25Q128JVSIQ` (SOIC-8 208mil) does not match the WSON-8 footprint; `W25Q128JVPIQ` is right. | Price fixed. **Open:** `pcb/design.py` value label (and thus bom.csv/netlist/KiCad) still says JVSIQ. |
| 3 | Y1 12 MHz crystal | `ABM8-12.000MHZ-D2Y-T` is an 18 pF load crystal (LCSC); C15/C16 are 15 pF (about 10-12 pF effective with stray), which fits a 10 pF part. | MPN changed to `ABM8-272-T3` (LCSC C20625731, 12 MHz, 10 pF, USD 0.66, stock 845). Alternative: keep the 18 pF crystal and change C15/C16 to ~27-33 pF. Design owner should confirm. |
| 4 | U6 TLV75525PDBVR, U8 TLV75528PDBVR | Stock 0 at both LCSC and JLC. | Flagged "hard to source" with the other-package alternates found (WSON-6 / X2SON; a SOT-23-5 TLV75528PDYDR pinout was not checked). Not swapped: needs a footprint decision. |
| 5 | R10 453k | `RC0402FR-07453KL`: LCSC stock 0, JLC stock 1. | Swapped to UNI-ROYAL `0402WGF4533TCE` (C27009, 453k 1% 0402, stock 636k). Same electrical spec, no layout change. |
| 6 | R8/R9 27R (`RC0402FR-0727RL`) | LCSC stock 0, but JLC stock 48,785. | Kept, noted. |
| 7 | L1 3.3 uH | Was an unverified DigiKey-only suggestion. The same Murata part exists on LCSC (C2041573, Isat 2.8 A, 110 mOhm, 1008, stock 3,210). | Now verified at USD 0.197. |
| 8 | Other LCSC prices | Re-read for all 33 LCSC lines. Most moved by <5%. Notable: RP2350A 1.68 -> 1.30, 10k resistor 0.0021 -> 0.0028, USB-C, LDOs etc. within a few percent. | All updated, `checked` = 2026-10-29. |
| 9 | LCSC link for U1 | Pointed at a `product-image` page. | Replaced with the `product-detail` URL. |
| 10 | LH1 lens holder CLA020 | Commonlands: **out of stock**; it is **10.0 mm tall** (the repo assumes 6.0 mm: `pcb_params.json` `height_above_board`, housing README "lens holder 6 mm", barrel top 20.0 mm above PCB) and takes **M1.6** self-tapping screws (repo: "two M2.6 holes", 2.6 mm NPTH in `build_pcb.py`). 20 mm hole spacing matches. | Entry verified (USD 4.50) but flagged out of stock with an in-stock alternative, CLA021-LCP (20 mm spacing, 7.4 mm, 17x17 mm, M1.7, 1,074 pcs, USD 4.50). **Open:** mechanical re-derivation (see section 4). |
| 11 | Holder screws | 2 screws for the holder were not listed anywhere. | Added line `CLA904-SCR` (M1.6x5, pack of 25 at USD 12.00, 0.48 each). Hole/head fit open (2.6 mm hole vs ~3 mm M1.6 pan head). |
| 12 | PCB fab fee | The USD 2.00 "from" price is the 1-2 layer price, not 4-layer 48x48. | Price removed, line unverified. Forum anecdote of ~USD 9.55 for 5 x 100x100 mm 4-layer (2024) noted only as an order of magnitude. Needs a live JLCPCB quote. |
| 13 | Filament | MatterHackers page text shows no price (21.99 only from a search snippet). | Demoted to unverified. Housing also needs 2 x 7.5 mm clear filament (light pipes), not listed (negligible). |
| 14 | M2x10 screws (Zoro ZSCRW-213) | Page returns 403; USD 11.75 per 100 only from a search snippet. M2 pan head may exceed the 3.8 mm head limit in the housing. | Stays unverified. |
| 15 | Heat-set inserts SZTB1091 | LCSC says "M2*3*4"; housing wants OD 3.2 x 4. | Set to unverified (dimensions unclear). Optional part. |
| 16 | JLCPCB assembly fees | Re-read from the help page: setup 51.12, stencil 16.42, feeder 1.53/line, placement 0.0016/joint (all unchanged). Joint count: 771 pads of BOM-listed parts in the KiCad file (was ~800 estimate). | Quantity changed to 771, still unverified (JLCPCB counts joints itself). |
| 17 | FB1 BLM18AG601SN1D | 500 mA rating on the 5 V path; board draw about 0.22 A (docs/hardware.md: ~1.1 W) leaves about 2x margin, inrush not analysed. | Noted only. |
| 18 | OV9281 U10 | LCSC C5354447 lists OV9281 at a placeholder price (USD 0.0398, 0 stock); JLC entries are assembly placeholders. GoPhotonics link returns 403. | Remains quote-only/unverified. |

Checks that passed (electrical sanity, from LCSC attributes): capacitor voltage ratings (100n 16 V X7R, 4u7/2u2 16 V X5R,
1u 50 V, 10u/22u 25 V, 15p C0G 50 V), TLV62569 feedback dividers (453k/100k -> 3.32 V, 82k5/100k -> 1.10 V),
inductor currents (2.2 uH Isat 3.6 A for a 2 A buck; 3.3 uH Isat 2.8 A), LFE5U-85F core range 1.045-1.155 V vs the 1.1 V rail,
USBLC6-2SC6 17 V clamp, USB-C 16-pin receptacle, 12/24 MHz oscillator package (3225 4-pad).
Not checked: pad geometry of J2 header and the Abracon ASE oscillator footprint vs the YXC part, OV9281 CSP ball pitch (assumed in docs).

## 3. Lens (Task B)

**Which lens is meant.** The repo never mentions M15. `grep` for `M15` only hits ball names in FPGA pin tables and KiCad files.
Everything (docs/hardware.md, housing/README.md, pcb_params.json, bom.json, README) specifies an **M12x0.5 (S-mount)** lens,
f = 1.92 mm, 90 deg HFOV, on a CLA020-class M12 board holder. "M15" is almost certainly a typo for M12. No M15-threaded lens
is needed; M12x0.5 is the thread of the holder.

**Requirement.** OV9281: 1/4", 1280x800, 3 um pixels, active area 3.84 x 2.40 mm, diagonal 4.53 mm. Rectilinear HFOV = 2 atan(1.92 / f),
so f = 1.92 mm gives exactly 90 deg. The lens needs M12x0.5, an image circle of at least 4.53 mm, and a body that fits the 14 mm barrel / 15 mm bore.
The repo does not say whether to filter IR. The sensor is NIR-enhanced, printed tags can lose contrast in NIR, so a 650 nm IR-cut variant is the safer default; the no-filter variant is available at the same price.

**No exact 1.92 mm catalog lens exists** among the sellers checked. Candidates (HFOV computed as 2 atan(1.92/f); real HFOV differs with distortion):

| # | Lens | Seller / link | Price, stock (2026-10-29) | f | HFOV (rect.) | Distortion / image circle | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | **CIL018-F2.8-M12B650** (also `...M12BNIR` no IR-cut) | [Commonlands](https://commonlands.com/products/low-distortion-m12-lens) | USD 39.00, both variants in stock | 1.8 mm, f/2.8 | **93.7 deg** (V 67.4, D 103.1) | -14% (barrel), image circle 6.8 mm, covers 4.53 mm | **Recommended.** Nearest to 90 deg, in stock, exact price. Needs a 9-13 mm holder (CLA020, 10 mm). Housing half-diagonal 49.7 deg -> 51.5 deg, still clear (about 2.1 mm margin at the 15 mm bore). |
| 2 | CIL023-F2.2-M12B650 | [Commonlands](https://commonlands.com/products/wide-angle-no-distortion-m12lens) | USD 39.00, B650 in stock (BNIR out of stock) | 2.2 mm, f/2.2 | 82.2 deg (V 57.2, D 91.7) | -5% TV, circle 7.2 mm | Fallback if 90 deg is not critical. Lists 6-9 mm holders, so it pairs with the 7.4 mm CLA021-LCP (close to the housing's 6 mm). |
| 3 | Arducam LN014 / M40210M09S | [RobotShop](https://www.robotshop.com/products/arducam-1-4-m12-mount-21mm-focal-length-low-distortion-camera-lens) (welectron also sells it, 12.90 EUR incl. VAT, ~3 month delivery) | USD 12.62, in stock (RobotShop) | 2.1 mm, f/2.2 | 84.8 deg | <1%, 1/4" format; image circle not published, so coverage of the 4.53 mm diagonal is unconfirmed; 650 nm IR filter | Cheapest, lowest distortion; risk of vignetting at the corners. Price/stock from a third-party page only. |
| 4 | CIL024-F2.2-M12A650 "Low Distortion 2mm" | [Commonlands](https://commonlands.com/products/low-distortion-2mm-m12-lens) | USD 39.00, A650 in stock | "2 mm" (title) | 87.8 deg if EFL is exactly 2.0 mm | spec table could not be read; not in Commonlands' OV9281 table | Promising but unverified: ask Commonlands for EFL/distortion/circle. |
| 5 | Edmund 1.9 mm f/2 no-IR-cut micro video lens (#18-818) | [Edmund](https://www.edmundoptics.com/p/19mm-fl-no-ir-cut-filter-f2-micro-video-lens/18818/) | price not read (page behind Cloudflare) | 1.9 mm | search snippet lists 118 deg HFOV | distortion not stated | Rejected: far wider than 90 deg. |

Also rejected: Commonlands CIL819 (1.9 mm, -22% TV, 160 deg); Framos 1.93 mm lens (about 125 deg, -12.9%, from a search snippet);
Arducam OV9281 module lenses (not sold separately with a known FOV). Sunex DSL lenses were searched: no 1.9-2.1 mm 1/4" part found; Framos resells them with quote-only pricing.
AliExpress/Amazon/Mouser/DigiKey were not fetchable and no equivalent 1.92 mm lens turned up in search.

**BOM entry.** Lens line = CIL018-F2.8-M12B650, USD 39.00, status verified (exact MPN, link, explicit price, stock). It is the nearest
in-stock match, not an exact 1.92 mm / 90 deg lens; if exactly 90 deg rectilinear is wanted, ask Commonlands for a custom or untested EFL via their custom lens design service. Lens distortion (-14%) must be calibrated by the host (the host pipeline already undistorts using the lens calibration).

## 4. Unresolved

1. **Housing height** (Mechanical). The housing and `pcb_params.json` assume a 6.0 mm holder with a 14 mm lens above it (top at 20.0 mm above the PCB, hood rim at 20.3 mm). CLA020 is 10.0 mm; CLA021 is 7.4 mm. Re-derive lens-top height with the actual lens mounting depth from the CIL018 drawing and update `housing/README.md`, `pcb_params.json`, `tests/test_housing.py` expectations.
2. **Holder screws and holes.** CLA020 takes M1.6 (CLA021: M1.7) self-tapping screws, the PCB footprint has 2.6 mm holes. Verify head diameter vs hole and the screw length through 1.6 mm FR4 (check the CLA020 .STP).
3. **CLA020 out of stock** at Commonlands; no other seller checked.
4. `pcb/design.py` flash value `W25Q128JVSIQ` -> `W25Q128JVPIQ`; `BLM18` ferrite labels; regenerating `bom.csv`/netlist/KiCad is outside this audit.
5. Y1 crystal vs C15/C16 load capacitance: confirm the ABM8-272-T3 choice (or change the caps) and, if kept, update the design label (`12MHz`).
6. U6/U8 LDOs out of stock (LCSC and JLC); decide on a substitute and footprint.
7. U1 price (USD 100 on LCSC) and 8-pc stock: DigiKey/Mouser not verifiable here; the single-board total is dominated by the FPGA.
8. OV9281 bare CSP: quote-only; CSP ball pitch/pad size assumptions still need the OmniVision drawing.
9. Unverified lines: OV9281, Zoro M2x10 screws, SZTB1091 inserts, filament, 4-layer PCB fee, SMT joint count.

## Method notes

- LCSC data: `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=Cxxxx` (price ladder, stock, package, attributes). JLC library type and stock: JLCPCB parts search API. Both are the vendors' own site data, read 2026-10-29.
- Commonlands: `products.json` and product page text (price, availability, specs, FOV table for the OV9281).
- Not fetchable (403/timeout/Cloudflare): DigiKey, Mouser, Zoro, GoPhotonics, Edmund. Their figures only come from search snippets and are marked as such.
- Per-row price rule: the LCSC tier at the largest quantity break not above the quantity needed, or the minimum order quantity.

## 5. Hardware and filament prices (follow-up, 2026-10-29)

Read in a real browser or via the seller's JSON, price stated on the page. Housing needs per board: 4 screws M2 x 10 (head <= 3.8 x 1.4 mm), 4 optional heat-set inserts (4.0 mm pilot depth, 3.2 mm pilot), 2 holder screws M1.6 x 5, about 18 g filament. Pack accounting: unit_price = pack price / pack size, qty = per-board need, one pack must be bought.

| Item | Old | New | Source |
|---|---|---|---|
| M2 x 10 screws (qty 4) | Zoro ZSCRW-213, 0.1175, unverified (snippet, 403) | uxcell M2x10 button head, 304 SS, head 3.4 x 1.3 mm, 100 pk USD 9.99 = 0.0999, **verified**, Amazon B011BNTAAU (4 in stock) | https://www.amazon.com/dp/B011BNTAAU |
| Heat-set inserts (qty 4, optional) | XHHD SZTB1091 / LCSC C51938904, 0.0143, unverified ("M2*3*4") | uxcell M2 x 4 mm L x 3.5 mm OD, 100 pk USD 7.69 = 0.0769, **verified**, Amazon B0CTCQ6MHK (13 in stock) | https://www.amazon.com/dp/B0CTCQ6MHK |
| Filament (18 g) | 0.3958 (21.99/kg, snippet), unverified | MatterHackers Polymaker PolyLite PLA Black 1.75 mm 1 kg USD 19.99 (InStock) = 0.3598, **verified**; Polymaker store PA02001 also 19.99 | https://www.matterhackers.com/store/l/polymaker-polylite-pla-black-175mm-1kg/sk/M3RRH23H |
| M1.6 x 5 holder screws (qty 2) | CLA904-SCR 0.48, verified | unchanged: USD 12.00, in stock; head diameter still not published | https://commonlands.com/products/phillips-m1-6x5-thread-forming-screws-for-plastic-25 |

Fit findings:
* **Zoro M2 Phillips pan screw does not meet the housing limits.** Zoro page (read in a browser, USD 12.39 per 100, in stock) gives head 4 mm x 1.7 mm; housing/README.md allows <= 3.8 mm and the underside counterbore is 4.4 x 1.4 mm deep, so the head would stand 0.3 mm proud. Replaced by a button head (3.4 x 1.3 mm). Alternative: keep pan head and deepen the counterbore to 1.8 mm (`head_cb_h`).
* **Inserts.** The LCSC part "M2*3*4" has no stated OD/length. Standard M2 inserts are 3.5 mm OD x 4 mm and are installed in a 3.2 mm hole, which matches `pilot_d = 3.2` and the 4.0 mm pilot depth, so the 3.2 in the README is the hole, not the insert OD. The 5 mm long inserts (e.g. spool3d.ca 3.5 x 5) would not fit the 4.0 mm pilot.
* **Holder screws.** M1.6 pan head is about 3 mm (not published by Commonlands); the PCB hole is 2.6 mm, so the head bears only about 0.2 mm all round. Check against the CLA020 drawing.
* McMaster-Carr requires a login to show prices and Bolt Depot/Fastenal/Digi-Key blocked automated access, so they were not used.

## 6. Update 2026-10-31: optics and housing production readiness (branch housing-optics)

Decisions (sources: Commonlands product pages and products.json read 2026-10-31):
* **Lens changed to CIL023-F2.2-M12B650** (EFL 2.2 mm, 82.2 deg rectilinear HFOV, -5 % TV, 7.2 mm image circle, USD 39.00, 270 in stock). Reason: the section 3 recommendation CIL018 needs a 9 to 13 mm tall holder ("Both variants require a 9mm-13mm tall M12 holder"), and the in-stock 20 mm-spacing holder CLA021-LCP is 7.4 mm; CLA020-PC (10 mm) is out of stock. CIL023 lists "6mm-9mm Tall Holder" and fits the CLA021. A 20 mm hole spacing is fixed by the PCB; the 18 mm holders (CLA018 8.4 mm, CLA019 12 mm) and the 22 mm CLA024 (12 mm) do not match it.
* **Holder changed to CLA021-LCP** (7.4 mm, 17 x 17 mm, M1.7 holes, USD 4.50, 1074 in stock). The Commonlands M1.6 x 5 screw (CLA904-SCR) states it fits 1.6 and 1.7 mm holes, so it stays.
* **The 90 deg requirement is not in the code.** Pose and calibration code take any fx, fy, cx, cy and k1, k2, p1, p2, k3. Only the simulated dataset (`tools/geom.py`, 640 px, 90 deg) and the housing cone assumed it. CIL023 gives 82.2 deg rectilinear (about 84 to 85 deg with its distortion, estimate). The dataset is not re-rendered.
* **Not available from the vendor:** lens length, back focal length and the holder outline (STP/drawings are behind DocSend forms). The housing uses a 22.0 mm lens-top allowance and an assumed 23 x 6 mm screw-ear envelope, both documented in `housing/README.md` and `pcb/pcb_params.json`. Commonlands does not publish the screw head size either; the housing allows 3.4 x 1.3 mm (ISO 7045 M1.6 is 3.2 x 1.3; a second-hand McMaster 99461A911 listing says 2.6 x 1.1).
* **Open PCB issue (not fixed here):** footprint holes for the holder screws are 2.6 mm. The screws need about 1.9 mm holes or the heads cannot bear on the board.
* Page inconsistencies seen: the CLA021 page title says "7mm Height" and one Commonlands page title says "22mm Hole Spacing" while the body and FAQ say 7.4 mm and 20 mm; the CIL023 page says 125 deg diagonal in the intro and "121 deg @ 7.2mm image circle" in the table.
