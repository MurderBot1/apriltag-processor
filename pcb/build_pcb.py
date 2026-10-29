"""Build the AprilTag camera PCB with KiCad's pcbnew Python API (run with KiCad's python):
   "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/build_pcb.py [--route] [--fill]
Steps: place footprints + nets (pcb/design.py) -> outline/holes/planes -> Specctra export -> Freerouting -> import SES ->
fill zones -> save pcb/output/apriltag_cam.kicad_pcb.  Fabrication outputs / DRC are produced by pcb/make_outputs.py."""
import os, sys, math, json, subprocess, shutil
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design as D

FPROOT = r'C:\Program Files\KiCad\10.0\share\kicad\footprints'
OUT = os.path.join(HERE, 'output'); os.makedirs(OUT, exist_ok=True)
CX, CY = 100.0, 100.0                       # board centre in KiCad coordinates (mm)
mm = pcbnew.FromMM


def V(x, y): return pcbnew.VECTOR2I(mm(CX + x), mm(CY - y))


# ---------------------------------------------------------------------------------------------- custom footprints
def make_sensor_fp(b):
    fp = pcbnew.FOOTPRINT(b)
    fp.SetFPID(pcbnew.LIB_ID('apriltag_cam', 'OV9281_CSP'))
    pitch, dia = 0.5, 0.25
    rows = 'ABCDEFGH'
    for name in D.SENSOR_BALLS:
        r, c = rows.index(name[0]), int(name[1:])
        pad = pcbnew.PAD(fp)
        pad.SetNumber(name); pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE); pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetSize(pcbnew.VECTOR2I(mm(dia), mm(dia))); pad.SetLayerSet(pad.SMDMask())
        pad.SetPosition(pcbnew.VECTOR2I(mm((c - 5) * pitch), mm((r - 3.5) * pitch)))
        fp.Add(pad)
    for (a, bb, l) in (((-2.65, -2.25), (2.65, -2.25), 'F.SilkS'), ((2.65, -2.25), (2.65, 2.25), 'F.SilkS'),
                       ((2.65, 2.25), (-2.65, 2.25), 'F.SilkS'), ((-2.65, 2.25), (-2.65, -2.25), 'F.SilkS')):
        s = pcbnew.PCB_SHAPE(fp); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.F_SilkS); s.SetWidth(mm(0.12))
        s.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1]))); s.SetEnd(pcbnew.VECTOR2I(mm(bb[0]), mm(bb[1]))); fp.Add(s)
    return fp


def make_lens_mount_fp(b):
    fp = pcbnew.FOOTPRINT(b)
    fp.SetFPID(pcbnew.LIB_ID('apriltag_cam', 'M12_LENS_MOUNT'))
    for x in (-10.0, 10.0):
        pad = pcbnew.PAD(fp)
        pad.SetNumber(''); pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE); pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
        pad.SetSize(pcbnew.VECTOR2I(mm(2.6), mm(2.6))); pad.SetDrillSize(pcbnew.VECTOR2I(mm(2.6), mm(2.6)))
        pad.SetLayerSet(pad.UnplatedHoleMask()); pad.SetPosition(pcbnew.VECTOR2I(mm(x), 0)); fp.Add(pad)
    for (a, bb) in (((-10, -10), (10, -10)), ((10, -10), (10, 10)), ((10, 10), (-10, 10)), ((-10, 10), (-10, -10))):
        s = pcbnew.PCB_SHAPE(fp); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.F_Fab); s.SetWidth(mm(0.1))
        s.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1]))); s.SetEnd(pcbnew.VECTOR2I(mm(bb[0]), mm(bb[1]))); fp.Add(s)
    return fp


def load_fp(b, p):
    if p['lib'] == 'CUSTOM':
        return make_sensor_fp(b) if p['fp'] == 'OV9281_CSP' else make_lens_mount_fp(b)
    return pcbnew.FootprintLoad(os.path.join(FPROOT, p['lib'] + '.pretty'), p['fp'])


