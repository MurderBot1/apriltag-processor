"""Second router pass: take a routed board + its DRC json, and write a problem file whose only jobs connect the
'unconnected' clusters (plane pours cut by tracks/vias).  usage: kicad-python make_fix_problem.py board.kicad_pcb drc.json out.txt"""
import sys, re, math, json, subprocess, os
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__))
mm = pcbnew.ToMM


def main(board, drcjson, out):
    base = os.path.join(os.path.dirname(out), '_fix_base.txt')
    subprocess.run([sys.executable, os.path.join(HERE, 'export_problem.py'), board, base], check=True)
    b = pcbnew.LoadBoard(board)
    lines = open(base).read().splitlines()
    nets = {}
    for l in lines:
        f = l.split()
        if f and f[0] == 'N': nets[f[3]] = int(f[1])
    nxt = max(nets.values()) + 1
    layer_bit = {'F.Cu': 1, 'B.Cu': 2, 'In2.Cu': 4, 'In1.Cu': 0}

    def find(desc, pos):
        px, py = pos['x'], pos['y']
        m = re.match(r"Track \[([^\]]+)\] on (\S+?),", desc)
        if m:
            for t in b.GetTracks():
                if t.GetClass() == 'PCB_VIA' or t.GetNetname() != m.group(1): continue
                s, e = t.GetStart(), t.GetEnd()
                ax, ay, bx, by = mm(s.x), mm(s.y), mm(e.x), mm(e.y)
                L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-9
                u = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
                if math.hypot(px - (ax + u * (bx - ax)), py - (ay + u * (by - ay))) < 0.03 and t.GetLayerName() == m.group(2):
                    return m.group(1), layer_bit[m.group(2)], f"2 {ax:.4f} {ay:.4f} {bx:.4f} {by:.4f} {mm(t.GetWidth()):.4f}"
            return None
        m = re.match(r"Via \[([^\]]+)\]", desc)
        if m:
            for t in b.GetTracks():
                if t.GetClass() == 'PCB_VIA' and t.GetNetname() == m.group(1) and math.hypot(mm(t.GetPosition().x) - px, mm(t.GetPosition().y) - py) < 0.03:
                    return m.group(1), 7, f"1 {mm(t.GetPosition().x):.4f} {mm(t.GetPosition().y):.4f} 0.2250 0 0"
            return None
        m = re.match(r"Pad (\S+) \[([^\]]+)\] of (\S+) on (\S+)", desc)
        if m:
            fp = b.FindFootprintByReference(m.group(3))
            for pad in fp.Pads():
                if pad.GetNumber() == m.group(1):
                    bb = pad.GetBoundingBox()
                    x0, y0, x1, y1 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
                    if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                        sh = f"1 {(x0+x1)/2:.4f} {(y0+y1)/2:.4f} {(x1-x0)/2:.4f} 0 0"
                    else:
                        sh = f"0 {x0:.4f} {y0:.4f} {x1:.4f} {y1:.4f} 0.060"
                    return m.group(2), layer_bit.get(m.group(4), 3), sh
            return None
        return None

    d = json.load(open(drcjson))
    extra_n, extra_p, k = [], [], 0
    for u in d.get('unconnected_items', []):
        its = [find(i['description'], i['pos']) for i in u['items'][:2]]
        if len(its) < 2 or None in its or its[0][0] != its[1][0]: continue
        name = its[0][0]
        if name == 'GND' and False: continue
        fid = nxt + k; k += 1
        extra_n.append(f"N {fid} {1 if name.startswith('+1V1') else 0} {name}~fix{k}")
        for _, mask, sh in its:
            extra_p.append(f"P {fid} {mask} 3 {sh}")
    with open(out, 'w') as f:
        f.write('\n'.join([l for l in lines if l.startswith('N ')] + extra_n + [l for l in lines if not l.startswith('N ')] + extra_p) + '\n')
    print('fix jobs', k)


if __name__ == '__main__':
    main(*sys.argv[1:4])
