"""Repair of +3V3 / GND copper fragments that KiCad DRC reports as unconnected items.

Background: the grid router treats "pad + via" as connected to the +3V3 / GND plane.  GND is a solid plane on In1, but +3V3 is on In2, which also
carries signal tracks and the +1V1 island, so the pour does not reach every +3V3 via.  Those pads then hang on stubs that end in a via without a plane.

This script takes the unconnected pairs from a KiCad DRC json report, finds a short single-net path between the two items with an A* search on a 0.05 mm
grid (F.Cu, B.Cu, through vias at 0.45/0.2 mm, other nets and holes as obstacles), adds it, refills the zones and saves.
usage (KiCad python):  fix_power_links.py in.kicad_pcb drc.json out.kicad_pcb workdir [net ...]     (default nets: +3V3; accepts a candidate path only when DRC unconnected items drop and no hole/clearance error appears)
"""
import os, sys, json, heapq, math
import numpy as np
import pcbnew

mm = pcbnew.FromMM
STEP = 0.05
W = 0.10                 # new track width
VIA_D, VIA_DRILL = 0.45, 0.20
VIA_CLR = 0.36           # copper edge to via centre: board hole clearance 0.25 + drill radius 0.1 (+ margin)
POWER = ('+3V3', '+1V1', '+1V1MCU', '+1V2', '+1V8', '+2V5', '+2V8', '+5V', 'VBUS', 'SW1V1', 'SW3V3', 'VREG_LX')       # 'Power' net class: 0.12 mm clearance
CLR = 0.12               # clearance used for power nets; signal nets use 0.10 (Default class), see Grid.clr
LAYERS = ['F.Cu', 'In2.Cu', 'B.Cu']      # In1 is the solid GND plane, never routed
ALL = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']


class Grid:
    def __init__(self, b, x0, y0, x1, y1, net):
        self.b, self.net = b, net
        self.clr = CLR if net in POWER else 0.10
        self.x0, self.y0 = math.floor(x0 / STEP) * STEP, math.floor(y0 / STEP) * STEP      # grid on multiples of 0.05 mm (the BGA via lattice is 0.8 mm)
        x1, y1 = x1 + STEP, y1 + STEP
        self.nx, self.ny = int((x1 - self.x0) / STEP) + 1, int((y1 - self.y0) / STEP) + 1
        self.trk = {l: np.zeros((self.nx, self.ny), bool) for l in ALL}      # blocked for a track centre
        self.via = np.zeros((self.nx, self.ny), bool)                       # blocked for a via centre (any layer)
        self.build()
        self.plane = self.plane_cells() if net != 'GND' else set()      # GND: In1 is a solid plane that is not routed on, pair-to-pair links only

    def cell(self, x, y): return int(round((x - self.x0) / STEP)), int(round((y - self.y0) / STEP))
    def xy(self, i, j): return self.x0 + i * STEP, self.y0 + j * STEP

    def paint(self, arr, shape, clr):
        bb = shape.BBox(); m = mm(clr)
        l, r, t, bt = (pcbnew.ToMM(v) for v in (bb.GetLeft() - m, bb.GetRight() + m, bb.GetTop() - m, bb.GetBottom() + m))
        i0, j0 = self.cell(l, t); i1, j1 = self.cell(r, bt)
        i0, j0 = max(i0, 0), max(j0, 0); i1, j1 = min(i1, self.nx - 1), min(j1, self.ny - 1)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                x, y = self.xy(i, j)
                if not arr[i, j] and shape.Collide(pcbnew.VECTOR2I(mm(x), mm(y)), m): arr[i, j] = True

    def plane_cells(self):
        """In2 cells inside the main (largest) filled pour of the net, with margin: a via there lands on the plane."""
        pl = 'In1.Cu' if self.net == 'GND' else 'In2.Cu'
        li = self.b.GetLayerID(pl); polys = []
        for z in self.b.Zones():
            if z.GetNetname() == self.net and z.IsOnLayer(li):
                ps = z.GetFilledPolysList(li)
                if ps.OutlineCount(): polys.append((ps, max(range(ps.OutlineCount()), key=lambda k: abs(ps.Outline(k).Area()))))
        out = set()
        for i in range(self.nx):
            for j in range(self.ny):
                if self.via[i, j] or self.trk[pl][i, j]: continue
                x, y = self.xy(i, j)
                if all(any(ps.Contains(pcbnew.VECTOR2I(mm(x + dx), mm(y + dy)), k) for ps, k in polys) for dx, dy in ((0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2))):
                    out.add((pl, (i, j)))
        return out

    def build(self):
        b = self.b
        for t in b.GetTracks():
            if t.GetClass() == 'PCB_VIA' and t.GetNetname() == self.net:           # same-net via: no copper conflict, but a new hole needs 0.25 mm hole-to-hole
                self.paint(self.via, t.GetEffectiveHoleShape(), 0.25 + VIA_D / 2 + 0.01)
            if t.GetNetname() == self.net: continue
            if t.GetClass() == 'PCB_VIA':
                for l in ALL:
                    li = b.GetLayerID(l); self.paint(self.trk[l], t.GetEffectiveShape(li), 0.1745)      # track edge to via hole >= 0.25 mm: centre >= 0.1 + 0.25 + W/2 = 0.40 from the via centre
                self.paint(self.via, t.GetEffectiveShape(b.GetLayerID('F.Cu')), VIA_CLR)
            else:
                l = b.GetLayerName(t.GetLayer())
                if l in self.trk:
                    li = t.GetLayer(); self.paint(self.trk[l], t.GetEffectiveShape(li), self.clr + W / 2)
                    if l != 'In1.Cu': self.paint(self.via, t.GetEffectiveShape(li), VIA_CLR)
        for f in b.GetFootprints():
            for p in f.Pads():
                dr = p.GetDrillSize()
                if dr.x > 0:
                    hs = p.GetEffectiveHoleShape()
                    for l in ALL: self.paint(self.trk[l], hs, 0.25 + W / 2)
                    self.paint(self.via, hs, 0.25 + VIA_D / 2 + 0.01)
                if p.GetNetname() == self.net: continue
                for l in ALL:
                    li = b.GetLayerID(l)
                    if p.IsOnLayer(li):
                        self.paint(self.trk[l], p.GetEffectiveShape(li), self.clr + W / 2)
                        if l != 'In1.Cu': self.paint(self.via, p.GetEffectiveShape(li), VIA_CLR)


