"""PCB component metadata for the interactive 3D viewer (used by build_site.py).

Reads (read-only): pcb/output/apriltag_cam.kicad_pcb (footprint ref/position/side of the routed board),
pcb/output/placement.csv (value + notes), pcb/output/netlist.txt (ref.pin -> net).
Matches STEP solids to reference designators by position, so the viewer can look a clicked solid up by ref.
"""
import os, re, csv, collections
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'pcb', 'output')


def _rd(p):
    with open(p, encoding='utf-8', errors='replace') as f:
        return f.read()


def kind_of(ref):
    m = re.match(r'[A-Za-z]+', ref); p = m.group(0).upper() if m else ''
    return {'C': 'cap', 'R': 'res', 'L': 'ind', 'FB': 'ind', 'D': 'led', 'LED': 'led', 'U': 'ic', 'J': 'conn', 'SW': 'conn', 'Y': 'xtal',
            'TP': 'tp', 'MH': 'mech', 'LH': 'mech'}.get(p, 'other')


def read_footprints():
    """-> {ref: dict(fp, side, x, y, rot)} with x,y relative to board centre, +y up (same frame as the 3D view)"""
    fps = {}
    for name in ('apriltag_cam.kicad_pcb',):   # the routed board; the old *_unrouted variant held pre-move LED positions
        p = os.path.join(OUT, name)
        try:
            t = _rd(p)
        except OSError:
            continue
        found = {}
        for m in re.finditer(r'\(footprint "([^"]+)"\s*\(layer "([FB])\.Cu"\)\s*\(uuid "[^"]+"\)\s*\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', t):
            seg = t[m.end():m.end() + 3500]
            r = re.search(r'\(property "Reference" "([^"]+)"', seg)
            v = re.search(r'\(property "Value" "([^"]*)"', seg)
            if not r: continue
            found[r.group(1)] = dict(fp=m.group(1).split(':')[-1], side='top' if m.group(2) == 'F' else 'bottom',
                                     x=float(m.group(3)), y=float(m.group(4)), rot=float(m.group(5) or 0), value=v.group(1) if v else '')
        if len(found) > 100:
            fps = found; break
    return fps


def read_placement():
    rows = {}
    try:
        for r in csv.DictReader(open(os.path.join(OUT, 'placement.csv'), encoding='utf-8')):
            rows[r['Ref']] = r
    except OSError:
        pass
    return rows


def read_netlist():
    nets = collections.OrderedDict()
    try:
        for line in _rd(os.path.join(OUT, 'netlist.txt')).splitlines():
            if ':' in line:
                n, pins = line.split(':', 1); nets[n.strip()] = pins.split()
    except OSError:
        pass
    return nets


def build_info(centre=None):
    """-> pcbinfo dict {'refs': {ref: {...}}, 'nets': {net: [ref.pin,..]}, 'size':[w,h]}.  centre = KiCad board centre (x,y) used to make x,y relative"""
    fps = read_footprints(); pl = read_placement(); nets = read_netlist()
    pins = collections.defaultdict(dict)
    for n, ps in nets.items():
        for p in ps:
            ref, _, pin = p.rpartition('.')
            pins[ref][pin] = n
    refs = {}
    cx, cy = centre if centre else (100.0, 100.0)
    for ref in sorted(set(fps) | set(pl), key=lambda s: (re.sub(r'\d+', '', s), int(re.sub(r'\D', '', s) or 0))):
        f = fps.get(ref); r = pl.get(ref, {})
        d = {'fp': (f or {}).get('fp') or r.get('Footprint', ''), 'val': (f or {}).get('value') or r.get('Value', ''),
             'side': (f or {}).get('side') or r.get('Side', ''), 'k': kind_of(ref)}
        if f: d['x'] = round(f['x'] - cx, 3); d['y'] = round(cy - f['y'], 3); d['rot'] = f['rot']
        elif r: d['x'] = float(r['X_mm']); d['y'] = float(r['Y_mm']); d['rot'] = float(r['Rot'] or 0)
        if r.get('Note'): d['note'] = r['Note']
        if pins.get(ref): d['pins'] = pins[ref]
        refs[ref] = d
    return {'refs': refs, 'nets': {n: ps for n, ps in nets.items()}}


def match_solids(solids, cx, cy, ztop):
    """solids: list of dict(name, bb=[x0,y0,z0,x1,y1,z1]) in STEP coords.  Returns list of ref (or None) per solid."""
    fps = read_footprints()
    res = [None] * len(solids)
    if not fps:
        return res
    # STEP frame: x = kicad x, y = -kicad y.  candidates keyed by (footprint prefix, side)
    def fam(s): return re.sub(r'\d{3}$', '', s)[:9]
    cand = collections.defaultdict(list)
    for ref, f in fps.items():
        cand[(f['fp'][:9], f['side'])].append((ref, f['x'], -f['y']))
    left = {r: (f['x'], -f['y'], f['side']) for r, f in fps.items()}
    items = []
    for i, s in enumerate(solids):
        bb = s['bb']; side = 'top' if (bb[2] + bb[5]) / 2 > ztop / 2 else 'bottom'
        items.append((i, (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, side, fam(s['name'])))
    try:
        from scipy.optimize import linear_sum_assignment as lsa
    except Exception:
        lsa = None
    by = collections.defaultdict(list)
    for it in items: by[(it[4], it[3])].append(it)
    for k, its in by.items():
        cs = cand.get(k, [])
        if not cs: continue
        A = np.array([[a[1], a[2]] for a in its]); B = np.array([[c[1], c[2]] for c in cs])
        D = np.linalg.norm(A[:, None] - B[None], axis=2)
        if lsa:
            ii, jj = lsa(D)
        else:
            ii, jj, used = [], [], set()
            for i in np.argsort(D.min(axis=1)):
                j = min((j for j in range(len(cs)) if j not in used), key=lambda j: D[i, j], default=None)
                if j is None: break
                used.add(j); ii.append(i); jj.append(j)
        for i, j in zip(ii, jj):
            if D[i, j] < 4.0:
                res[its[i][0]] = cs[j][0]; left.pop(cs[j][0], None)
    # second pass: unmatched solids -> nearest unused footprint on the same side (name families that differ, e.g. SOT-23-5 vs SOT-23)
    for it in items:
        if res[it[0]] is not None: continue
        best = None
        for ref, (x, y, side) in left.items():
            if side != it[3]: continue
            d = ((x - it[1]) ** 2 + (y - it[2]) ** 2) ** .5
            if d < 1.5 and (best is None or d < best[0]): best = (d, ref)
        if best: res[it[0]] = best[1]; left.pop(best[1], None)
    return res
