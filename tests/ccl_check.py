"""Compare run_ccl candidate dump against golden components."""
import numpy as np
def parse_dump(path):
    lines = open(path).read().split()
    n = int(lines[0]); words = [int(x, 16) for x in lines[1:]]
    recs = []
    def s16(v): v &= 0xFFFF; return v - 65536 if v & 0x8000 else v
    for i in range(n):
        w = words[i*16:(i+1)*16]
        sc = [s16(w[1+k]) for k in range(8)]; ax = [(w[1+k] >> 16) & 0xFFFF for k in range(8)]
        recs.append(dict(area=w[0], scores=np.array(sc), aux=ax, label=w[9],
                         x0=w[10] & 0xFFFF, x1=w[10] >> 16, y0=w[11] & 0xFFFF, y1=w[11] >> 16))
    return recs

def point_of(k, sc, ax):
    return [(sc, ax), (-sc, ax), (ax, sc), (ax, -sc), (ax, sc - ax), (ax, -sc - ax), (ax, ax - sc), (ax, sc + ax)][k]

def compare(recs, golden_keep, lab):
    """each RTL record must match one golden component exactly (area, scores) and extreme points must lie in it."""
    errs = []
    gold = {}
    for g in golden_keep:
        gold[(g['area'], tuple(int(v) for v in g['scores']))] = g
    if len(recs) != len(golden_keep):
        errs.append(f'count rtl={len(recs)} golden={len(golden_keep)}')
    for r in recs:
        key = (r['area'], tuple(int(v) for v in r['scores']))
        if key not in gold:
            errs.append(f"no golden match for rtl comp area={r['area']} scores={r['scores']}"); continue
        g = gold[key]
        if (r['x0'], r['x1'], r['y0'], r['y1']) != (g['x0'], g['x1'], g['y0'], g['y1']): errs.append('bbox mismatch')
        for k in range(8):
            x, y = point_of(k, int(r['scores'][k]), r['aux'][k])
            if not (0 <= x < lab.shape[1] and 0 <= y < lab.shape[0]) or lab[y, x] != g['label']:
                errs.append(f'extreme {k} point ({x},{y}) not in component {g["label"]}')
    return errs