def item_cells(g, it):
    """(layer, cell) pairs where a path may start / end on this item."""
    b = g.b
    if it.GetClass() == 'PCB_VIA':
        p = it.GetPosition(); c = g.cell(pcbnew.ToMM(p.x), pcbnew.ToMM(p.y))
        return [(l, c) for l in LAYERS]
    if it.GetClass() in ('PCB_TRACK', 'PCB_ARC'):
        l = b.GetLayerName(it.GetLayer()); s, e = it.GetStart(), it.GetEnd()
        n = max(1, int(math.hypot(s.x - e.x, s.y - e.y) / mm(STEP)))
        return [(l, g.cell(pcbnew.ToMM(s.x + (e.x - s.x) * k / n), pcbnew.ToMM(s.y + (e.y - s.y) * k / n))) for k in range(n + 1)]
    l = 'B.Cu' if it.IsOnLayer(b.GetLayerID('B.Cu')) else 'F.Cu'     # pad: cells inside its shape
    bb = it.GetBoundingBox(); cells = []
    i0, j0 = g.cell(pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())); i1, j1 = g.cell(pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            x, y = g.xy(i, j)
            if it.HitTest(pcbnew.VECTOR2I(mm(x), mm(y))): cells.append((l, (i, j)))
    return cells


def fragment(b, start):
    """All copper items of the start item's net that touch it through tracks / vias / pads (own geometry walk; KiCad's connectivity also follows pours)."""
    net = start.GetNetname(); items = [t for t in b.GetTracks() if t.GetNetname() == net]
    for f in b.GetFootprints():
        items += [p for p in f.Pads() if p.GetNetname() == net]
    def ends(it):
        if it.GetClass() == 'PCB_VIA': return [it.GetPosition()]
        if it.GetClass() in ('PCB_TRACK', 'PCB_ARC'): return [it.GetStart(), it.GetEnd()]
        return [it.GetPosition()]
    def layers(it):
        return set(b.GetLayerName(l) for l in it.GetLayerSet().Seq() if b.GetLayerName(l) in ALL)
    def touch(a, c):
        if not layers(a) & layers(c): return False
        for x, y in ((a, c), (c, a)):
            for p in ends(x):
                if x.GetClass() == 'PAD' and False: continue
                if y.GetClass() == 'PAD':
                    if y.HitTest(p): return True
                elif y.GetClass() == 'PCB_VIA':
                    if (p - y.GetPosition()).EuclideanNorm() < mm(0.2): return True
                elif any((p - q).EuclideanNorm() < mm(0.002) for q in ends(y)): return True
        if a.GetClass() == 'PAD' and c.GetClass() == 'PAD': return False
        return False
    seen = {start.m_Uuid.AsString(): start}; todo = [start]
    while todo:
        x = todo.pop()
        for y in items:
            k = y.m_Uuid.AsString()
            if k not in seen and touch(x, y): seen[k] = y; todo.append(y)
    return list(seen.values())


def astar(g, src, dst):
    goal = {(l, c) for l, c in dst}
    gc = [c for l, c in dst]; gx, gy = sum(c[0] for c in gc) / len(gc), sum(c[1] for c in gc) / len(gc)
    h = lambda c: 0.0                                           # plain Dijkstra: the goal is a set of areas
    pq = []; dist = {}; prev = {}
    for l, c in src:
        dist[(l, c)] = 0.0; heapq.heappush(pq, (h(c), 0.0, l, c))
    nb = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    while pq:
        _, d, l, c = heapq.heappop(pq)
        if d > dist.get((l, c), 1e18): continue
        if (l, c) in goal:
            path = [(l, c)]
            while path[-1] in prev: path.append(prev[path[-1]])
            return path[::-1]
        for di, dj, w in nb:
            n = (c[0] + di, c[1] + dj)
            if not (0 <= n[0] < g.nx and 0 <= n[1] < g.ny): continue
            if g.trk[l][n] and (l, n) not in goal: continue
            if di and dj and (g.trk[l][c[0] + di, c[1]] or g.trk[l][c[0], c[1] + dj]): continue      # no corner cutting
            nd = d + w
            if nd < dist.get((l, n), 1e18): dist[(l, n)] = nd; prev[(l, n)] = (l, c); heapq.heappush(pq, (nd + h(n), nd, l, n))
        if not g.via[c]:
            for ol in LAYERS:
                if ol == l or g.trk[ol][c]: continue
                nd = d + 12.0
                if nd < dist.get((ol, c), 1e18): dist[(ol, c)] = nd; prev[(ol, c)] = (l, c); heapq.heappush(pq, (nd + h(c), nd, ol, c))
    return None


def emit(g, path, net):
    b = g.b; ni = b.FindNet(net); n = 0
    pts = [(l, g.xy(*c)) for l, c in path]
    i = 0
    while i < len(pts) - 1:
        l, p = pts[i]
        if pts[i + 1][0] != l:
            v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(p[0]), mm(p[1]))); v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL)); v.SetNet(ni)
            v.SetViaType(pcbnew.VIATYPE_THROUGH); b.Add(v); n += 1; i += 1; continue
        j = i + 1                                              # extend while the direction stays the same
        d0 = (pts[j][1][0] - p[0], pts[j][1][1] - p[1])
        while j + 1 < len(pts) and pts[j + 1][0] == l:
            d1 = (pts[j + 1][1][0] - pts[j][1][0], pts[j + 1][1][1] - pts[j][1][1])
            if abs(d1[0] * d0[1] - d1[1] * d0[0]) > 1e-9 or d1[0] * d0[0] + d1[1] * d0[1] < 0: break
            j += 1
        q = pts[j][1]
        if (p[0], p[1]) != (q[0], q[1]):
            t = pcbnew.PCB_TRACK(b); t.SetStart(pcbnew.VECTOR2I(mm(p[0]), mm(p[1]))); t.SetEnd(pcbnew.VECTOR2I(mm(q[0]), mm(q[1])))
            t.SetWidth(mm(W)); t.SetLayer(b.GetLayerID(l)); t.SetNet(ni); b.Add(t); n += 1
        i = j
    return n


