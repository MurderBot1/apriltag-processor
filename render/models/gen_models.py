"""Parametric real-dimension STEP models for parts that have no model in the KiCad 10 official 3D library.
Run:  "C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe" render/models/gen_models.py     (writes render/models/*.step, coloured)
Needs render/work/localpads.json (pad positions in file-local footprint coordinates, dumped by render/dump_pads.py with pcbnew).
Model frame convention (what kicad-cli expects): origin = footprint origin, +z away from the board surface the part sits on.
For B.Cu footprints KiCad mirrors the model about the X axis, so model (x, y) == file-local pad (x, y); for F.Cu parts model y = -file y.
Colours are written as STEP STYLED_ITEMs by post-processing (FreeCAD headless cannot colour).
"""
import os, re, json, math
import FreeCAD, Part, Import
from FreeCAD import Vector as V
RENDER = (os.environ.get('RENDER_DIR') or os.getcwd()).replace(chr(92), '/')   # render/ of THIS clone (run_all.sh exports RENDER_DIR)
HERE = RENDER + '/models'
PADS = json.load(open(RENDER + '/work/localpads.json'))

def box(x0, x1, y0, y1, z0, z1): return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))
def cbox(cx, cy, dx, dy, z0, z1): return box(cx - dx / 2, cx + dx / 2, cy - dy / 2, cy + dy / 2, z0, z1)
def cyl(cx, cy, r, z0, z1): return Part.makeCylinder(r, z1 - z0, V(cx, cy, z0), V(0, 0, 1))

def revolve(profile):
    """profile [(r,z)...] closed polygon -> solid of revolution about the vertical axis through the origin"""
    pts = [V(r, 0, z) for r, z in profile] + [V(profile[0][0], 0, profile[0][1])]
    f = Part.Face(Part.makePolygon(pts))
    return f.revolve(V(0, 0, 0), V(0, 0, 1), 360)

MODELS = {}   # name -> list of (colour(r,g,b), shape)
def add(name, parts): MODELS[name] = parts
BLACK = (0.07, 0.07, 0.08); SILVER = (0.80, 0.80, 0.82); TIN = (0.72, 0.72, 0.74); GOLD = (0.83, 0.68, 0.22)

def ball(cx, cy, r=0.225, h=0.30):
    """solder ball collapsed on its pad: sphere truncated at z=0 and z=h"""
    s = Part.makeSphere(r * 1.12, V(cx, cy, h * 0.5))
    return s.common(box(cx - 1, cx + 1, cy - 1, cy + 1, 0, h))

# ---------------------------------------------------------------- U1  ECP5 LFE5U-85F caBGA-381 (17x17 mm, 0.8 mm pitch, 20x20 ball matrix)
# Lattice caBGA381 outline: body 17.0 x 17.0, A(max) 1.40 incl. ball, ball dia 0.45 (collapsed height ~0.30). Balls sit on the real footprint pads.
pads = PADS['U1']['pads']; seen = set(); balls = []
b0 = ball(0, 0)
for n, x, y, sx, sy, at, dr in pads:
    if (x, y) in seen: continue
    seen.add((x, y)); b = b0.copy(); b.translate(V(x, y, 0)); balls.append(b)
p1 = [p for p in pads if p[0] == 'A2'][0]
sx1 = -1 if p1[1] < 0 else 1; sy1 = -1 if p1[2] < 0 else 1
add('Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm', [
    (SILVER, Part.makeCompound(balls)),
    ((0.10, 0.13, 0.10), box(-8.5, 8.5, -8.5, 8.5, 0.30, 0.62)),                      # laminate substrate
    ((0.05, 0.05, 0.055), box(-8.5, 8.5, -8.5, 8.5, 0.62, 1.30)),                     # mould cap
    ((0.45, 0.45, 0.47), cyl(sx1 * 7.4, sy1 * 7.4, 0.35, 1.30, 1.32)),                # pin-A1 mark
])