def mating_dir_ok(fp, want=(-1, 0)):
    """USB-C: the mating face is on the opposite side of the signal pads; return True if it points along `want`."""
    sig = [pa for pa in fp.Pads() if pa.GetNumber() in ('A5', 'A6', 'B5', 'B6')]
    cx = sum(pa.GetPosition().x for pa in sig) / len(sig); cy = sum(pa.GetPosition().y for pa in sig) / len(sig)
    bb = fp.GetBoundingBox(False)
    ox, oy = (bb.GetCenter().x - cx), (bb.GetCenter().y - cy)       # from pads towards body centre = towards the mating face
    n = math.hypot(ox, oy) or 1
    return (ox / n) * want[0] + (-oy / n) * want[1] > 0.9           # y up convention for `want`


def place(b, p, netmap):
    fp = load_fp(b, p)
    fp.SetReference(p['ref']); fp.SetValue(p['value'])
    b.Add(fp)
    pos = V(p['x'], p['y'])
    angles = [p['rot']] if p['ref'] not in ('J1', 'U1') else [0, 90, 180, 270]
    best = None
    for ang in angles:
        if fp.IsFlipped(): fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(pos)
        fp.SetOrientationDegrees(ang)
        if p['side'] == 'bottom': fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(pos)
        if p['ref'] == 'J1' and mating_dir_ok(fp): break
        if p['ref'] == 'U1':
            mp = [pa for pa in fp.Pads() if p['nets'].get(pa.GetNumber(), '').startswith('MIPI_')]
            cy = sum(pa.GetPosition().y for pa in mp) / len(mp)
            sc = -(cy - pos.y)                       # y up: bigger = further towards the sensor (+Y)
            if best is None or sc > best[0]: best = (sc, ang)
    if p['ref'] == 'U1':
        if fp.IsFlipped(): fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(pos); fp.SetOrientationDegrees(best[1]); fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT); fp.SetPosition(pos)
        print('U1 orientation', best)
    for pad in fp.Pads():
        n = p['nets'].get(pad.GetNumber(), '')
        if n: pad.SetNet(netmap[n])
    # keep silkscreen reference text small, off the copper
    fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6))); fp.Reference().SetTextThickness(mm(0.1))
    fp.Value().SetVisible(False)
    return fp


# ---------------------------------------------------------------------------------------------- board
def edge_line(b, a, c, layer=pcbnew.Edge_Cuts):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(layer); s.SetWidth(mm(0.1))
    s.SetStart(V(*a)); s.SetEnd(V(*c)); b.Add(s)


def edge_arc(b, centre, start, end):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_ARC); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
    s.SetCenter(V(*centre)); s.SetStart(V(*start)); s.SetEnd(V(*end)); b.Add(s)


def outline(b, w, h, r):
    x, y = w / 2, h / 2
    edge_line(b, (-x + r, y), (x - r, y)); edge_line(b, (x, y - r), (x, -y + r))
    edge_line(b, (x - r, -y), (-x + r, -y)); edge_line(b, (-x, -y + r), (-x, y - r))
    edge_arc(b, (x - r, y - r), (x - r, y), (x, y - r)); edge_arc(b, (x - r, -y + r), (x, -y + r), (x - r, -y))
    edge_arc(b, (-x + r, -y + r), (-x + r, -y), (-x, -y + r)); edge_arc(b, (-x + r, y - r), (-x, y - r), (-x + r, y))


