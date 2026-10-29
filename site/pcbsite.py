"""Site build helper for the routed-PCB features (called from build_site.py):
 - copies render/out/pcb_layers (tile pyramids, manifest.js, full-res PNGs) to site/pcb/
 - writes site/data/pcbtex.js: board outline + top/bottom texture (data URIs, so WebGL can use them from file://) for the 3D viewer."""
import os, json, shutil, base64, io
from PIL import Image
Image.MAX_IMAGE_PIXELS = None


def build(repo, site, notes):
    src = os.path.join(repo, 'render', 'out', 'pcb_layers'); dst = os.path.join(site, 'pcb')
    if not os.path.exists(os.path.join(src, 'manifest.js')):
        notes.append('render/out/pcb_layers missing (run render/make_pcb_textures.py): no PCB layout viewer'); return False
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src); os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            a, b = os.path.join(root, f), os.path.join(dst, rel, f)
            if not os.path.exists(b) or os.path.getsize(a) != os.path.getsize(b) or os.path.getmtime(a) > os.path.getmtime(b) + 1:
                shutil.copy2(a, b)
    m = open(os.path.join(src, 'manifest.js'), encoding='utf8').read()
    geom = json.loads(m[m.index('=') + 1:].rstrip().rstrip(';'))['geom']
    N = int(json.loads(m[m.index('=') + 1:].rstrip().rstrip(';'))['N'])
    def tex(name, flip):
        im = Image.open(os.path.join(src, 'pcb_%s_%d.png' % (name, N))).convert('RGBA')
        if flip: im = im.transpose(Image.FLIP_LEFT_RIGHT)           # the download is mirrored; the 3D face needs top-view coordinates
        bg = Image.new('RGB', im.size, (13, 74, 42)); bg.paste(im, mask=im.split()[3]); bg = bg.resize((4096, 4096), Image.LANCZOS)
        b = io.BytesIO(); bg.save(b, 'JPEG', quality=92, optimize=True); return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()
    # viewer coordinates: x = kx - 100, y = 100 - ky (board centred at the origin, same as pcbinfo refs)
    poly = [[round(p[0] - 100, 3), round(100 - p[1], 3)] for p in geom['poly']]
    holes = [[round(p[0] - 100, 3), round(100 - p[1], 3), round(p[8] / 2, 3)] for p in geom['pads'] if p[8] >= 1.5 and abs(p[8] - p[9]) < 1e-3]
    uniq = []
    for h in holes:
        if h not in uniq: uniq.append(h)
    js = 'window.PCBTEX=' + json.dumps({'poly': poly, 'holes': uniq, 'size': 48.0, 'top': tex('top', False), 'bottom': tex('bottom', True)}, separators=(',', ':')) + ';'
    os.makedirs(os.path.join(site, 'data'), exist_ok=True)
    open(os.path.join(site, 'data', 'pcbtex.js'), 'w', encoding='utf8').write(js)
    return True
