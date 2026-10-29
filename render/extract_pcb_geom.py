"""Dump routed geometry (tracks, vias, pads, outline, drills) per net from a COPY of the board to a compact JSON.
Run with KiCad's python:  "C:/Program Files/KiCad/10.0/bin/python.exe" render/extract_pcb_geom.py <board.kicad_pcb> <out.json>
Coordinates are KiCad mm (y down). Layer index: 0 F.Cu, 1 In1.Cu, 2 In2.Cu, 3 B.Cu."""
import sys, json, math, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = lambda v: round(v / 1e6, 3)
LI = {pcbnew.F_Cu: 0, pcbnew.In1_Cu: 1, pcbnew.In2_Cu: 2, pcbnew.B_Cu: 3}
nets = {}; names = []
def nid(n):
    nm = n.GetNetname()
    if nm not in nets: nets[nm] = len(names); names.append(nm)
    return nets[nm]
tracks, vias, pads = [], [], []
for t in b.GetTracks():
    c = t.GetClass()
    if c == 'PCB_VIA':
        p = t.GetPosition(); vias.append([mm(p.x), mm(p.y), mm(t.GetWidth(pcbnew.F_Cu)), mm(t.GetDrillValue()), nid(t.GetNet())])
    elif c == 'PCB_ARC':
        # sample the arc as 8 segments
        s, m, e = t.GetStart(), t.GetMid(), t.GetEnd(); pts = [(s.x, s.y), (m.x, m.y), (e.x, e.y)]
        a = t.GetArcAngleStart() / 10.0; c0 = t.GetCenter(); r = t.GetRadius(); da = t.GetAngle().AsDegrees()
        a0 = math.degrees(math.atan2(s.y - c0.y, s.x - c0.x)); N = 8; prev = (s.x, s.y)
        for i in range(1, N + 1):
            ang = math.radians(a0 + da * i / N); q = (c0.x + r * math.cos(ang), c0.y + r * math.sin(ang))
            tracks.append([LI.get(t.GetLayer(), 0), mm(prev[0]), mm(prev[1]), mm(q[0]), mm(q[1]), mm(t.GetWidth()), nid(t.GetNet())]); prev = q
    else:
        s, e = t.GetStart(), t.GetEnd()
        tracks.append([LI.get(t.GetLayer(), 0), mm(s.x), mm(s.y), mm(e.x), mm(e.y), mm(t.GetWidth()), nid(t.GetNet())])
SH = {pcbnew.PAD_SHAPE_CIRCLE: 'c', pcbnew.PAD_SHAPE_RECT: 'r', pcbnew.PAD_SHAPE_OVAL: 'o', pcbnew.PAD_SHAPE_ROUNDRECT: 'q'}
for f in b.GetFootprints():
    for p in f.Pads():
        ls = p.GetLayerSet(); mask = sum(1 << LI[l] for l in LI if ls.Contains(l))
        if not mask: continue
        pos = p.GetPosition(); sz = p.GetSize(pcbnew.F_Cu); d = p.GetDrillSize()
        pads.append([mm(pos.x), mm(pos.y), mm(sz.x), mm(sz.y), round(p.GetOrientationDegrees(), 1), SH.get(p.GetShape(), 'r'), mask, nid(p.GetNet()),
                     mm(d.x), mm(d.y), f.GetReference(), p.GetNumber()])
outline, holes = [], []
for d in b.GetDrawings():
    if d.GetLayerName() != 'Edge.Cuts': continue
    if d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
        c = d.GetCenter(); holes.append([mm(c.x), mm(c.y), mm(d.GetRadius())])
    elif d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
        s, e = d.GetStart(), d.GetEnd(); outline.append([mm(s.x), mm(s.y), mm(e.x), mm(e.y)])
    elif d.GetShape() == pcbnew.SHAPE_T_ARC:
        s, e, c0 = d.GetStart(), d.GetEnd(), d.GetCenter(); r = d.GetRadius(); a0 = math.atan2(s.y - c0.y, s.x - c0.x); da = math.radians(d.GetArcAngle().AsDegrees()); prev = s
        for i in range(1, 9):
            a = a0 + da * i / 8; q = (c0.x + r * math.cos(a), c0.y + r * math.sin(a)); outline.append([mm(prev.x if hasattr(prev, 'x') else prev[0]), mm(prev.y if hasattr(prev, 'y') else prev[1]), mm(q[0]), mm(q[1])]); prev = q
# drilled holes with no pad (NPTH are pads in footprints, so already in pads)
json.dump({'bbox': [76.0, 76.0, 124.0, 124.0], 'nets': names, 'tracks': tracks, 'vias': vias, 'pads': pads, 'outline': outline, 'holes': holes},
          open(sys.argv[2], 'w'), separators=(',', ':'))
print('nets', len(names), 'tracks', len(tracks), 'vias', len(vias), 'pads', len(pads), 'outline segs', len(outline), 'holes', len(holes))