# ---------------------------------------------------------------- U2  RP2350A  QFN-60 7x7 mm, 0.4 mm pitch, EP 3.4x3.4 (QFN-60 7x7x0.9)
qp = [p for p in PADS['U2']['pads'] if p[0] != '']
leads = []
for n, x, y, sx, sy, at, dr in qp:
    if n == '61': continue
    if abs(x) > abs(y):
        a, b = (3.0, 3.5) if x > 0 else (-3.5, -3.0); leads.append(box(a, b, y - .1, y + .1, 0.0, 0.2))
    else:
        a, b = (3.0, 3.5) if y > 0 else (-3.5, -3.0); leads.append(box(x - .1, x + .1, a, b, 0.0, 0.2))
q1 = [p for p in qp if p[0] == '1'][0]
add('QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm', [
    (BLACK, box(-3.5, 3.5, -3.5, 3.5, 0.02, 0.85)),
    (TIN, Part.makeCompound(leads)),
    (TIN, box(-1.7, 1.7, -1.7, 1.7, 0.0, 0.05)),
    ((0.5, 0.5, 0.52), cyl(math.copysign(2.75, q1[1]), math.copysign(2.75, q1[2]), 0.28, 0.85, 0.87)),
])

# ---------------------------------------------------------------- Y2  Abracon ASE-series SMD oscillator 3.2 x 2.5 x 0.95 mm (ceramic base, metal lid, 4 pads)
add('Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm', [
    ((0.80, 0.76, 0.62), box(-1.6, 1.6, -1.25, 1.25, 0.08, 0.62)),
    (SILVER, box(-1.45, 1.45, -1.10, 1.10, 0.62, 0.95)),
    (GOLD, Part.makeCompound([cbox(sx * 1.1, sy * 0.825, 0.9, 0.85, 0.0, 0.1) for sx in (-1, 1) for sy in (-1, 1)] +
                             [cbox(sx * 1.55, sy * 0.825, 0.1, 0.85, 0.0, 0.62) for sx in (-1, 1) for sy in (-1, 1)])),
    ((0.15, 0.15, 0.15), cyl(-1.0, 0.65, 0.12, 0.95, 0.96)),
])

# ---------------------------------------------------------------- J1  HRO TYPE-C-31-M-12 USB-C 16P receptacle (8.94 w x 3.26 h x 7.3 deep shell, 4 THT shield legs)
pj = PADS['J1']['pads']
Yf, Yr = -4.0, 3.3
def stadium(w, h, y0, y1, r):
    b = box(-w / 2, w / 2, y0, y1, 0, h)
    ed = [e for e in b.Edges if abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) > 1e-6]
    return b.makeFillet(r, ed)
outer = stadium(8.94, 3.26, Yf, Yr, 1.2)
cav = stadium(8.94 - 0.4, 3.26 - 0.4, Yf - 0.1, Yr - 0.6, 1.0); cav.translate(V(0, 0, 0.2))
shell = outer.cut(cav)
tongue = box(-3.4, 3.4, Yf + 1.0, Yr - 0.3, 1.28, 1.98)
rear = box(-4.2, 4.2, Yr - 0.9, Yr - 0.3, 0.2, 3.06)
uleads = []; seenx = set()
for n, x, y, sx, sy, at, dr in pj:
    if at == 1 and x not in seenx:
        seenx.add(x); uleads.append(box(x - sx / 2, x + sx / 2, Yr - 0.4, y + sy / 2, 0.0, 0.15))
