"""Routed-board pipeline: kicad-cli layer SVG exports -> (a) Blender PBR textures, (b) deep-zoom tile pyramids + full-res PNGs for the site.
Run: py -3.12 render/make_pcb_textures.py [N]   N = full resolution in px (default 8192 = 170 px/mm).
Works on a COPY of the board (render/work/board.kicad_pcb); never touches pcb/.
Outputs: render/work/tex_{top,bottom}_{color,rough,metal,bump}.png   (4096 px, used by render_hardware.py)
         render/work/geom.json                                         (tracks / vias / pads / outline per net, KiCad mm, y down)
         render/out/pcb_layers/  tiles/<set>/<z>/<x>_<y>.png, manifest.js, pcb_top_N.png, pcb_bottom_N.png, pcb_layers_top_N.png, pcb_layers_bottom_N.png"""
import os, sys, json, subprocess, shutil, numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__)); W = os.path.join(HERE, 'work'); ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'out', 'pcb_layers')
KC = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"; KPY = r"C:\Program Files\KiCad\10.0\bin\python.exe"
RSVG = shutil.which('rsvg-convert') or r"C:\msys64\mingw64\bin\rsvg-convert.exe"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8192
TEX = 4096; TILE = 512; BX0, BY0, BS = 76.0, 76.0, 48.0   # plot frame (mm): the svg plot area is the Edge.Cuts centre-line box
os.makedirs(W, exist_ok=True); os.makedirs(OUT, exist_ok=True)
pcb = os.path.join(W, 'board.kicad_pcb')
shutil.copyfile(os.path.join(ROOT, 'pcb', 'output', 'apriltag_cam.kicad_pcb'), pcb)
subprocess.run([KPY, os.path.join(HERE, 'extract_pcb_geom.py'), pcb, os.path.join(W, 'geom.json')], check=True)
geom = json.load(open(os.path.join(W, 'geom.json')))
S = N / BS

def layer(l):
    svg = os.path.join(W, l + '.svg'); png = os.path.join(W, l + '.png')
    subprocess.run([KC, 'pcb', 'export', 'svg', '--mode-single', '--black-and-white', '--page-size-mode', '2',
                    '--exclude-drawing-sheet', '--layers', l, '-o', svg, pcb], check=True, capture_output=True)
    subprocess.run([RSVG, '-w', str(N), '-h', str(N), svg, '-o', png], check=True)
    return np.array(Image.open(png).convert('RGBA'))[..., 3].astype(np.float32) / 255
def blur(m, r): return ndi.gaussian_filter(m, r)
L = {k: layer(v) for k, v in dict(fcu='F.Cu', in1='In1.Cu', in2='In2.Cu', bcu='B.Cu', fmask='F.Mask', bmask='B.Mask',
                                  fsilk='F.Silkscreen', bsilk='B.Silkscreen', edge='Edge.Cuts').items()}
print('layers exported')
lab, nl = ndi.label(L['edge'] < 0.5)
ext = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))); ext.discard(0)
inside = ~np.isin(lab, list(ext)); del lab
inside_f = blur(inside.astype(np.float32), 0.8)

def holes_mask():
    im = Image.new('L', (N, N), 0); d = ImageDraw.Draw(im)
    def circ(x, y, r): d.ellipse([(x - BX0 - r) * S, (y - BY0 - r) * S, (x - BX0 + r) * S, (y - BY0 + r) * S], fill=255)
    for x, y, dia, dr, n in geom['vias']: circ(x, y, dr / 2)
    for p in geom['pads']:
        if p[8] > 0:
            if abs(p[8] - p[9]) < 1e-3: circ(p[0], p[1], p[8] / 2)
            else: d.rounded_rectangle([(p[0] - BX0 - p[8] / 2) * S, (p[1] - BY0 - p[9] / 2) * S, (p[0] - BX0 + p[8] / 2) * S, (p[1] - BY0 + p[9] / 2) * S], radius=min(p[8], p[9]) / 2 * S, fill=255)
    return np.array(im).astype(np.float32) / 255
hole = blur(holes_mask(), 0.7)
c3 = lambda r, g, b: np.array([r, g, b], np.float32) / 255
def u8(a): return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)

def realistic(side):
    P = 'f' if side == 'top' else 'b'
    cu, open_f, silk = L[P + 'cu'], L[P + 'mask'], L[P + 'silk']
    cu_cov = cu * (1 - open_f)                                   # copper under the soldermask
    base = np.zeros((N, N, 3), np.float32) + c3(13, 74, 42)
    g = blur(cu_cov, 0.9 * N / 4096 + 0.4); gy, gx = np.gradient(g)
    shade = np.clip((-(gx + gy)) * 9.0 * (4096 / N), -1, 1) * 0.5   # raised mask edge, light from upper left
    cs = blur(cu_cov, 0.7)[..., None]
    base = base * (1 - cs) + c3(28, 112, 62) * cs
    base *= (1 + shade[..., None] * np.where(cs > 0.01, 0.45, 0.22))
    gold = blur(cu * open_f, 0.7)[..., None]
    base = base * (1 - gold) + c3(218, 176, 88) * gold
    bare = blur(open_f * (1 - cu), 0.7)[..., None]
    base = base * (1 - bare) + c3(168, 150, 98) * bare
    s = blur(silk, 0.6)[..., None]
    base = base * (1 - s) + c3(238, 238, 230) * s
    h = hole[..., None]
    base = base * (1 - h) + c3(22, 18, 14) * h
    gd, sd = gold[..., 0], s[..., 0]
    rough = np.full((N, N), 0.34, np.float32)
    rough = rough * (1 - gd) + 0.26 * gd; rough = rough * (1 - sd) + 0.72 * sd
    rough = np.where(cs[..., 0] > 0.02, rough * 0.85, rough)
    bump = blur(cu_cov, 1.2) * 0.5 + blur(cu * open_f, 1.0) * 0.12 + sd * 0.25
    return np.clip(base, 0, 1), rough, gd, bump

