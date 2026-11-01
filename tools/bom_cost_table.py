#!/usr/bin/env python3
"""Cost per board at 1, 10 and 100 boards from docs/bom/bom.json and results/bom_prices_2026-10-31.json.

Rules (printed with the table; same text as docs/bom/PRODUCTION.md section 4):
  * LCSC lines: price at the largest quantity break not above (qty per board x boards), else the first break.
    Lines with no ladder in the price file (ME6211 LDOs) use the bom.json unit price at every quantity.
  * Packs (screws, inserts) are bought whole: ceil(need / pack) packs, cost spread over the boards.
  * Filament is pro-rated (18 g of a 1 kg roll, as in bom.json). Lens and holder are flat.
  * Fixed JLCPCB fees: setup + stencil + feeder (bom.json) + hand-soldering 3.58 (fee page, not in bom.json),
    spread over the boards. SMT placement 771 joints x 0.0016 per board.
  * Excluded: U1 (shown separately), U10 sensor and bare PCB (no price), shipping, taxes, other JLCPCB extras.
Usage: python tools/bom_cost_table.py
"""
import json, math, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bom = json.load(open(os.path.join(ROOT, "docs/bom/bom.json"), encoding="utf-8"))["items"]
lad = json.load(open(os.path.join(ROOT, "results/bom_prices_2026-10-31.json"), encoding="utf-8"))
PACKS = {"CLA904-SCR": (25, 12.00), "B011BNTAAU": (100, 9.99), "B0CTCQ6MHK": (100, 7.69)}
HAND = 3.58
N = (1, 10, 100)


def tier(l, need):
    p = l[0][1]
    for q, pr in l:
        if q <= need:
            p = pr
    return p


def cost(boards):
    ics = mech = fixed = smt = 0.0
    for it in bom:
        mpn, q, up = it["mpn"], it["qty"], it["unit_price"]
        if it["status"] != "verified" and not (it["value"].startswith("SMT")):
            continue
        if it["designators"] in ("U1", "U10", "PCB"):
            continue
        if it.get("fixed"):
            fixed += up * q
        elif it["value"].startswith("SMT"):
            smt += up * q
        elif mpn in PACKS:
            size, price = PACKS[mpn]
            mech += math.ceil(q * boards / size) * price / boards
        elif it["designators"] == "-" or mpn == "CLA021-LCP":
            mech += up * q
        elif mpn in lad:
            ics += tier(lad[mpn]["ladder"], q * boards) * q
        else:
            ics += up * q
    return ics, mech, fixed + HAND, smt


rows = {n: cost(n) for n in N}
print("| Item (USD per board) | " + " | ".join("%d board%s" % (n, "s" if n > 1 else "") for n in N) + " |")
print("|---|---|---|---|")
def line(name, f):
    print("| " + name + " | " + " | ".join("%.2f" % f(n) for n in N) + " |")
line("Passives/ICs/connectors at LCSC (excl. U1, U10)", lambda n: rows[n][0])
line("Lens, lens holder, screws, inserts, filament", lambda n: rows[n][1])
line("SMT placement (771 joints)", lambda n: rows[n][3])
line("JLCPCB fixed fees incl. hand-soldering, spread", lambda n: rows[n][2] / n)
line("Subtotal without FPGA", lambda n: rows[n][0] + rows[n][1] + rows[n][3] + rows[n][2] / n)
print("fixed fees total: %.2f" % rows[1][2])