legs = [cyl(x, y, 0.28, -1.6, 0.6) for n, x, y, sx, sy, at, dr in pj if at == 0]
pegs = [cyl(x, y, 0.3, -1.4, 0.3) for n, x, y, sx, sy, at, dr in pj if at == 3]
add('USB_C_Receptacle_HRO_TYPE-C-31-M-12', [
    (SILVER, shell), ((0.05, 0.05, 0.06), Part.makeCompound([rear] + pegs)), ((0.05, 0.05, 0.06), tongue),
    (GOLD, Part.makeCompound([box(x - .12, x + .12, Yf + 1.0, Yr - 0.3, 1.98, 2.02) for x in sorted(seenx)])),
    (TIN, Part.makeCompound(uleads + legs)),
])

# ---------------------------------------------------------------- U10  OmniVision OV9281 CSP (5.3 x 4.5 mm per pcb/pcb_params.json sensor.package; 0.7 mm total height)
po = PADS['U10']['pads']
sb = []; b2 = ball(0, 0, 0.14, 0.18)
for n, x, y, sx, sy, at, dr in po:
    b = b2.copy(); b.translate(V(x, -y, 0)); sb.append(b)
add('OV9281_CSP', [
    (SILVER, Part.makeCompound(sb)),
    ((0.12, 0.12, 0.14), box(-2.65, 2.65, -2.25, 2.25, 0.18, 0.40)),                  # silicon + RDL
    ((0.62, 0.72, 0.78), box(-2.65, 2.65, -2.25, 2.25, 0.40, 0.70)),                  # cover glass
    ((0.05, 0.04, 0.12), box(-1.92, 1.92, -1.2, 1.2, 0.70, 0.705)),                   # coated active array
])

# ---------------------------------------------------------------- TP  1.0 mm test pad (finish on the exposed pad, 0.05 mm)
add('TestPoint_Pad_D1.0mm', [(GOLD, cyl(0, 0, 0.5, 0, 0.05))])

# ---------------------------------------------------------------- LH1  M12 (S-mount) board-mount lens holder + M12x0.5 lens, optical axis at footprint origin
# holder: 20 mm (y) flanged body, screw holes at x=+-10 (footprint NPTH 2.6), 6 mm tall; lens: thread d12 P0.5, hex lock nut, focus body d14, ends 14 mm above holder
body = box(-8.0, 8.0, -10.0, 10.0, 0, 6.0)
extra = []
for sx in (-1, 1):
    extra.append(Part.makeCylinder(2.0, 3.0, V(sx * 10.0, 0, 0)))
    extra.append(box(sx * 8.0 if sx > 0 else -10.0, 10.0 if sx > 0 else -8.0, -2.0, 2.0, 0, 3.0))
holder = body.multiFuse(extra)
holder = holder.cut(Part.makeCylinder(6.4, 7, V(0, 0, 0)))
for sx in (-1, 1): holder = holder.cut(Part.makeCylinder(1.3, 4, V(sx * 10.0, 0, -0.5)))
holder = holder.cut(box(-5, 5, -8.5, 8.5, -0.1, 1.2))
holder = holder.removeSplitter()
prof = [(5.0, 1.6)]; z = 1.6
while z < 13.9:
    prof += [(5.75, z), (6.0, z + 0.125), (6.0, z + 0.25), (5.75, z + 0.375)]; z += 0.5
prof += [(5.75, z), (5.0, z)]
thread = revolve(prof)
focus = revolve([(5.0, 14.0), (7.0, 14.0), (7.0, 19.4), (6.2, 20.0), (5.0, 20.0)])
grip = [revolve([(7.0, 14.5 + 1.0 * i), (7.25, 14.6 + 1.0 * i), (7.25, 15.1 + 1.0 * i), (7.0, 15.2 + 1.0 * i)]) for i in range(5)]
bezel = revolve([(3.4, 19.7), (6.0, 19.7), (6.0, 20.05), (3.4, 20.05)])
hexw = Part.Face(Part.makePolygon([V(7.5 * math.cos(math.radians(60 * i)), 7.5 * math.sin(math.radians(60 * i)), 6.0) for i in range(7)]))
nut = hexw.extrude(V(0, 0, 2.0)).cut(Part.makeCylinder(5.9, 2.0, V(0, 0, 6.0)))
def element(zc, t, a, s1, s2):
    R1 = (a * a + s1 * s1) / (2 * s1); R2 = (a * a + s2 * s2) / (2 * s2)
    top = Part.makeSphere(R1, V(0, 0, zc + t / 2 + s1 - R1)); bot = Part.makeSphere(R2, V(0, 0, zc - t / 2 - s2 + R2))
    return top.common(bot).common(Part.makeCylinder(a, t + s1 + s2 + 0.1, V(0, 0, zc - t / 2 - s1 - 0.05)))