real = {}
for side in ('top', 'bottom'):
    col, rough, metal, bump = realistic(side)
    for kind, a, mode in (('color', col, 'RGB'), ('rough', rough, 'L'), ('metal', metal, 'L'), ('bump', bump, 'L')):
        Image.fromarray(u8(a), mode).resize((TEX, TEX), Image.LANCZOS).save(os.path.join(W, 'tex_%s_%s.png' % (side, kind)))
    real[side] = np.dstack([u8(col), u8(inside_f)]); print(side, 'texture done'); del col, rough, metal, bump

COL = dict(fcu=(255, 90, 77), in1=(242, 194, 48), in2=(71, 209, 122), bcu=(77, 141, 255), fmask=(18, 104, 58), bmask=(18, 104, 58), fsilk=(246, 246, 240), bsilk=(190, 215, 255))
OPA = dict(fcu=.92, in1=.92, in2=.92, bcu=.92, fmask=.5, bmask=.5, fsilk=.95, bsilk=.95)
alpha = {k: L[k] * OPA[k] for k in ('fcu', 'in1', 'in2', 'bcu', 'fsilk', 'bsilk')}
alpha['fmask'] = inside_f * (1 - L['fmask']) * OPA['fmask']; alpha['bmask'] = inside_f * (1 - L['bmask']) * OPA['bmask']
manifest = {'N': N, 'tile': TILE, 'sets': {}, 'bbox': [BX0, BY0, BS], 'colors': COL}
nlev = 1
while N // (2 ** (nlev - 1)) > TILE: nlev += 1
manifest['levels'] = nlev

def write_pyramid(name, rgba):
    tdir = os.path.join(OUT, 'tiles', name); shutil.rmtree(tdir, ignore_errors=True)
    im = Image.fromarray(rgba, 'RGBA'); have = []
    for lv in range(nlev - 1, -1, -1):
        sz = N // (2 ** (nlev - 1 - lv))
        if lv != nlev - 1: im = im.resize((sz, sz), Image.BOX)
        a = np.array(im); lst = []; os.makedirs(os.path.join(tdir, str(lv)), exist_ok=True)
        for ty in range((sz + TILE - 1) // TILE):
            for tx in range((sz + TILE - 1) // TILE):
                t = a[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE]
                if t[..., 3].max() == 0: continue
                Image.fromarray(t, 'RGBA').save(os.path.join(tdir, str(lv), '%d_%d.png' % (tx, ty)), compress_level=6); lst.append('%d_%d' % (tx, ty))
        have.append(lst)
    manifest['sets'][name] = have[::-1]; print('tiles', name, sum(len(x) for x in have))

for k in COL:
    rgba = np.zeros((N, N, 4), np.uint8); rgba[..., 0], rgba[..., 1], rgba[..., 2] = COL[k]; rgba[..., 3] = u8(alpha[k]); write_pyramid(k, rgba)
write_pyramid('rtop', real['top']); write_pyramid('rbot', np.ascontiguousarray(real['bottom']))   # bottom stays in top-view coordinates; the viewer mirrors it

segs = [tuple(s) for s in geom['outline']]; poly = [segs[0][:2], segs[0][2:]]; rest = segs[1:]
while rest:
    for i, s in enumerate(rest):
        if abs(s[0] - poly[-1][0]) + abs(s[1] - poly[-1][1]) < 0.02: poly.append(s[2:]); rest.pop(i); break
        if abs(s[2] - poly[-1][0]) + abs(s[3] - poly[-1][1]) < 0.02: poly.append(s[:2]); rest.pop(i); break
    else: break
geom['poly'] = [list(p) for p in poly]; del geom['outline']
manifest['geom'] = geom
open(os.path.join(OUT, 'manifest.js'), 'w').write('window.PCBVIEW=' + json.dumps(manifest, separators=(',', ':')) + ';')

# full-res downloads (the "board layout" renders): realistic top-down, realistic bottom-down (mirrored = as seen from below), 4-layer colour views
Image.fromarray(real['top'], 'RGBA').save(os.path.join(OUT, 'pcb_top_%d.png' % N), compress_level=6)
Image.fromarray(np.ascontiguousarray(real['bottom'][:, ::-1]), 'RGBA').save(os.path.join(OUT, 'pcb_bottom_%d.png' % N), compress_level=6)
def layered(order, mirror):
    img = np.zeros((N, N, 3), np.float32) + c3(14, 22, 20)
    for k in order:
        a = alpha[k][..., None]; img = img * (1 - a) + c3(*COL[k]) * a
    h = hole[..., None]; img = img * (1 - h) + c3(8, 8, 10) * h
    img = np.dstack([u8(img), u8(inside_f)])
    return np.ascontiguousarray(img[:, ::-1]) if mirror else img
Image.fromarray(layered(['bcu', 'in2', 'in1', 'fcu', 'fsilk'], False), 'RGBA').save(os.path.join(OUT, 'pcb_layers_top_%d.png' % N), compress_level=6)
Image.fromarray(layered(['fcu', 'in1', 'in2', 'bcu', 'bsilk'], True), 'RGBA').save(os.path.join(OUT, 'pcb_layers_bottom_%d.png' % N), compress_level=6)
print('done', N)
