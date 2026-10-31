"""Dump a KiCad board (pcbnew, internal coordinates in mm) into the flat text format read by router.cpp.
usage: kicad-python export_problem.py <board.kicad_pcb> <problem.txt>"""
import sys, math, pcbnew

PLANES = ('GND', '+3V3')
POWER = ('+1V1', '+1V1MCU', '+1V2', '+1V8', '+2V5', '+2V8', '+5V', 'SW1V1', 'SW3V3', 'VBUS', 'VREG_LX')   # 0.3 mm net class
mm = pcbnew.ToMM


def main(src, dst):
    b = pcbnew.LoadBoard(src)
    nets = {}
    def nid(name):
        if not name: return -1
        if name not in nets: nets[name] = len(nets)
        return nets[name]
    lines = []
    bb = b.GetBoardEdgesBoundingBox()
    corner = 0.0
    try:
        import json, os
        corner = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pcb_params.json')))['board']['corner_radius']
    except Exception: pass
    lines.append(f"B {mm(bb.GetLeft()):.4f} {mm(bb.GetTop()):.4f} {mm(bb.GetRight()):.4f} {mm(bb.GetBottom()):.4f} {corner}")
    def lmask(item):
        return (1 if item.IsOnLayer(pcbnew.F_Cu) else 0) | (2 if item.IsOnLayer(pcbnew.B_Cu) else 0) | (4 if item.IsOnLayer(pcbnew.In2_Cu) and item.GetClass() != 'PAD' else 0)   # In2 copper of an already routed board is an obstacle too
    # fan-out geometry already on the board
    touch = []                                    # (x, y) of via centres / track ends, for 'already connected' tests
    cls_of = {}
    for t in b.GetTracks():
        n = nid(t.GetNetname())
        if t.GetClass() == 'PCB_VIA':
            p = t.GetPosition(); x, y = mm(p.x), mm(p.y)
            lines.append(f"C {n} 3 1 {x:.4f} {y:.4f} {mm(t.GetWidth(pcbnew.F_Cu))/2:.4f} 0 0")
            touch.append((n, x, y))
        else:
            s, e = t.GetStart(), t.GetEnd()
            lines.append(f"C {n} {lmask(t)} 2 {mm(s.x):.4f} {mm(s.y):.4f} {mm(e.x):.4f} {mm(e.y):.4f} {mm(t.GetWidth()):.4f}")
            touch += [(n, mm(s.x), mm(s.y)), (n, mm(e.x), mm(e.y))]
    island = None
    for z in b.Zones():
        if z.GetZoneName() == '1V1_ISLAND':
            zb = z.GetBoundingBox(); island = (mm(zb.GetLeft()), mm(zb.GetTop()), mm(zb.GetRight()), mm(zb.GetBottom()))
    if island:                                # the 1V1 pour on In2: one big already-connected target for every +1V1 pin
        lines.append(f"P {nid('+1V1')} 4 2 0 {island[0]+0.4:.3f} {island[1]+0.4:.3f} {island[2]-0.4:.3f} {island[3]-0.4:.3f} 0")
    pins = []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            name = pad.GetNetname(); n = nid(name)
            box = pad.GetBoundingBox()
            x0, y0, x1, y1 = mm(box.GetLeft()), mm(box.GetTop()), mm(box.GetRight()), mm(box.GetBottom())
            m = lmask(pad)
            dr = pad.GetDrillSize()
            if dr.x > 0:
                p = pad.GetPosition()
                lines.append(f"H {mm(p.x):.4f} {mm(p.y):.4f} {mm(max(dr.x, dr.y))/2:.4f}")
            if m == 0: continue
            sh = pad.GetShape()
            if sh == pcbnew.PAD_SHAPE_CIRCLE:
                shape = f"1 {(x0+x1)/2:.4f} {(y0+y1)/2:.4f} {(x1-x0)/2:.4f} 0 0"
            elif sh == pcbnew.PAD_SHAPE_OVAL:
                w, h = x1 - x0, y1 - y0
                if w >= h:
                    shape = f"2 {x0+h/2:.4f} {(y0+y1)/2:.4f} {x1-h/2:.4f} {(y0+y1)/2:.4f} {h:.4f}"
                else:
                    shape = f"2 {(x0+x1)/2:.4f} {y0+w/2:.4f} {(x0+x1)/2:.4f} {y1-w/2:.4f} {w:.4f}"
            else:
                rr = sh in (pcbnew.PAD_SHAPE_ROUNDRECT, pcbnew.PAD_SHAPE_CHAMFERED_RECT)
                inset = min(0.15, 0.3 * min(x1 - x0, y1 - y0)) if rr else 0.03        # track ends stay clear of rounded corners
                shape = f"0 {x0:.4f} {y0:.4f} {x1:.4f} {y1:.4f} {inset:.3f}"
            need = 1
            if island and name == '+1V1' and island[0] <= (x0 + x1) / 2 <= island[2] and island[1] <= (y0 + y1) / 2 <= island[3] and any(tn == n and x0 - 0.05 <= tx <= x1 + 0.05 and y0 - 0.05 <= ty <= y1 + 0.05 for tn, tx, ty in touch): continue
            if name in PLANES:
                tht = (m == 3)
                near = any(tn == n and x0 - 0.05 <= tx <= x1 + 0.05 and y0 - 0.05 <= ty <= y1 + 0.05 for tn, tx, ty in touch)
                need = 0 if (tht or near) else 1
            lines.append(f"P {n} {m} {need} {shape}")
    for t in b.GetNetsByName() if False else []: pass
    out = []
    for name, i in sorted(nets.items(), key=lambda kv: kv[1]):
        cl = 2 if name in PLANES else 0
        try:
            if name in POWER and name not in PLANES: cl = 1
        except Exception: pass
        out.append(f"N {i} {cl} {name.replace(' ', '_')}")
    with open(dst, 'w') as f:
        f.write('\n'.join(out + lines) + '\n')
    print('nets', len(nets), 'records', len(lines))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