els = [element(19.0, 0.9, 3.3, 0.9, 0.5), element(17.4, 0.8, 3.9, 0.5, 0.7), element(15.4, 1.0, 4.3, 0.7, 0.7),
       element(12.6, 0.9, 4.3, 0.5, 0.4), element(9.5, 0.9, 4.5, 0.4, 0.7), element(5.5, 0.6, 4.3, 0.2, 0.2)]
spacers = [revolve([(4.4, z0), (5.0, z0), (5.0, z0 + 0.4), (4.4, z0 + 0.4)]) for z0 in (10.5, 14.0)]
add('M12_LENS_MOUNT', [
    ((0.07, 0.07, 0.08), holder),
    ((0.55, 0.56, 0.58), nut),
    ((0.03, 0.03, 0.035), Part.makeCompound([thread, focus] + grip)),
    ((0.12, 0.12, 0.13), bezel),
    ((0.35, 0.50, 0.62), Part.makeCompound(els)),
    ((0.01, 0.01, 0.01), Part.makeCompound(spacers)),
])

# ---------------------------------------------------------------- write + colour
def write(name, parts):
    doc = FreeCAD.newDocument('m'); objs = []
    for i, (col, sh) in enumerate(parts):
        o = doc.addObject('Part::Feature', 'c%d' % i); o.Shape = sh; objs.append(o)
    path = os.path.join(HERE, name + '.step'); Import.export(objs, path)
    FreeCAD.closeDocument(doc.Name)
    txt = open(path, encoding='utf8', errors='replace').read()
    ids = [int(m.group(1)) for m in re.finditer(r'^#(\d+)\s*=\s*MANIFOLD_SOLID_BREP', txt, re.M)]
    cols = []
    for col, sh in parts: cols += [col] * len(sh.Solids)
    print(name, 'solids in step', len(ids), 'expected', len(cols))
    if len(ids) != len(cols): return
    mx = max(int(m) for m in re.findall(r'^#(\d+)\s*=', txt, re.M)); n = mx + 1; out = []; palette = {}
    for sid, col in zip(ids, cols):
        if col not in palette:
            c, a, b, c2, d, e, f = n, n + 1, n + 2, n + 3, n + 4, n + 5, n + 6
            out.append("#%d=COLOUR_RGB('',%.4f,%.4f,%.4f);\n#%d=FILL_AREA_STYLE_COLOUR('',#%d);\n#%d=FILL_AREA_STYLE('',(#%d));\n#%d=SURFACE_STYLE_FILL_AREA(#%d);\n#%d=SURFACE_SIDE_STYLE('',(#%d));\n#%d=SURFACE_STYLE_USAGE(.BOTH.,#%d);\n#%d=PRESENTATION_STYLE_ASSIGNMENT((#%d));" % (c, col[0], col[1], col[2], a, c, b, a, c2, b, d, c2, e, d, f, e))
            palette[col] = f; n += 7
        out.append("#%d=STYLED_ITEM('color',(#%d),#%d);" % (n, palette[col], sid)); n += 1
    i = txt.rindex('ENDSEC;'); txt = txt[:i] + '\n'.join(out) + '\n' + txt[i:]
    open(path, 'w', encoding='utf8').write(txt)

for k, v in MODELS.items(): write(k, v)