KCLI = os.path.join(os.path.dirname(sys.executable), 'kicad-cli.exe')       # sys.executable is KiCad's own python.exe (bin folder)
BAD = ('hole_clearance', 'hole_to_hole', 'holes_co_located', 'clearance', 'shorting_items', 'track_dangling', 'copper_edge_clearance', 'via_dangling_new')


def drc(path, out):
    import subprocess
    subprocess.run([KCLI, 'pcb', 'drc', '--output', out, '--format', 'json', '--severity-all', '--units', 'mm', '--all-track-errors', path],
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    d = json.load(open(out))
    c = {}
    for v in d['violations']: c[v['type']] = c.get(v['type'], 0) + 1
    return d, c


def score(d, c, nets):
    un = sum(1 for u in d['unconnected_items'] if u['items'][0]['description'].split('[')[1].split(']')[0] in nets) if d['unconnected_items'] else 0
    bad = sum(c.get(k, 0) for k in BAD)
    return un, bad


def route_pair(src, a_uuid, c_uuid, dst, mode):
    """mode 0: a -> c;  1: c -> a;  2: a -> plane or c;  3: c -> plane or a.   Returns True when a path was added."""
    b = pcbnew.LoadBoard(src); by = {}
    for t in b.GetTracks(): by[t.m_Uuid.AsString()] = t
    for f in b.GetFootprints():
        for p in f.Pads(): by[p.m_Uuid.AsString()] = p
    a, c = by[a_uuid], by[c_uuid]
    if mode in (1, 3): a, c = c, a
    net = a.GetNetname()
    pa = (pcbnew.ToMM(a.GetPosition().x), pcbnew.ToMM(a.GetPosition().y)); pc = (pcbnew.ToMM(c.GetPosition().x), pcbnew.ToMM(c.GetPosition().y))
    pad = 8.0
    g = Grid(b, min(pa[0], pc[0]) - pad, min(pa[1], pc[1]) - pad, max(pa[0], pc[0]) + pad, max(pa[1], pc[1]) + pad, net)
    inside = lambda cl: [(l, ce) for l, ce in cl if 0 <= ce[0] < g.nx and 0 <= ce[1] < g.ny]
    goal = [x for it in fragment(b, c) for x in inside(item_cells(g, it))] + (list(g.plane) if mode >= 2 and net != 'GND' else [])
    path = astar(g, [x for it in fragment(b, a) for x in inside(item_cells(g, it))], goal)
    if not path or len(path) < 2: return False
    emit(g, path, net)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(dst, b)
    return True


def main(src, rep, dst, nets, work):
    import shutil, os
    os.makedirs(work, exist_ok=True)
    cur = os.path.join(work, 'cur.kicad_pcb'); shutil.copy(src, cur)
    pro = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'apriltag_cam.kicad_pro')      # project file = design rules for kicad-cli
    for nm in ('cur', 'cand'): shutil.copy(pro, os.path.join(work, nm + '.kicad_pro'))
    d, c = drc(cur, os.path.join(work, 'cur.json'))
    best = score(d, c, nets); print('start', best, c)
    for rnd in range(30):
        pairs = [[i['uuid'] for i in u['items']] for u in d['unconnected_items'] if u['items'][0]['description'].split('[')[1].split(']')[0] in nets]
        if not pairs: break
        progress = False
        for a, cc in pairs:
            for mode in (0, 1, 2, 3):
                cand = os.path.join(work, 'cand.kicad_pcb')
                try:
                    if not route_pair(cur, a, cc, cand, mode):
                        print(' round', rnd, 'mode', mode, 'no path'); continue
                except KeyError: continue
                d2, c2 = drc(cand, os.path.join(work, 'cand.json')); sc = score(d2, c2, nets)
                print(' round', rnd, 'mode', mode, sc)
                if sc[1] <= best[1] and sc[0] < best[0]:
                    shutil.copy(cand, cur); d, c, best = d2, c2, sc; progress = True; break
            if progress: break
        if not progress: print('no further progress'); break
    shutil.copy(cur, dst)
    print('final', best, c)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[5:] or ['+3V3'], sys.argv[4])