def add_zone(b, net, layer, pts, prio=0, name=''):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer); z.SetNet(net); z.SetAssignedPriority(prio)
    z.SetMinThickness(mm(0.15)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(mm(0.2)); z.SetThermalReliefSpokeWidth(mm(0.25))
    ol = z.Outline(); ol.NewOutline()
    for (x, y) in pts: ol.Append(mm(CX + x), mm(CY - y))
    z.SetZoneName(name)
    b.Add(z)
    return z



# ---------------------------------------------------------------------------------------------- placement legaliser
FIXED = {'U1', 'U2', 'U3', 'J1', 'J2', 'U10', 'LH1', 'SW1', 'MH1', 'MH2', 'MH3', 'MH4'}


def rect_mm(fp):
    side = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    try:
        bb = fp.GetCourtyard(side).BBox()
        if bb.GetWidth() == 0: raise ValueError
    except Exception:
        bb = fp.GetBoundingBox(False)
    return [pcbnew.ToMM(bb.GetLeft()) - CX, pcbnew.ToMM(bb.GetTop()) - CY, pcbnew.ToMM(bb.GetRight()) - CX, pcbnew.ToMM(bb.GetBottom()) - CY]


def overlap(a, b, m=0.2):
    return not (a[2] + m <= b[0] or b[2] + m <= a[0] or a[3] + m <= b[1] or b[3] + m <= a[1])


def legalize(b):
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}
    W2, H2 = D.BW / 2 - 0.5, D.BH / 2 - 0.5
    obst = {'top': [], 'bottom': []}
    both = []
    for r in FIXED:
        if r not in fps: continue
        fp = fps[r]; rc = rect_mm(fp)
        if r.startswith('MH'):
            rc = [rc[0] - 1.2, rc[1] - 1.2, rc[2] + 1.2, rc[3] + 1.2]; both.append(rc)
        elif r == 'LH1':
            for hx in (-10.0, 10.0):
                both.append([D.SENSOR_POS[0] + hx - 1.6, -(D.SENSOR_POS[1]) - 1.6, D.SENSOR_POS[0] + hx + 1.6, -(D.SENSOR_POS[1]) + 1.6])
            obst['top'].append([D.SENSOR_POS[0] - 10.2, -(D.SENSOR_POS[1] + 10.2), D.SENSOR_POS[0] + 10.2, -(D.SENSOR_POS[1] - 10.2)])
        else:
            obst['bottom' if fp.IsFlipped() else 'top'].append(rc)
    mov = [fps[r] for r in fps if r not in FIXED]
    mov.sort(key=lambda f: -(lambda r: (r[2] - r[0]) * (r[3] - r[1]))(rect_mm(f)))
    moved = 0
    for fp in mov:
        side = 'bottom' if fp.IsFlipped() else 'top'
        r0 = rect_mm(fp); w = r0[2] - r0[0]; h = r0[3] - r0[1]
        cands = [(0.0, 0.0)]
        step = 0.25
        for rad in range(1, 90):
            d = rad * step
            n = max(8, int(8 * rad))
            for k in range(n):
                a = 2 * math.pi * k / n
                cands.append((d * math.cos(a), d * math.sin(a)))
        for dx, dy in cands:
            rc = [r0[0] + dx, r0[1] + dy, r0[2] + dx, r0[3] + dy]
            if rc[0] < -W2 or rc[2] > W2 or rc[1] < -H2 or rc[3] > H2: continue
            if any(overlap(rc, o) for o in obst[side]) or any(overlap(rc, o) for o in both): continue
            if dx or dy:
                fp.Move(pcbnew.VECTOR2I(mm(dx), mm(dy))); moved += 1
            obst[side].append(rc)
            break
        else:
            print('WARNING: no free spot for', fp.GetReference())
    # hide small reference designators (fab drawing/BOM carry them)
    for fp in b.GetFootprints():
        big = fp.GetReference().startswith(('U', 'J', 'Y', 'SW', 'L')) or fp.GetReference() in ('U1',)
        fp.Reference().SetVisible(bool(big))
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8))); fp.Reference().SetTextThickness(mm(0.12))
    print('legalized: moved', moved, 'parts')


# ---------------------------------------------------------------------------------------------- plane fan-out
PLANE_NETS = ('GND', '+3V3', '+1V1')
VIA_D, VIA_DRILL = 0.45, 0.20


