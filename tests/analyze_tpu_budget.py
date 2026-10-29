"""Per-category TPU time and CCL status from results/rtl_chain_results.json (single-frame runs of the 500-frame set).

A frame whose TPU run is longer than one sensor frame period would be dropped (reg 0x30 frames_dropped) in a back-to-back stream,
because the ping-pong bank it needs is still busy when the next frame ends.  Frame period in core clocks: 713,840 at the real
85.714 MHz core (686 clocks/line x 1041 lines), 832,800 in the 100 MHz simulations.

    py -3.12 tests/analyze_tpu_budget.py"""
import os, sys, json, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import geom
ROOT = geom.ROOT
FRAME_REAL, FRAME_SIM = 713_840, 832_800


def main():
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    rtl = json.load(open(os.path.join(ROOT, 'results', 'rtl_chain_results.json')))
    cats = sorted({g['category'] for g in gt.values()})
    print(f'| category | frames | TPU clk median | worst | would drop @ real core ({FRAME_REAL}) | would drop @ sim core ({FRAME_SIM}) | CCL flags set | rows dropped (bit 0) |')
    print('|---|---|---|---|---|---|---|---|')
    tot = [0, 0, 0, 0, 0]
    for c in cats:
        names = [n for n, g in gt.items() if g['category'] == c and n in rtl]
        cyc = np.array([int(rtl[n]['stats']['tpucyc']) for n in names])
        fl = [(int(rtl[n]['stats']['ccl'], 16) >> 8) & 15 for n in names]
        a, b = int((cyc > FRAME_REAL).sum()), int((cyc > FRAME_SIM).sum())
        print(f'| {c} | {len(names)} | {int(np.median(cyc))} | {int(cyc.max())} | {a} | {b} | {sum(f != 0 for f in fl)} | {sum(f & 1 for f in fl)} |')
        tot = [tot[0] + len(names), tot[1] + a, tot[2] + b, tot[3] + sum(f != 0 for f in fl), tot[4] + sum(f & 1 for f in fl)]
    print(f'| all | {tot[0]} | | | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} |')


if __name__ == '__main__':
    main()
