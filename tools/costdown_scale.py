"""Scale the measured PC detector times to candidate CPUs by single-thread 7-zip MIPS (ThomasKaiser/sbc-bench Results.md, read 2026-10-30)
and compute the 120 fps feasibility (8.33 ms frame period, one whole frame per core = frame pipelining, 85 % parallel efficiency assumed).
    py -3.12 tools/costdown_scale.py  -> results/costdown_scaling.md
PC reference: this PC, 7-Zip `7z b -mmt1` total = 9469 MIPS (Ryzen 9 7900X); the detector times are results/costdown_native*.json (single thread)."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PC = 9469.0; PERIOD = 1000 / 120.0; EFF = 0.85
N = json.load(open(os.path.join(ROOT, 'results/costdown_native.json'))); NB = json.load(open(os.path.join(ROOT, 'results/costdown_native_bin.json')))
def pick(L, dec, qs, thr=1): return [x for x in L if x['decimate'] == dec and x['quad_sigma'] == qs and x['threads'] == thr][0]
W = {
 'W1 gray, full res, sigma 0.8 (632/647 tags)': pick(N, 1, 0.8),
 'W2 gray, full res, no blur (626/647)': pick(N, 1, 0),
 'W3 gray, decimate 2, no blur (613/647)': pick(N, 2, 0),
 'W4 after FPGA threshold+despeckle (556/647)': pick(NB, 1, 0),
}
# (name, LCSC price at 1+, [(count, 7-zip MIPS single-thread of that core type, source note)])
CPU = [
 ('RV1106G3 (1x A7 1.2 GHz)', 25.3877, [(1, 772, 'SSD202D A7 1094 MIPS at 1.7 GHz scaled to 1.2 GHz: ESTIMATE')]),
 ('T113-S3 (2x A7 1.2 GHz)', 21.4419, [(2, 772, 'as above: ESTIMATE')]),
 ('i.MX 8M Mini (4x A53 1.8 GHz)', 23.4864, [(4, 1348, 'i.MX8MPlus EVK A53 1.8 GHz measured 1348 (Mini has the same A53 at the same clock)')]),
 ('RK3566 (4x A55 1.8 GHz)', 14.6466, [(4, 1457, 'Quartz64-A RK3566 1.89 GHz measured 1457')]),
 ('V853 (1x A7 + NPU)', 5.9369, [(1, 700, 'A7 ESTIMATE (clock not checked)')]),
 ('RK3576 (4x A72 2.2 GHz + 4x A53 2.0 GHz)', 22.8179, [(4, 1771, 'ROCK 4D RK3576 A72 measured 1771'), (4, 1400, 'A53 estimate from RPi3 977 @1.2 GHz scaled')]),
 ('RK3588 (4x A76 2.35 GHz + 4x A55 1.8 GHz)', 65.9546, [(4, 3146, 'ROCK 5B measured 3146'), (4, 1400, 'A55 estimate from RK3566')]),
 ('Raspberry Pi 5 BCM2712 (4x A76 2.4 GHz) [not a purchasable chip, reference]', None, [(4, 3196, 'measured 3196')]),
]
L = ['| CPU (LCSC 1+ price) | PC-core equivalents (x 0.85) | ' + ' | '.join(f'{k.split(" ")[0]} need mean / p95 / max' for k in W) + ' |', '|---|---|' + '---|' * len(W)]
for name, price, cores in CPU:
    cap = sum(c * m for c, m, _ in cores) / PC * EFF
    row = [f'{name} {"$%.2f" % price if price else ""}', f'{cap:.2f}']
    for k, w in W.items():
        need = [w['mean_ms'] / PERIOD, w['p95_ms'] / PERIOD, w['max_ms'] / PERIOD]
        row.append(' / '.join(f'{n:.1f}' + ('' if n <= cap else '!') for n in need))
    L.append('| ' + ' | '.join(row) + ' |')
txt = ('Required PC-core equivalents = per-frame detector time on the Ryzen 9 7900X (single thread) / 8.33 ms; "!" marks needs above the chip capacity.\n\n'
       + '\n'.join(L) + '\n\nWorkload times (ms, 7900X single thread): ' + '; '.join(f"{k}: mean {w['mean_ms']:.1f} p95 {w['p95_ms']:.1f} max {w['max_ms']:.1f}" for k, w in W.items()) + '\n')
open(os.path.join(ROOT, 'results/costdown_scaling.md'), 'w').write(txt); print(txt)