def fanout_planes(b, netmap, skip_refs=('U10', 'J2')):
    """A via (+ short locked stub) at every SMD pad of the plane nets so Freerouting only has to route signals and the
    low-current rails.  BGA balls use the diagonal gap sites; everything else a ring search around the pad."""
    obst = []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            p = pad.GetPosition()
            r = max(pcbnew.ToMM(pad.GetSizeX()), pcbnew.ToMM(pad.GetSizeY())) / 2
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH: r = pcbnew.ToMM(pad.GetDrillSize().x) / 2 + 0.3
            obst.append([pcbnew.ToMM(p.x), pcbnew.ToMM(p.y), r])
    vias = []
    n_done = n_fail = 0
    W2, H2 = CX + D.BW / 2 - 0.4, CY + D.BH / 2 - 0.4

    def seg_ok(ax, ay, bx, by, self_xy, w):
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1e-9
        for ox, oy, r in obst:
            if abs(ox - self_xy[0]) < 1e-6 and abs(oy - self_xy[1]) < 1e-6: continue
            t = max(0.0, min(1.0, ((ox - ax) * dx + (oy - ay) * dy) / L2))
            if (ax + t * dx - ox) ** 2 + (ay + t * dy - oy) ** 2 < (r + w / 2 + 0.12) ** 2: return False
        return True

    def free(x, y, self_xy, m=0.15):
        if x < CX - D.BW / 2 + 0.4 or x > W2 or y < CY - D.BH / 2 + 0.4 or y > H2: return False
        for ox, oy, r in obst:
            if abs(ox - self_xy[0]) < 1e-6 and abs(oy - self_xy[1]) < 1e-6: continue
            if (ox - x) ** 2 + (oy - y) ** 2 < (r + VIA_D / 2 + m) ** 2: return False
        for vx, vy in vias:
            if (vx - x) ** 2 + (vy - y) ** 2 < (VIA_D + 0.15) ** 2: return False
        return True

    for fp in b.GetFootprints():
        if fp.GetReference() in skip_refs: continue
        bga = 'BGA' in str(fp.GetFPID().GetLibItemName())
        for pad in fp.Pads():
            if pad.GetNetname() not in PLANE_NETS: continue
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD: continue
            p = pad.GetPosition(); px, py = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
            pr = max(pcbnew.ToMM(pad.GetSizeX()), pcbnew.ToMM(pad.GetSizeY())) / 2
            if pr > 1.0:                                   # exposed pad: 2x2 grid of vias inside the pad
                net = pad.GetNet()
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        vx, vy = px + sx * min(0.9, pr * 0.5), py + sy * min(0.9, pr * 0.5)
                        v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(vx), mm(vy))); v.SetWidth(mm(0.5)); v.SetDrill(mm(0.25))
                        v.SetNet(net); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLocked(True); b.Add(v); vias.append((vx, vy)); obst.append([vx, vy, 0.25])
                n_done += 1
                continue
            cands = []
            if bga:
                cands += [(px + sx * 0.4, py + sy * 0.4) for sx in (1, -1) for sy in (1, -1)]
            else:
                cx0, cy0 = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
                base = math.atan2(py - cy0, px - cx0)
                for k in range(1, 40):
                    d = pr + VIA_D / 2 + 0.18 + 0.12 * k
                    for a in (0, 0.5, -0.5, 1.0, -1.0, 1.57, -1.57, 2.4, -2.4, 3.14):
                        cands.append((px + d * math.cos(base + a), py + d * math.sin(base + a)))
            for (vx, vy) in cands:
                if free(vx, vy, (px, py), 0.12 if bga else 0.2) and seg_ok(px, py, vx, vy, (px, py), 0.15 if bga else 0.12):
                    layer = pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
                    net = pad.GetNet()
                    t = pcbnew.PCB_TRACK(b); t.SetStart(p); t.SetEnd(pcbnew.VECTOR2I(mm(vx), mm(vy)))
                    t.SetWidth(mm(0.15 if bga else 0.12)); t.SetLayer(layer); t.SetNet(net); t.SetLocked(True); b.Add(t)
                    v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(vx), mm(vy))); v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL))
                    v.SetNet(net); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLocked(True); b.Add(v)
                    vias.append((vx, vy)); obst.append([vx, vy, VIA_D / 2])
                    n_done += 1
                    break
            else:
                n_fail += 1
                print('WARNING: no via site for', fp.GetReference(), pad.GetNumber(), pad.GetNetname())
    print('plane fan-out:', n_done, 'vias,', n_fail, 'failed')


