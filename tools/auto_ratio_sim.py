"""Simulate the automatic contrast-ratio policy (firmware/core/atratio.c, run inside the real firmware through simfw) over frame sequences.

Per-frame inputs are the measured RTL chain results of the 100-frame dataset at ratio 0 and at ratio 1 (results/rtl_chain_results.json,
results/rtl_chain_results_ratio1.json): tags found and CCL register (flags, candidates).  A frame in a sequence is taken from the file of the ratio that
is in the THRESH register when the frame is captured.  A register write made after processing frame k reaches the sensor frames k+LAT and later
(LAT = 2: packet end 6.7 ms + tag unit up to 9.3 ms + SPI write is 1.5 .. 2 frame periods).  Sequences: every category repeated (10 frames x 10 cycles, as
tools/frame_budget.py), and the whole dataset in several orders.  Nothing here is measured on hardware: the per-frame results are measured in the RTL
chain, the switching dynamics (register latency) are modelled.

    py -3.12 tools/auto_ratio_sim.py [--lat 2] [--md results/auto_ratio.md] [--json results/auto_ratio.json]
"""
import os, sys, json, argparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'host'))
from apriltag_cam import protocol as P, simfw      # noqa: E402

CYCLES = 10
THRESH_RESET = 0x020A4018


def load():
    gt = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))['images']
    res = {r: json.load(open(os.path.join(ROOT, 'results', f))) for r, f in ((0, 'rtl_chain_results.json'), (1, 'rtl_chain_results_ratio1.json'))}
    return gt, res


def detectable(g):
    return {int(t) for t, v in g['tags'].items() if v.get('detectable', v['visible'])}


def run_sequence(names, gt, res, lat=2, mode='auto'):
    """mode: 'auto' (policy on) or 0 / 1 (fixed ratio, policy off).  The frames go through the real firmware (simfw).
    Returns dict(found, vis, ratios (ratio each frame was captured with), per_frame (detectable tags found per frame))."""
    fw = simfw.NativeFirmware()
    fpga = fw.fpga

    def send(t, b=b''):
        fw.rx(P.encode_frame(t, b))
        fw.take_tx()
    send(P.CMD_SET_AE, b'\x00')
    if mode == 'auto':
        send(P.CMD_SET_AUTO_RATIO, b'\x01')
    else:
        send(P.CMD_SET_AUTO_RATIO, b'\x00')
        if mode:
            send(P.CMD_SET_TRACK, bytes([24, 64, 10, 2 | (mode << 6)]))
    after = []                         # register ratio after the firmware processed frame k
    found = vis = 0
    ratios, per_frame = [], []
    for k, n in enumerate(names):
        r = (after[k - lat] if k >= lat else 0) if mode == 'auto' else mode
        d = res[r][n]
        c = int(d['stats']['ccl'], 16)
        fpga.publish([(t['id'], t['corners'], t.get('ham', 0)) for t in d['tags']], ccl_flags=(c >> 8) & 15)
        assert fw.poll()
        after.append(fpga.regs.get(simfw.REG_THRESH, THRESH_RESET) >> 30)
        v = detectable(gt[n])
        f = v & {t['id'] for t in d['tags']}
        found += len(f)
        vis += len(v)
        ratios.append(r)
        per_frame.append(len(f))
    return dict(found=found, vis=vis, ratios=ratios, per_frame=per_frame)


def switches(ratios):
    return sum(1 for i in range(1, len(ratios)) if ratios[i] != ratios[i - 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lat', type=int, default=2)
    ap.add_argument('--md')
    ap.add_argument('--json')
    a = ap.parse_args()
    gt, res = load()
    cats = sorted({g['category'] for g in gt.values()})
    by = {c: sorted(n for n, g in gt.items() if g['category'] == c) for c in cats}
    out = {'lat': a.lat, 'cats': {}}
    lines = [f'Register write latency {a.lat} frame(s). Each category: its 10 frames repeated {CYCLES} times ({10 * CYCLES} frames). '
             'found = detectable GT tags found, summed over the sequence; `first r1` = index of the first frame captured at ratio 1; '
             '`frames to first tag` = index of the first frame of the sequence in which auto finds a tag.', '',
             '| category | frames | GT tags | fixed 0 | fixed 1 | auto | auto - fixed 0 | ratio-1 frames | first r1 | switches | frames to first tag |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    tot = dict(vis=0, f0=0, f1=0, fa=0)
    for c in cats:
        names = by[c] * CYCLES
        r0, r1, ra = (run_sequence(names, gt, res, a.lat, m) for m in (0, 1, 'auto'))
        first = next((i for i, r in enumerate(ra['ratios']) if r == 1), None)
        ft = next((i for i, f in enumerate(ra['per_frame']) if f), None)
        out['cats'][c] = dict(vis=ra['vis'], fixed0=r0['found'], fixed1=r1['found'], auto=ra['found'], r1_frames=sum(ra['ratios']),
                              first_r1=first, switches=switches(ra['ratios']), first_tag=ft)
        lines.append(f"| {c} | {len(names)} | {ra['vis']} | {r0['found']} | {r1['found']} | **{ra['found']}** | {ra['found'] - r0['found']:+d} | "
                     f"{sum(ra['ratios'])} | {first if first is not None else '-'} | {switches(ra['ratios'])} | {ft if ft is not None else '-'} |")
        for k, v in (('vis', ra['vis']), ('f0', r0['found']), ('f1', r1['found']), ('fa', ra['found'])):
            tot[k] += v
    lines.append(f"| **all** | {len(cats) * 10 * CYCLES} | {tot['vis']} | {tot['f0']} | {tot['f1']} | **{tot['fa']}** | {tot['fa'] - tot['f0']:+d} | | | | |")
    out['total'] = tot
    lines += ['', 'The whole dataset as one stream (scene changes between categories), detectable tags found:', '',
              '| order | frames | GT tags | fixed 0 | fixed 1 | auto | ratio-1 frames | switches |', '|---|---|---|---|---|---|---|---|']
    orders = {'file order (sorted names)': sorted(gt),
              'categories reversed': [n for c in reversed(cats) for n in by[c]],
              'lowcon first': by['lowcon'] + [n for c in cats if c != 'lowcon' for n in by[c]],
              'noise, lowcon, clutter, noise, lowcon': by['noise'] + by['lowcon'] + by['clutter'] + by['noise'] + by['lowcon']}
    out['orders'] = {}
    for label, names in orders.items():
        r0, r1, ra = (run_sequence(names, gt, res, a.lat, m) for m in (0, 1, 'auto'))
        out['orders'][label] = dict(frames=len(names), vis=ra['vis'], fixed0=r0['found'], fixed1=r1['found'], auto=ra['found'],
                                    r1_frames=sum(ra['ratios']), switches=switches(ra['ratios']))
        lines.append(f"| {label} | {len(names)} | {ra['vis']} | {r0['found']} | {r1['found']} | **{ra['found']}** | {sum(ra['ratios'])} | {switches(ra['ratios'])} |")
    txt = '\n'.join(lines)
    print(txt)
    if a.md:
        open(a.md, 'w').write(txt + '\n')
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
