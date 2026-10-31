"""Recurring BOM per board at 1/10/100 boards for the architectures in docs/costdown.md, from docs/bom/bom.json + results/costdown_prices.json
(live LCSC API reads).  Passives keep the bom.json 1+ price at every quantity (conservative).  Excludes the OV9281 (no public price), the PCB
fabrication (unverified in bom.json), SMT placement (unverified) and one-time fees (reported separately and amortised).
    py -3.12 tools/costdown_model.py  -> results/costdown_model.json + printed markdown tables"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bom = json.load(open(os.path.join(ROOT, 'docs/bom/bom.json'))); P = json.load(open(os.path.join(ROOT, 'results/costdown_prices.json')))
LENS_ARDUCAM = 10.09     # RobotShop RB-Adu-231 / Arducam LN005 M27210H08, read via WebFetch 2026-10-30 (summarised page; stock: backorder)

def tier(ladder, q):
    p = None
    for n, pr in ladder:
        if n <= q: p = pr
    return p if p is not None else ladder[0][1]

base_items = [i for i in bom['items'] if not i.get('fixed') and i.get('unit_price') is not None]
FPGA, MCU, FLASH = 'U1', 'U2', 'U3'
fixed = sum(i['unit_price'] * i['qty'] for i in bom['items'] if i.get('fixed') and i.get('unit_price') is not None)
def rest(excl_desig=(), excl_lens=False):
    s = 0
    for i in base_items:
        if i['designators'] in excl_desig: continue
        if excl_lens and i['mpn'] == 'CIL018-F2.8-M12B650': continue
        s += i['unit_price'] * i['qty']
    return s
rest_all = rest((FPGA, MCU, FLASH))                        # everything except FPGA, MCU, flash (lens included)
rest_nolens = rest((FPGA, MCU, FLASH), excl_lens=True)
def fl(q): return tier(P['flash']['ladder'], q)
def mcu(q): return tier(P['rp2350a']['ladder'], q)
def fpga(key, q): return tier(P[key]['ladder'], q * 1)
arch = {
 'A0 baseline (ECP5-85F-8, Commonlands lens)':            lambda q: rest_all + mcu(q) + fl(q) + fpga('ecp5_85f', q),
 'A1 = A0 + Arducam 2.1 mm lens':                         lambda q: rest_nolens + LENS_ARDUCAM + mcu(q) + fl(q) + fpga('ecp5_85f', q),
 'A2 ECP5 UM-45F-8 + off-chip frame RAM (RAM not priced)': lambda q: rest_all + mcu(q) + fl(q) + fpga('ecp5um45_8', q),
 'A3 ECP5 UM-45F-8 front end + CCL, TPU in RP2350 firmware': lambda q: rest_all + mcu(q) + fl(q) + fpga('ecp5um45_8', q),
 'A3b = A3 with LFE5U-25F-6BG256C (needs <=~650 Mb/s MIPI lanes)': lambda q: rest_all + mcu(q) + fl(q) + fpga('ecp5_25f_bg256', q),
 'A3c = A3 with LFE5U-25F-7BG256C (stock 0 at 1+)':        lambda q: rest_all + mcu(q) + fl(q) + fpga('ecp5_25f_7', q),
 'A3+A1 (A3 with UM-45F-8 and Arducam lens)':              lambda q: rest_nolens + LENS_ARDUCAM + mcu(q) + fl(q) + fpga('ecp5um45_8', q),
}
P['ecp5um45_8'] = P['ecp5um45_8'] if 'ecp5um45_8' in P else None
out = {}
qs = (1, 10, 100)
print('one-time fees per order (setup + stencil + feeder lines):', round(fixed, 2), '| per board at 1/10/100:', [round(fixed / q, 2) for q in qs])
print('rest-of-BOM (no FPGA/MCU/flash), Commonlands lens: %.2f ; with lens removed: %.2f' % (rest_all, rest_nolens))
print('| architecture | 1 board | 10 boards | 100 boards |\n|---|---|---|---|')
for k, f in arch.items():
    v = [f(q) for q in qs]; out[k] = v
    print(f'| {k} | ${v[0]:.2f} | ${v[1]:.2f} | ${v[2]:.2f} |')
json.dump(dict(fixed_per_order=fixed, rest_all=rest_all, rest_nolens=rest_nolens, arch=out), open(os.path.join(ROOT, 'results/costdown_model.json'), 'w'), indent=1)