def build(route=False):
    b = pcbnew.BOARD()
    b.SetCopperLayerCount(4)
    ds = b.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.1); ds.m_MinClearance = mm(0.1); ds.m_ViasMinSize = mm(0.45); ds.m_MinThroughDrill = mm(0.2)
    ds.m_CopperEdgeClearance = mm(0.25); ds.m_HoleToHoleMin = mm(0.25)
    ns = ds.m_NetSettings
    dn = ns.GetDefaultNetclass()
    dn.SetClearance(mm(0.1)); dn.SetTrackWidth(mm(0.12)); dn.SetViaDiameter(mm(0.45)); dn.SetViaDrill(mm(0.2))
    pw = pcbnew.NETCLASS('Power')
    pw.SetClearance(mm(0.12)); pw.SetTrackWidth(mm(0.3)); pw.SetViaDiameter(mm(0.6)); pw.SetViaDrill(mm(0.3))
    ns.SetNetclass('Power', pw)
    for n in ('+5V', 'VBUS', '+3V3', '+1V1', '+1V8', '+2V5', '+2V8', '+1V2', '+1V1MCU', 'SW3V3', 'SW1V1', 'VREG_LX'):
        ns.SetNetclassPatternAssignment(n, 'Power')
    netmap = {}
    for name in D.nets_used() + ['GND']:
        if name in netmap: continue
        ni = pcbnew.NETINFO_ITEM(b, name); b.Add(ni); netmap[name] = ni
    outline(b, D.BW, D.BH, D.P['board']['corner_radius'])
    for p in D.parts:
        place(b, p, netmap)
    legalize(b)
    # ---- planes: In1 = GND (whole board), In2 = +3V3 (whole board)
    pts = [(-D.BW / 2 + 0.3, D.BH / 2 - 0.3), (D.BW / 2 - 0.3, D.BH / 2 - 0.3), (D.BW / 2 - 0.3, -D.BH / 2 + 0.3), (-D.BW / 2 + 0.3, -D.BH / 2 + 0.3)]
    add_zone(b, netmap['GND'], pcbnew.In1_Cu, pts, 0, 'GND_PLANE')
    add_zone(b, netmap['+3V3'], pcbnew.In2_Cu, pts, 0, '3V3_PLANE')
    fx, fy = D.FPGA_POS
    isl = [(fx - 2.8, fy + 2.8), (fx + 2.8, fy + 2.8), (fx + 2.8, fy - 2.8), (fx - 2.8, fy - 2.8)]
    add_zone(b, netmap['+1V1'], pcbnew.In2_Cu, isl, 1, '1V1_ISLAND')        # FPGA core supply: only GND balls share this area
    fanout_planes(b, netmap)
    path = os.path.join(OUT, 'apriltag_cam_unrouted.kicad_pcb')
    b.Save(path)
    return b, path


def route(b, unrouted_path, max_passes=40):
    dsn = os.path.join(OUT, 'apriltag_cam.dsn'); ses = os.path.join(OUT, 'apriltag_cam.ses')
    if os.path.exists(ses): os.remove(ses)
    ok = pcbnew.ExportSpecctraDSN(b, dsn)
    print('DSN export', ok)
    java = r'C:\Program Files\Java\jdk-25\bin\java.exe'
    cmd = [java, '-jar', os.path.join(HERE, 'tools', 'freerouting.jar'), '-de', dsn, '-do', ses, '-mp', str(max_passes), '--gui.enabled=false']
    print(' '.join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get('ROUTE_TIMEOUT', 2700)))
    except subprocess.TimeoutExpired as e:
        print('freerouting timed out'); return False
    open(os.path.join(OUT, 'freerouting.log'), 'w').write(r.stdout + r.stderr)
    print(r.stdout[-800:], r.stderr[-400:])
    if os.path.exists(ses):
        print('SES import', pcbnew.ImportSpecctraSES(b, ses))
    return os.path.exists(ses)


def finish(b, name='apriltag_cam.kicad_pcb'):
    filler = pcbnew.ZONE_FILLER(b)
    filler.Fill(b.Zones())
    pcbnew.SaveBoard(os.path.join(OUT, name), b)


if __name__ == '__main__':
    b, path = build()
    print('placed', len(D.parts), 'parts ->', path)
    if '--route' in sys.argv:
        route(b, path, int(os.environ.get('MAX_PASSES', 40)))
    if '--fill' in sys.argv or '--route' in sys.argv:
        finish(b)
    else:
        pcbnew.SaveBoard(os.path.join(OUT, 'apriltag_cam.kicad_pcb'), b)
