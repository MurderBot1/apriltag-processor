#!/usr/bin/env py -3.12
"""Generate the browsable project site: site/index.html (+ assets/, data/, thumbs/, img/, vendor/).

    py -3.12 site/build_site.py

Works from file:// (no fetch/XHR): data goes into <script src="data/*.js"> files.  Read-only on the rest of the repo.
Needs: markdown-it-py, Pillow, numpy, opencv (the repo's py -3.12), optional FreeCAD for the PCB STEP -> mesh conversion.
"""
import os, sys, re, json, base64, shutil, subprocess, tempfile, html, csv, struct, math, time
import numpy as np
from markdown_it import MarkdownIt
from PIL import Image

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
FREECAD = r"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe"
sys.path.insert(0, os.path.join(ROOT, 'tests')); sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, ROOT)
P = lambda *a: os.path.join(ROOT, *a)
S = lambda *a: os.path.join(SITE, *a)
esc = html.escape


def rd(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def b64(arr):
    return base64.b64encode(arr.tobytes()).decode('ascii')


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


NOTES = []          # things that could not be included (shown on the About page)

import importlib.util as _ilu   # chip-simulation pages (site/sim/pages.py; data from site/simout/, made by site/sim/gen_sim.py + gen_pipeline.py)
_spec = _ilu.spec_from_file_location('sim_pages', os.path.join(SITE, 'sim', 'pages.py')); SIMPAGES = _ilu.module_from_spec(_spec); _spec.loader.exec_module(SIMPAGES)
sim_pages = SIMPAGES.sim_pages

# ---------------------------------------------------------------- markdown
md = MarkdownIt('commonmark', {'html': False}).enable('table')
DOC_PAGES = {   # source path -> (page id, title)
    'README.md': ('readme', 'Overview (README)'),
    'docs/architecture.md': ('architecture', 'Architecture'),
    'docs/hardware.md': ('hardware-doc', 'Hardware'),
    'docs/verification.md': ('verification-doc', 'Verification'),
    'docs/fpga.md': ('fpga', 'FPGA results'),
    'docs/protocol.md': ('protocol', 'Protocol'),
    'housing/README.md': ('housing-doc', 'Housing notes'),
    'results/reference_baseline.md': ('reference-baseline', 'Reference baseline'),
}
LINKMAP = {}
for src, (pid, _) in DOC_PAGES.items():
    LINKMAP[src] = pid
    LINKMAP[os.path.basename(src)] = pid


def render_md(text):
    out = md.render(text)
    def fix(m):
        href = html.unescape(m.group(1))
        if re.match(r'(https?:|#|mailto:)', href):
            return m.group(0)
        key = href.split('#')[0].lstrip('./')
        if key in LINKMAP:
            return 'href="#/%s"' % LINKMAP[key]
        return 'class="srcref" data-path="%s"' % esc(href)
    out = re.sub(r'href="([^"]*)"', fix, out)
    out = out.replace('<table>', '<div class="tablewrap"><table>').replace('</table>', '</table></div>')
    return out


def md_tables(text):
    """All pipe tables of a markdown text -> list of (header list, rows list)."""
    res, lines, i = [], text.split('\n'), 0
    while i < len(lines):
        if lines[i].startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s\-|:]+\|$', lines[i + 1]):
            cells = lambda l: [c.strip().strip('`').replace('**', '') for c in l.strip().strip('|').split('|')]
            hdr, rows = cells(lines[i]), []
            i += 2
            while i < len(lines) and lines[i].startswith('|'):
                rows.append(cells(lines[i])); i += 1
            res.append((hdr, rows))
        else:
            i += 1
    return res


def num(s):
    m = re.search(r'[-+]?\d[\d,]*\.?\d*', s or '')
    return float(m.group(0).replace(',', '')) if m else None


# ---------------------------------------------------------------- charts (inline SVG, CSS-var colours)
def svg_hbar(title, items, unit='', maxv=None, width=720, fmt='{:g}'):
    """items: [(label, value, cls)]  horizontal bar chart."""
    n = len(items); rowh = 26; lw = 250; h = n * rowh + 34
    mv = maxv or max(v for _, v, _ in items) * 1.08 or 1
    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, h, esc(title)),
         '<text x="0" y="14" class="ct">%s</text>' % esc(title)]
    for i, (lab, v, cls) in enumerate(items):
        y = 28 + i * rowh; w = (width - lw - 70) * v / mv
        o.append('<text x="%d" y="%d" class="cl" text-anchor="end">%s</text>' % (lw - 8, y + 14, esc(lab)))
        o.append('<rect x="%d" y="%d" width="%.1f" height="18" rx="3" class="bar %s"/>' % (lw, y, max(w, 1), cls))
        o.append('<text x="%.1f" y="%d" class="cv">%s%s</text>' % (lw + w + 6, y + 14, fmt.format(v), unit))
    o.append('</svg>')
    return ''.join(o)


def svg_group(title, cats, series, unit='', width=760, fmt='{:.1f}', height=250):
    """series: [(name, cls, [values per cat])] vertical grouped bars."""
    ml, mb, mt = 44, 46, 34; pw = width - ml - 10; ph = height - mb - mt
    mv = max((v for _, _, vs in series for v in vs if v is not None), default=1) * 1.12 or 1
    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, esc(title)),
         '<text x="0" y="14" class="ct">%s</text>' % esc(title)]
    for k in range(5):
        y = mt + ph - ph * k / 4
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/><text x="%d" y="%.1f" class="ca" text-anchor="end">%s</text>' % (ml, width - 10, y, y, ml - 4, y + 4, fmt.format(mv * k / 4)))
    gw = pw / len(cats); bw = min(24, gw / (len(series) + 1))
    for i, c in enumerate(cats):
        gx = ml + i * gw + gw / 2 - bw * len(series) / 2
        for j, (nm, cls, vs) in enumerate(series):
            v = vs[i]
            if v is None: continue
            bh = ph * v / mv
            o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" class="bar %s"><title>%s %s: %s%s</title></rect>' % (gx + j * bw, mt + ph - bh, bw - 1, max(bh, 0.5), cls, esc(c), esc(nm), fmt.format(v), unit))
        o.append('<text x="%.1f" y="%d" class="ca" text-anchor="middle">%s</text>' % (ml + i * gw + gw / 2, height - mb + 16, esc(c)))
    lx = width - 10
    for nm, cls, _ in reversed(series):
        lx -= 8 * len(nm) + 26
        o.append('<rect x="%d" y="4" width="11" height="11" rx="2" class="bar %s"/><text x="%d" y="14" class="cl">%s</text>' % (lx, cls, lx + 15, esc(nm)))
    o.append('</svg>')
    return ''.join(o)


# ---------------------------------------------------------------- 1. docs -> html
def build_docs():
    pages = {}
    for src, (pid, title) in DOC_PAGES.items():
        p = P(*src.split('/'))
        if not os.path.exists(p):
            NOTES.append('%s not found' % src); continue
        pages[pid] = (title, render_md(rd(p)), src)
    return pages


# ---------------------------------------------------------------- 2. 3D models
def parse_stl(path):
    t = rd(path)
    v = np.array(re.findall(r'vertex\s+(\S+)\s+(\S+)\s+(\S+)', t), dtype=np.float32)
    return v


def convert_step(glb):
    """Full-assembly GLB (kicad-cli, real 3D models on every footprint; render/out/apriltag_cam_full.glb) -> coloured meshes per reference
    designator (site/glb_convert.py: node names of the GLB are the refs, so nothing has to be matched by position)."""
    import glb_convert
    parts = glb_convert.convert(glb)
    board_parts = [p for p in parts if p['ref'] == 'board']
    bb = [min(p['bb'][0] for p in board_parts), min(p['bb'][1] for p in board_parts), min(p['bb'][2] for p in board_parts),
          max(p['bb'][3] for p in board_parts), max(p['bb'][4] for p in board_parts), max(p['bb'][5] for p in board_parts)]
    cx, cy = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2; ztop = bb[5]
    side_of = {}
    for r in set(p['ref'] for p in parts):
        if r == 'board': side_of[r] = 'board'; continue
        zs = [(p['bb'][2] + p['bb'][5]) / 2 for p in parts if p['ref'] == r]
        side_of[r] = 'top' if sum(zs) / len(zs) > ztop / 2 else 'bottom'
    groups = {'board': [], 'top': [], 'bottom': []}
    for p in parts: groups[side_of[p['ref']]].append(p)
    res = {'groups': {}, 'center': [cx, cy], 'board_z': [bb[2], bb[5]], 'n_solids': len(parts), 'n_raw': len(parts), 'parts': []}
    try:
        import pcbinfo
        res['info'] = pcbinfo.build_info((cx, -cy))
    except Exception as e:
        NOTES.append('PCB component metadata unavailable: %s' % e)
    for g, ps in groups.items():
        ps.sort(key=lambda p: (p['ref'], p['col']))
        pos, col, idx, base = [], [], [], 0
        for p in ps:
            v = np.array(p['v'], np.float32).reshape(-1, 3) - np.array([cx, cy, 0], np.float32)
            b_ = p['bb']; c = [int(round(x * 255)) for x in p['col']]
            res['parts'].append({'g': g, 'ref': None if p['ref'] == 'board' else p['ref'], 'name': p['ref'], 'v': base, 'vn': len(v), 'i': sum(len(a) for a in idx), 'in': len(p['f']),
                                 'c': c, 'bb': [round(b_[0] - cx, 2), round(b_[1] - cy, 2), round(b_[2], 2), round(b_[3] - cx, 2), round(b_[4] - cy, 2), round(b_[5], 2)]})
            pos.append(v); col.append(np.tile(np.array(c, np.uint8), (len(v), 1)))
            idx.append(np.array(p['f'], np.uint32) + base); base += len(v)
        if not pos: continue
        pos = np.concatenate(pos); col = np.concatenate(col); idx = np.concatenate(idx)
        res['groups'][g] = {'pos': b64(pos), 'col': b64(col), 'idx': b64(idx), 'n': len(ps), 'tris': len(idx) // 3}
    return res


def build_models():
    m = {'housing': {}, 'pcb': None}
    for n in ('front', 'back'):
        p = P('housing', 'output', n + '.stl')
        if os.path.exists(p):
            v = parse_stl(p); m['housing'][n] = {'pos': b64(v), 'tris': len(v) // 3}
        else:
            NOTES.append('housing/output/%s.stl missing' % n)
    # geometry constants from housing.scad contract: zpb = floor 2.4 + standoff (3.2+0.8); zpt = zpb + 1.6
    m['housing_z'] = {'split': 8.0, 'pcb_bottom': 6.4}
    step = P('render', 'out', 'apriltag_cam_full.glb')
    if os.path.exists(step):
        m['pcb'] = convert_step(step)
        if m['pcb']:
            m['pcb']['step_mtime'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(step)))
    else:
        NOTES.append('render/out/apriltag_cam_full.glb missing - no 3D PCB view (run render/run_all.sh)')
    write(S('data', 'models.js'), 'window.MODELS=' + json.dumps(m, separators=(',', ':')) + ';')
    return m


def copy_images():
    os.makedirs(S('img'), exist_ok=True)
    got = {}
    for key, src in [('board_top', 'pcb/output/board_top.png'), ('board_bottom', 'pcb/output/board_bottom.png'),
                     ('board_iso', 'pcb/output/board_iso.png'), ('contact', 'results/dataset_contact_sheet.png')]:
        p = P(*src.split('/'))
        if os.path.exists(p):
            dst = S('img', key + '.png')
            if key == 'contact':       # keep it small
                im = Image.open(p).convert('RGB'); im.thumbnail((1600, 1600)); dst = S('img', key + '.jpg'); im.save(dst, quality=80)
            else:
                shutil.copyfile(p, dst)
            got[key] = os.path.relpath(dst, SITE).replace('\\', '/')
        elif key != 'board_iso':
            NOTES.append('%s not found' % src)
    # Blender renders (render/render_hardware.py -> render/out): JPEG q86 for the page
    RO = P('render', 'out')
    for key, fn in [('r_hero', 'hero_assembled'), ('r_exploded', 'exploded'), ('r_pcb_top', 'pcb_top'),
                    ('r_pcb_bottom', 'pcb_bottom'), ('r_section', 'section_fov')]:
        p = os.path.join(RO, fn + '.png')
        if os.path.exists(p):
            dst = S('img', key + '.png'); shutil.copyfile(p, dst); got[key] = 'img/' + key + '.png'      # full-resolution PNG (3840x2160), lazy-loaded
            if key == 'r_hero':
                im = Image.open(p).convert('RGB'); im.thumbnail((2400, 1350)); im.save(S('img', 'r_hero_s.jpg'), quality=92, optimize=True, progressive=True); got['r_hero_s'] = 'img/r_hero_s.jpg'
        else:
            NOTES.append('render/out/%s.png not found (run render/run_all.sh)' % fn)
    for key, fn in [('r_turntable', 'turntable.mp4')]:
        p = os.path.join(RO, fn)
        if os.path.exists(p):
            shutil.copyfile(p, S('img', fn)); got[key] = 'img/' + fn
    return got


# ---------------------------------------------------------------- 3. gallery
def build_gallery():
    import analyze_chain as ac
    _load = ac.load      # the ground truth may list more frames than the RTL chain results cover yet: only show frames that have results
    ac.load = lambda: (lambda g, r, f: ({k: v for k, v in g.items() if k in r}, r, f))(*_load())
    rows, ref = ac.analyse()
    gtj = json.load(open(P('test_images', 'ground_truth.json')))
    rtl = json.load(open(P('results', 'rtl_chain_results.json')))
    cases = {c['name']: c for c in json.load(open(P('test_images', 'cases.json')))}
    os.makedirs(S('thumbs'), exist_ok=True); os.makedirs(S('frames'), exist_ok=True)
    imgs = []
    for name in sorted((n for n in gtj['images'] if n in rtl), key=lambda n: (gtj['images'][n]['category'], n)):
        g = gtj['images'][name]; r = rows[name]; rf = ref['per_image'].get(name, {})
        src = P('test_images', 'sensor', name + '.png')
        has = os.path.exists(src)
        if has:
            im = Image.open(src).convert('L')
            t = im.copy(); t.thumbnail((256, 160)); t.save(S('thumbs', name + '.jpg'), quality=72)
            f = im.resize((1024, 640), Image.LANCZOS); f.save(S('frames', name + '.jpg'), quality=78)
        det = {t['id']: t for t in rtl[name]['tags']}
        tags = {}
        for tid, v in g['tags'].items():
            tags[tid] = {'gt': [[round(a, 1), round(b, 1)] for a, b in v['corners']], 'vis': bool(v['visible']), 'px': round(v['px_width'], 1)}
        for tid, d in det.items():
            tags.setdefault(str(tid), {})['chip'] = [[round(a, 1), round(b, 1)] for a, b in d['corners']]
            tags[str(tid)]['ham'] = d.get('ham')
        for tid in tags:
            t = tags[tid]
            if 'gt' in t and 'chip' in t and t['vis']:
                t['err'] = round(float(np.linalg.norm(np.array(t['gt']) - np.array(t['chip']), axis=1).max()), 2)
        pe = r['pose']
        imgs.append({'name': name, 'cat': g['category'], 'img': has, 'vis': r['vis'], 'found': r['found'], 'false': r['false'],
                     'unseen': r['unseen_det'], 'pose': None if not pe else {'t_mm': round(float(pe[0]), 2), 'rot_deg': round(float(pe[1]), 3), 'rms_px': round(float(pe[2]), 3), 'n': int(pe[3])},
                     'ref': {'det': rf.get('n_detected'), 'false': rf.get('n_false'), 't_mm': None if rf.get('t_err_mm') is None else round(rf['t_err_mm'], 2),
                             'rot_deg': None if rf.get('rot_err_deg') is None else round(rf['rot_err_deg'], 4), 'rms_px': None if rf.get('rms_px') is None else round(rf['rms_px'], 3)} if rf else None,
                     'gt_t': [round(x, 4) for x in g['t_wc']], 'gt_R': [[round(x, 5) for x in row] for row in g['R_wc']],
                     'light': None if name not in cases else {'scale': round(cases[name]['light_scale'], 3), 'shift': round(cases[name]['light_shift'], 3)},
                     'stats': rtl[name]['stats'], 'sim_s': round(rtl[name].get('seconds', 0), 1), 'tags': tags})
    data = {'K': gtj['K'], 'dist': gtj['dist'], 'w': gtj['width'], 'h': gtj['height'], 'images': imgs}
    write(S('data', 'gallery.js'), 'window.GALLERY=' + json.dumps(data, separators=(',', ':')) + ';')
    return rows, ref, imgs


# ---------------------------------------------------------------- 4. verification page
def build_verification(imgs, rows, ref):
    vtxt = rd(P('docs', 'verification.md')); ftxt = rd(P('docs', 'fpga.md'))
    h = []
    # (a) test counts
    tabs = md_tables(vtxt)
    layers = []
    for hd, rs in tabs:
        if hd and hd[0] == 'layer':
            for r in rs:
                n = num(r[2])
                if n is not None: layers.append((r[0], int(n)))
    total = sum(n for _, n in layers)
    h.append('<div class="cards">')
    def card(v, l): return '<div class="card"><b>%s</b><span>%s</span></div>' % (esc(str(v)), esc(l))
    allv = sum(i['vis'] for i in imgs); allf = sum(i['found'] for i in imgs)
    refd = sum((i['ref'] or {}).get('det') or 0 for i in imgs)
    tms = np.array([i['pose']['t_mm'] for i in imgs if i['pose']]); rts = np.array([i['pose']['rot_deg'] for i in imgs if i['pose']])
    h.append(card(total, 'pytest tests (%d suites)' % len(layers)))
    h.append(card('%d / %d' % (allf, allv), 'tags found by chip (%.0f%%)' % (100 * allf / allv)))
    h.append(card('%d / %d' % (refd, allv), 'found by reference (%.0f%%)' % (100 * refd / allv)))
    h.append(card('%.1f mm' % np.median(tms), 'median camera position error (chip+solver)'))
    h.append(card('%.3f deg' % np.median(rts), 'median orientation error'))
    h.append(card('120.08 fps', 'sustained, 832,800 clocks/frame @ 100 MHz sim'))
    h.append('</div>')
    h.append('<h2>Tests per suite</h2>')
    if layers:
        h.append(svg_hbar('pytest tests per verification layer (total %d)' % total, [(l, n, 'c1') for l, n in layers], width=760))
    # (b) per category
    cats = []
    for i in imgs:
        if i['cat'] not in cats: cats.append(i['cat'])
    def agg(c):
        rs = [i for i in imgs if i['cat'] == c]
        v = sum(i['vis'] for i in rs); f = sum(i['found'] for i in rs); rd_ = sum((i['ref'] or {}).get('det') or 0 for i in rs)
        pt = [i['pose']['t_mm'] for i in rs if i['pose']]; rt = [i['ref']['t_mm'] for i in rs if i['ref'] and i['ref']['t_mm'] is not None]
        po = [i['pose']['rot_deg'] for i in rs if i['pose']]; ro = [i['ref']['rot_deg'] for i in rs if i['ref'] and i['ref']['rot_deg'] is not None]
        ce = [t['err'] for i in rs for t in i['tags'].values() if 'err' in t]
        return dict(n=len(rs), v=v, f=f, r=rd_, pt=np.median(pt) if pt else None, rt=np.median(rt) if rt else None, po=np.median(po) if po else None,
                    ro=np.median(ro) if ro else None, ce=np.mean(ce) if ce else None, fp=sum(i['false'] for i in rs))
    A = {c: agg(c) for c in cats}
    h.append('<h2>Detection and pose accuracy by image category</h2>')
    h.append(svg_group('Detection rate (% of ground-truth-visible tags)', cats, [
        ('chip', 'c1', [100 * A[c]['f'] / A[c]['v'] if A[c]['v'] else None for c in cats]),
        ('reference', 'c2', [100 * A[c]['r'] / A[c]['v'] if A[c]['v'] else None for c in cats])], unit='%', fmt='{:.0f}'))
    h.append(svg_group('Median camera position error (mm)', cats, [
        ('chip + MCU solver', 'c1', [A[c]['pt'] for c in cats]), ('reference', 'c2', [A[c]['rt'] for c in cats])], unit=' mm'))
    h.append(svg_group('Median camera orientation error (deg)', cats, [
        ('chip + MCU solver', 'c1', [A[c]['po'] for c in cats]), ('reference', 'c2', [A[c]['ro'] for c in cats])], unit=' deg', fmt='{:.3f}'))
    h.append('<div class="tablewrap"><table><thead><tr><th>category</th><th>images</th><th>visible tags</th><th>chip found</th><th>reference found</th><th>false IDs (chip)</th><th>mean corner err (px, chip)</th><th>pos err median chip / ref (mm)</th><th>rot err median chip / ref (deg)</th></tr></thead><tbody>')
    f = lambda x, p=1: '-' if x is None else ('%.' + str(p) + 'f') % x
    for c in cats:
        a = A[c]
        h.append('<tr><td>%s</td><td>%d</td><td>%d</td><td>%d (%s%%)</td><td>%d</td><td>%d</td><td>%s</td><td>%s / %s</td><td>%s / %s</td></tr>' % (
            c, a['n'], a['v'], a['f'], f(100 * a['f'] / a['v'], 0) if a['v'] else '-', a['r'], a['fp'], f(a['ce'], 2), f(a['pt']), f(a['rt']), f(a['po'], 3), f(a['ro'], 3)))
    h.append('</tbody></table></div><p class="muted">Computed at site build time from <code>results/rtl_chain_results.json</code> through the firmware pose solver (<code>tests/analyze_chain.py</code>) and <code>results/reference_baseline.json</code>. The per-image numbers are on the Test images page.</p>')
    # per-image error strip
    order = sorted([i for i in imgs if i['pose']], key=lambda i: i['pose']['t_mm'])
    w, hh = 760, 200; ml, mt, mb = 44, 30, 22; cap = 12.0
    o = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="per-image position error"><text x="0" y="14" class="ct">Per-image camera position error, sorted (mm, clipped at %g; labelled if larger)</text>' % (w, hh, cap)]
    ph = hh - mt - mb
    for k in range(5):
        y = mt + ph - ph * k / 4
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/><text x="%d" y="%.1f" class="ca" text-anchor="end">%g</text>' % (ml, w - 6, y, y, ml - 4, y + 4, cap * k / 4))
    bw = (w - ml - 6) / max(len(order), 1)
    for k, i in enumerate(order):
        v = i['pose']['t_mm']; bhh = ph * min(v, cap) / cap
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="bar c1"><title>%s  chip %.1f mm%s</title></rect>' % (ml + k * bw, mt + ph - bhh, max(bw - 0.8, 0.8), bhh, i['name'], v, '' if not i['ref'] or i['ref']['t_mm'] is None else ', ref %.1f mm' % i['ref']['t_mm']))
        rt = i['ref'] and i['ref']['t_mm']
        if rt is not None:
            o.append('<circle cx="%.1f" cy="%.1f" r="1.8" class="dot c2"/>' % (ml + k * bw + bw / 2, mt + ph - ph * min(rt, cap) / cap))
        if v > cap: o.append('<text x="%.1f" y="%d" class="ca" text-anchor="middle">%.0f</text>' % (ml + k * bw, mt - 2 + 8, v))
    o.append('<rect x="%d" y="4" width="11" height="11" class="bar c1"/><text x="%d" y="14" class="cl">chip (bar)</text><circle cx="%d" cy="9" r="4" class="dot c2"/><text x="%d" y="14" class="cl">reference (dot)</text></svg>' % (w - 250, w - 234, w - 120, w - 112))
    h.append(''.join(o))
    # (c) FPGA
    h.append('<h2>FPGA resources and timing (yosys + nextpnr-ecp5)</h2>')
    h.append('<p><b>Shipping part LFE5U-25F-8BG381I:</b> 13,389 LUT4 (55 %), 56 of 56 block RAM (100 %), core 92.27 - 94.91 MHz, D-PHY 206.06 - 226.71 MHz, 7 of 7 seeds close (nextpnr estimates, pinned OSS CAD Suite 2025-09-01; <code>results/fpga_speed_grades.md</code>). <b>The table and the seed chart below were measured on the LFE5U-45F</b> with older RTL (12,227 LUT4) and older tools.</p>')
    ft = md_tables(ftxt)
    for hd, rs in ft:
        if hd[0] == 'resource':
            h.append(svg_hbar('Resource utilisation (%)', [(r[0], num(r[3]) or 0, 'c3' if (num(r[3]) or 0) > 80 else 'c1') for r in rs], unit='%', maxv=100, fmt='{:.0f}'))
            h.append('<div class="tablewrap"><table><thead><tr>' + ''.join('<th>%s</th>' % esc(x) for x in hd) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>%s</td>' % esc(c) for c in r) + '</tr>' for r in rs) + '</tbody></table></div>')
        if hd[0] == 'seed':
            seeds = [('seed ' + r[0], num(r[1])) for r in rs]; sc = [('seed ' + r[0], num(r[2])) for r in rs]
            h.append(svg_group('Post-P&R fmax per seed (MHz). Core target 85.714 MHz (built), original target 100 MHz; D-PHY sclk target 200 MHz', [s for s, _ in seeds],
                               [('core clock', 'c1', [v for _, v in seeds]), ('D-PHY sclk', 'c2', [v for _, v in sc])], unit=' MHz', fmt='{:.0f}', height=270))
            h.append('<div class="tablewrap"><table><thead><tr>' + ''.join('<th>%s</th>' % esc(x) for x in hd) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>%s</td>' % esc(c) for c in r) + '</tr>' for r in rs) + '</tbody></table></div>')
    h.append('<p>Timing budget: frame = 1041 lines x 8 us = 8.328 ms (120.08 fps). CCL row time &lt;= 651 clocks (budget 686 at 85.714 MHz). Tag unit on the RP2350 (C, estimate): 1.6 ms median, 9.3 ms worst per frame at 150 MHz (<a href="#/verification-doc">Verification</a>). Source: <a href="#/fpga">FPGA results</a>, <a href="#/verification-doc">Verification</a>.</p>')
    # (d) headline table from verification.md
    for hd, rs in tabs:
        if hd and hd[0] == '' and 'this chip' in hd:
            h.append('<h2>Whole-pipeline accuracy: chip vs reference (from docs/verification.md)</h2><div class="tablewrap"><table><thead><tr>' + ''.join('<th>%s</th>' % esc(x or ' ') for x in hd) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>%s</td>' % esc(c) for c in r) + '</tr>' for r in rs) + '</tbody></table></div>')
    # suite table
    for hd, rs in tabs:
        if hd and hd[0] == 'layer':
            h.append('<h2>Test suites</h2><div class="tablewrap"><table><thead><tr>' + ''.join('<th>%s</th>' % esc(x) for x in hd) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>%s</td>' % esc(c) for c in r) + '</tr>' for r in rs) + '</tbody></table></div>')
    return '\n'.join(h)


# ---------------------------------------------------------------- 5. hardware pages
def table(hd, rows, cls=''):
    return '<div class="tablewrap"><table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        cls, ''.join('<th>%s</th>' % esc(x) for x in hd), ''.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in rows))


def build_hardware():
    out = {}
    # netlist
    nets = []
    npath = P('pcb', 'output', 'netlist.txt')
    for line in rd(npath).splitlines():
        if ':' in line:
            n, pins = line.split(':', 1); nets.append((n.strip(), pins.split()))
    npins = sum(len(p) for _, p in nets)
    rows = []
    for n, pins in nets:
        kind = 'power' if re.match(r'^[+]|GND|AVDD|DVDD|DOVDD|EVDD|VBUS', n) else 'signal'
        rows.append('<tr data-k="%s"><td><code>%s</code></td><td>%d</td><td class="pins">%s</td></tr>' % (kind, esc(n), len(pins), esc(' '.join(pins))))
    nl = ['<div class="cards"><div class="card"><b>%d</b><span>nets</span></div><div class="card"><b>%d</b><span>net-pin connections</span></div></div>' % (len(nets), npins),
          '<p><input class="filter" data-target="nettable" type="search" placeholder="filter nets / pins (e.g. U1.F2, MIPI, +3V3)"> '
          '<label class="chk"><input type="checkbox" class="pwr" data-target="nettable" checked> show power nets</label></p>',
          '<div class="tablewrap"><table id="nettable"><thead><tr><th>net</th><th>pins</th><th>pin list (ref.pin)</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>']
    # pin plan from tools/pins.py
    pp = []
    try:
        import pins as pinmod
        for name, (ball, std, extra) in pinmod.PINS.items():
            pp.append((name, ball, pinmod.DIFF_N.get(name, ''), std, extra))
    except Exception as e:
        NOTES.append('tools/pins.py not importable: %s' % e)
    pin_html = table(['signal (RTL port)', 'ball', 'N ball (diff pair)', 'I/O standard', 'attributes'], [['<code>%s</code>' % esc(a), esc(b), esc(c), esc(d), esc(e)] for a, b, c, d, e in pp]) if pp else ''
    # placement + bom
    place = list(csv.DictReader(open(P('pcb', 'output', 'placement.csv'), encoding='utf-8')))
    bom = list(csv.DictReader(open(P('pcb', 'output', 'bom.csv'), encoding='utf-8')))
    nparts = len(place); top = sum(1 for r in place if r['Side'] == 'top')
    bom_html = table(['qty', 'value', 'footprint', 'references'], [[r['Qty'], esc(r['Value']), esc(r['Footprint']), '<span class="pins">%s</span>' % esc(r['References'])] for r in bom])
    place_html = ('<p><input class="filter" data-target="plctable" type="search" placeholder="filter placement (ref, value, side)"></p>' +
                  '<div class="tablewrap"><table id="plctable"><thead><tr><th>ref</th><th>value</th><th>footprint</th><th>x mm</th><th>y mm</th><th>rot</th><th>side</th><th>note</th></tr></thead><tbody>' +
                  ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % tuple(esc(r[k]) for k in ('Ref', 'Value', 'Footprint', 'X_mm', 'Y_mm', 'Rot', 'Side', 'Note')) for r in place) + '</tbody></table></div>')
    params = json.load(open(P('pcb', 'pcb_params.json')))
    b = params['board']
    # DRC
    drc_html = []
    drcs = []
    for fn in ('drc_summary.json', 'drc_place.json', 'drc_try.json'):
        p = P('pcb', 'output', fn)
        if os.path.exists(p): drcs.append((fn, p))
    if not drcs: drc_html.append('<p class="muted">No DRC json found in pcb/output.</p>')
    from collections import Counter
    for fn, p in drcs:
        try:
            d = json.load(open(p))
        except Exception as e:
            drc_html.append('<p>%s unreadable (%s)</p>' % (fn, e)); continue
        if 'violations' not in d:
            drc_html.append('<h3>%s</h3><pre>%s</pre>' % (fn, esc(json.dumps(d, indent=1)[:2000]))); continue
        c = Counter((v.get('type'), v.get('severity')) if isinstance(v, dict) else (str(v)[:60], 'error') for v in d['violations'])
        u = d.get('unconnected_items', []); u = u if isinstance(u, int) else len(u)
        drc_html.append('<h3><code>%s</code></h3><p class="muted">source: %s &middot; KiCad %s &middot; %s &middot; <b>%d</b> violations, <b>%d</b> unconnected items</p>' % (fn, esc(str(d.get('source'))), esc(str(d.get('kicad_version'))), esc(str(d.get('date'))), len(d['violations']), u))
        drc_html.append(svg_hbar('violations by type (%s)' % fn, [('%s [%s]' % (t, s), n, 'c3' if s == 'error' else 'c4') for (t, s), n in sorted(c.items(), key=lambda kv: -kv[1])] or [('none', 0, 'c1')], width=720))
    drc_html.append('<p class="muted">DRC files are snapshots of in-progress routing attempts (<code>drc_place.json</code> = placement only, <code>drc_try.json</code> = a Freerouting trial); there is no <code>drc_summary.json</code> in <code>pcb/output</code>. The board is not claimed DRC-clean here.</p>')
    # board stats
    cnt = Counter(re.match(r'[A-Za-z]+', r['Ref']).group(0) for r in place)
    stats = [('Size', '%g x %g mm, %d layers, %g mm, corner radius %g' % (b['width'], b['height'], b['layers'], b['thickness'], b['corner_radius'])),
             ('Components placed', '%d (%d top, %d bottom), %d distinct BOM lines' % (nparts, top, nparts - top, len(bom))),
             ('By prefix', ', '.join('%s x%d' % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]))),
             ('Nets / connections', '%d nets, %d pins' % (len(nets), npins)),
             ('Mounting holes', '%d x d%g mm (pad %g) at +-%g mm' % (len(params['mounting_holes']['positions']), params['mounting_holes']['diameter'], params['mounting_holes']['pad_diameter'], abs(params['mounting_holes']['positions'][0][0]))),
             ('Sensor centre', str(params['sensor']['center']) + ' mm'),
             ('Files in pcb/output', ', '.join(sorted(f for f in os.listdir(P('pcb', 'output')) if not f.startswith('sol_'))[:30]) + ' ... (and Freerouting sol_* trial files)')]
    return nl, pin_html, bom_html, place_html, drc_html, stats, params


def build_config():
    tm = json.load(open(P('config', 'tag_map.json')))
    cal = json.load(open(P('config', 'camera_calibration.json')))
    rows = [[t['id'], t.get('size'), ', '.join('%g' % x for x in t['position']), ', '.join('%.4f' % x for x in t['quat_wxyz'])] for t in tm['tags']]
    h = ['<h2>Field map (config/tag_map.json)</h2><p>family <code>%s</code>, %d tags</p>' % (esc(tm.get('family', '')), len(rows)),
         table(['id', 'size (m)', 'position (m, world)', 'quaternion wxyz'], [[esc(str(c)) for c in r] for r in rows]),
         '<h2>Camera calibration (config/camera_calibration.json)</h2><pre>%s</pre>' % esc(json.dumps(cal, indent=1))]
    return '\n'.join(h)


# ---------------------------------------------------------------- 6. RTL
KW = set('module endmodule input output inout wire reg integer parameter localparam assign always initial begin end if else case casez casex endcase default for while generate endgenerate genvar function endfunction task endtask posedge negedge or and not signed'.split())


def hl(src):
    out = []
    tok = re.compile(r'(//[^\n]*)|(/\*.*?\*/)|("(?:[^"\\]|\\.)*")|(`\w+)|(\b\d+\'[sS]?[bBhHdDoO][0-9a-fA-F_xXzZ]+|\b\d[\d_]*\b)|(\b[A-Za-z_]\w*\b)', re.S)
    pos = 0
    for m in tok.finditer(src):
        out.append(esc(src[pos:m.start()])); pos = m.end(); t = m.group(0)
        if m.group(1) or m.group(2): out.append('<span class="c">%s</span>' % esc(t))
        elif m.group(3): out.append('<span class="s">%s</span>' % esc(t))
        elif m.group(4): out.append('<span class="d">%s</span>' % esc(t))
        elif m.group(5): out.append('<span class="n">%s</span>' % esc(t))
        elif t in KW: out.append('<span class="k">%s</span>' % esc(t))
        else: out.append(esc(t))
    out.append(esc(src[pos:]))
    return ''.join(out)


def build_rtl():
    mods = []
    d = P('rtl')
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(('.v', '.lpf')): continue
        src = rd(os.path.join(d, fn)); lines = src.count('\n') + (0 if src.endswith('\n') else 1)
        head = []
        for l in src.splitlines():
            s = l.strip()
            if s.startswith(('//', '#')): head.append(re.sub(r'^(//|#)\s?', '', s))
            elif s == '' and not head: continue
            else: break
        desc = ' '.join(x.strip() for x in head).strip() or 'No header comment.'
        names = re.findall(r'^\s*module\s+(\w+)', src, re.M)
        insts = sorted(set(re.findall(r'^\s*(\w+)\s+(?:#\s*\([^;]*?\)\s*)?\w+\s*\(', src, re.M | re.S)) - KW - set(names))
        mods.append({'file': fn, 'lines': lines, 'bytes': len(src.encode()), 'modules': names, 'desc': desc, 'html': hl(src), 'kind': 'constraints' if fn.endswith('.lpf') else 'verilog'})
    # which modules instantiate which
    allm = {n for m in mods for n in m['modules']}
    for m in mods:
        txt = rd(os.path.join(d, m['file']))
        m['uses'] = sorted({n for n in allm if re.search(r'^\s*%s\s*(#|\w+\s*\()' % n, txt, re.M)} - set(m['modules']))
    hexes = [(f, os.path.getsize(os.path.join(d, f))) for f in sorted(os.listdir(d)) if f.endswith('.hex')]
    write(S('data', 'rtl.js'), 'window.RTL=' + json.dumps({'mods': mods, 'hex': hexes}, separators=(',', ':')) + ';')
    return mods, hexes


# ---------------------------------------------------------------- bom (native page, data from docs/bom/bom.json)
def build_bom():
    data = json.load(open(P('docs', 'bom', 'bom.json'), encoding='utf-8'))
    for i, it in enumerate(data['items']):
        if it.get('status') == 'verified' and (it.get('unit_price') is None or not it.get('link')):
            raise SystemExit('bom item %d (%s) marked verified without price/link' % (i, it.get('value')))
    write(S('data', 'bom.js'), 'window.BOM=' + json.dumps(data, separators=(',', ':')).replace('</', '<\\/') + ';')
    return data


def copy_part_thumbs():
    """render/out/parts/*.webp + render/out/partthumbs.js (render/render_part_thumbs.py) -> site/img/parts, site/data/partthumbs.js"""
    src = P('render', 'out', 'parts')
    os.makedirs(S('img', 'parts'), exist_ok=True)
    n = 0
    if os.path.isdir(src):
        for f in os.listdir(src):
            shutil.copyfile(os.path.join(src, f), S('img', 'parts', f)); n += 1
    js = P('render', 'out', 'partthumbs.js')
    write(S('data', 'partthumbs.js'), open(js, encoding='utf-8').read() if os.path.exists(js) else 'window.PARTTHUMBS=null;')
    if not n: NOTES.append('no part thumbnails (run render/render_part_thumbs.py)')


def bom_page_html():
    return """<h1>BOM &amp; pricing</h1>
<p class="muted" id="bom-sub"></p>
<div class="bomcards">
 <div class="bc bc-main"><b id="bom-tV">-</b><span>Verified total (<span class="bn"></span> board(s))</span></div>
 <div class="bc"><b id="bom-tVb">-</b><span>Verified, per board (recurring)</span></div>
 <div class="bc"><b id="bom-tF">-</b><span>Verified one-time (fab setup etc.)</span></div>
 <div class="bc"><b id="bom-tU">-</b><span>Unverified lines (not in total)</span></div>
 <div class="bc"><b id="bom-tH">-</b><span>Hard-to-source lines</span></div>
</div>
<div class="bomctl2" role="search">
 <div class="bc-row">
  <input id="bom-q" type="search" placeholder="Search parts: name, MPN, maker, designator..." aria-label="Search the BOM">
  <select id="bom-cat" aria-label="Category"><option value="">All categories</option></select>
  <select id="bom-st" aria-label="Status"><option value="">All status</option><option value="verified">Verified</option><option value="unverified">Unverified</option><option value="quote">Quote only</option><option value="hard">Hard to source</option></select>
  <label class="bc-sort">Sort <select id="bom-sort" aria-label="Sort by"><option value="cat">BOM order</option><option value="name">Name</option><option value="qty">Quantity</option><option value="unit">Unit price</option><option value="ext">Extended price</option><option value="status">Status</option><option value="mfr">Manufacturer</option></select></label>
  <button type="button" id="bom-dir" class="sm" title="Reverse sort order">&#9652; Asc</button>
 </div>
 <div class="bc-row">
  <label class="bc-boards">Boards <input id="bom-mult" type="number" min="1" value="1" aria-label="Number of boards"></label>
  <span class="seg"><button type="button" data-m="1">1</button><button type="button" data-m="10">10</button><button type="button" data-m="100">100</button></span>
  <span class="grow"></span>
  <button type="button" id="bom-grp" class="tgl" aria-pressed="true">Group by category</button>
  <button type="button" id="bom-det" class="tgl" aria-pressed="false" title="Show designators, descriptions and notes">Show details</button>
  <span class="seg" role="group" aria-label="View"><button type="button" data-view="cards">Cards</button><button type="button" data-view="table">Table</button></span>
  <button type="button" id="bom-csv" class="sm" title="Download the filtered list as CSV">CSV</button>
 </div>
 <div class="bc-count muted" id="bom-count" aria-live="polite"></div>
</div>
<div id="bom-cards" class="pcards"></div>
<div id="bom-twrap" class="tablewrap bomtw" hidden><table id="bom-table"><thead><tr id="bom-hd"></tr></thead><tbody id="bom-tb"></tbody><tfoot id="bom-tf"></tfoot></table></div>
<p class="muted" id="bom-ft"></p>
<p class="muted">Source data: <code>docs/bom/bom.json</code>, embedded at build time. Part images are renders of the real 3D models (made offline, see <code>render/render_part_thumbs.py</code>). The Buy links are plain hyperlinks to vendor pages; nothing is fetched unless you click one.</p>"""


# ---------------------------------------------------------------- main
def main():
    for sub in ('data', 'thumbs', 'frames', 'img'):
        shutil.rmtree(S(sub), ignore_errors=True)
    print('docs ...'); pages = build_docs()
    print('models (GLB -> meshes) ...'); models = build_models()
    imgs_ = copy_images()
    import pcbsite
    print('PCB layout tiles + 3D texture ...'); HAVE_PCBVIEW = pcbsite.build(ROOT, SITE, NOTES)
    print('gallery ...'); rows, ref, imgs = build_gallery()
    ver_html = build_verification(imgs, rows, ref)
    nl, pin_html, bom_html, place_html, drc_html, stats, params = build_hardware()
    cfg_html = build_config()
    mods, hexes = build_rtl()
    shutil.rmtree(S('bom'), ignore_errors=True)   # stale copy of the old separate BOM page
    bom_data = build_bom()
    copy_part_thumbs()
    for f in ('three.min.js', 'OrbitControls.js'):
        if not os.path.exists(S('vendor', f)): NOTES.append('vendor/%s missing - 3D viewers will not work' % f)

    # assemble pages: id -> (group, title, html)
    P_ = []   # (id, group, title, html)
    # overview first
    P_.append(('home', 'Start', 'Home', home_html(imgs_, imgs, models, mods)))
    for pid in ('readme', 'architecture', 'hardware-doc', 'verification-doc', 'fpga', 'protocol', 'housing-doc', 'reference-baseline'):
        if pid in pages:
            t, h, src = pages[pid]
            P_.append((pid, 'Docs', t, '<h1>%s</h1><p class="muted">rendered from <code>%s</code></p>%s' % (esc(t), esc(src), h)))
    P_.append(('models', '3D & renders', '3D models', models_html(imgs_, models)))
    P_.append(('gallery', 'Results', 'Test images', gallery_html(imgs)))
    P_.append(('results', 'Results', 'Verification results', '<h1>Verification results</h1>' + ver_html))
    P_.append(('netlist', 'Hardware', 'Netlist', '<h1>Netlist</h1><p class="muted">from <code>pcb/output/netlist.txt</code> (netlist-first design, no schematic)</p>' + ''.join(nl)))
    P_.append(('pins', 'Hardware', 'FPGA pin plan', '<h1>FPGA pin plan</h1><p class="muted">from <code>tools/pins.py</code> (single source for the LPF and the PCB netlist). The ECP5 BG381 pin data used for the choice (85F database; the 45F has the same pads, checked by <code>tools/pin_compat.py</code>) is in <code>pcb/ecp5_85f_bg381_io.json</code>.</p>' + pin_html + '<p>The table in <a href="#/hardware-doc">Hardware</a> explains bank / standard choices.</p>'))
    P_.append(('board', 'Hardware', 'Board & DRC', '<h1>Board stats &amp; DRC</h1>' + table(['item', 'value'], [[esc(a), esc(b)] for a, b in stats]) + '<h2>DRC summary</h2>' + ''.join(drc_html) +
              '<h2>Placement</h2>' + place_html + '<h2>Bill of materials (pcb/output/bom.csv, grouped)</h2>' + bom_html))
    P_.append(('bom', 'Hardware', 'BOM & pricing', bom_page_html()))
    P_.append(('rtl', 'RTL', 'RTL browser', rtl_html(mods, hexes)))
    P_.extend(sim_pages(mods))      # 'Chip simulation' group: block diagram, waveform viewer, frame pipeline (site/sim/pages.py)
    P_.append(('config', 'Config', 'Field map & calibration', '<h1>Field map &amp; calibration</h1>' + cfg_html))
    P_.append(('about', 'Start', 'About this site', about_html()))

    nav, body, index = [], [], {}
    groups = []
    for pid, g, t, h in P_:
        if g not in groups: groups.append(g)
    for g in groups:
        nav.append('<div class="navgroup">%s</div>' % esc(g))
        for pid, gg, t, h in P_:
            if gg != g: continue
            plain = re.sub(r'<[^>]+>', ' ', h); plain = re.sub(r'\s+', ' ', html.unescape(plain)).lower()
            if pid == 'bom': plain += ' ' + ' '.join(' '.join(str(v) for v in it.values()) for it in bom_data['items']).lower()
            plain = re.sub(r'https?://\S+', ' ', plain)
            index[pid] = plain[:60000]
            nav.append('<a class="navlink" href="#/%s" data-id="%s">%s</a>' % (pid, pid, esc(t)))
            body.append('<section class="page" id="page-%s" hidden>%s</section>' % (pid, h))
    write(S('data', 'search.js'), 'window.SEARCH=' + json.dumps(index, separators=(',', ':')) + ';')
    tpl = rd(S('template.html'))
    out = tpl.replace('{{NAV}}', '\n'.join(nav)).replace('{{PAGES}}', '\n'.join(body)).replace('{{BUILT}}', time.strftime('%Y-%m-%d %H:%M'))
    out = out.replace('{{SIMHEAD}}', SIMPAGES.SIM_CSS_LINK).replace('{{SIMSCRIPTS}}', SIMPAGES.sim_scripts())
    write(S('index.html'), out)
    # report
    refs = re.findall(r'(?:src|href)="([^"#:]+?)"', out)
    miss = [r for r in set(refs) if not os.path.exists(S(*r.split('/')))]
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(SITE) for f in fs)
    print('site size %.1f MB; missing refs: %s; notes: %s' % (total / 1e6, miss, NOTES))


def home_html(imgs_, imgs, models, mods):
    return '''<h1>AprilTag camera: project browser</h1>
<p class="lead">Custom vision chip (ECP5 FPGA with custom RTL for the per-pixel work, RP2350 MCU for the tag unit and pose solve) + OV9281 120 fps global-shutter sensor, one USB-C cable.
Everything below is generated from the repository by <code>site/build_site.py</code> and works offline (file://).</p>
<div class="cards">
<a class="card link" href="#/models"><b>3D</b><span>housing assembly with explode slider, PCB from STEP</span></a>
<a class="card link" href="#/gallery"><b>%d</b><span>test frames with ground truth, chip and reference detections</span></a>
<a class="card link" href="#/results"><b>Results</b><span>test counts, accuracy, timing and resource charts</span></a>
<a class="card link" href="#/rtl"><b>%d</b><span>RTL files / %d lines of Verilog, with source viewer</span></a>
<a class="card link" href="#/netlist"><b>Hardware</b><span>netlist, pin plan, board, DRC, BOM</span></a>
<a class="card link" href="#/readme"><b>Docs</b><span>README, architecture, protocol, FPGA, verification</span></a>
</div>
<pre class="diagram">OV9281 (MIPI, 120 fps) -> ECP5 LFE5U-25F: D-PHY/CSI-2 RX, threshold, despeckle, CCL, mask stream
                        -> 8-bit frame bus -> RP2350 MCU: 3 frame buffers, tag unit (C), pose solve, USB, field map -> host</pre>
<img class="hero" src="%s" alt="housing assembly render">''' % (len(imgs), len(mods), sum(m['lines'] for m in mods if m['kind'] == 'verilog'), imgs_.get('r_hero_s', imgs_.get('r_hero', '')))


def models_html(imgs_, m):
    pcbnote = ''
    if not m['pcb']:
        pcbnote = '<p class="warn">The 3D PCB view could not be generated (FreeCAD conversion unavailable or failed); only the rendered images are shown.</p>'
    else:
        g = m['pcb']['groups']
        pcbnote = ('<p class="muted">Full-assembly model <code>render/out/apriltag_cam_full.step</code> / <code>.glb</code> (exported %s with kicad-cli; every footprint carries a real 3D model: KiCad 10 official library for passives, SOT, WSON, header, switch, crystal; dimensionally accurate parametric models from <code>render/models/gen_models.py</code> for the ECP5 caBGA-381, RP2350 QFN-60, USB-C, oscillator, OV9281 CSP, M12 lens holder + lens and test pads): %d model colour groups (%d), %d triangles. '
                   'Colours are the colours stored in the models. The copper traces on the 3D board are a texture from the routed .kicad_pcb (toggle &quot;traces&quot;) and are in the PCB layout tab and the renders.</p>'
                   % (m['pcb']['step_mtime'], len(m['pcb']['parts']), len(set(x['ref'] for x in m['pcb']['parts'])), sum(x['tris'] for x in g.values())))
    pic = lambda k, c: ('<figure><img src="%s" alt="%s" loading="lazy"><figcaption>%s</figcaption></figure>' % (imgs_[k], c, c)) if k in imgs_ else ''
    big = lambda k, c: ('<figure class="rbig"><a href="%s" target="_blank"><img src="%s" alt="%s" loading="lazy"></a><figcaption>%s</figcaption></figure>' % (imgs_[k], imgs_[k], c.split('.')[0], c)) if k in imgs_ else ''
    renders = ''.join([
        big('r_hero', 'Assembled unit. Matte black PLA housing (front.stl + back.stl), M12 lens with a glossier black anodised barrel and glass, USB-C opening on the left wall. 3840x2160 (click for the full PNG).'),
        big('r_exploded', 'Exploded view: front cover, PCB with lens holder, back shell. Dotted guides pass through the four M2 screw positions.'),
        big('r_pcb_top', 'PCB top (lens side), routed board: soldermask-covered copper traces and vias, ENIG pads and silkscreen come from the KiCad layout (textured from the kicad-cli layer export); the sensor sits under the M12 holder. 3840x2160.'),
        big('r_pcb_bottom', 'PCB bottom. ECP5 BGA, RP2350, USB-C, regulators and passives; all routed copper of apriltag_cam.kicad_pcb is in the texture. 3840x2160. For the 4-layer board layout at 8192 px with zoom see the PCB layout tab.'),
        big('r_section', 'Section through the lens axis with the 82.2 degree horizontal field-of-view cone of the CIL023 lens (apex at the hood entrance pupil, 41.1 degree half angle; angle read from pcb/pcb_params.json). The 45 degree hood cone does not vignette the field.')])
    if 'r_turntable' in imgs_:
        renders += ('<figure class="rbig"><video src="%s" poster="%s" controls loop muted autoplay playsinline preload="metadata"></video>'
                    '<figcaption>Turntable of the assembled unit (3 s loop).</figcaption></figure>' % (imgs_['r_turntable'], imgs_.get('r_hero', '')))
    renders += '<p class="muted">Rendered headless with Blender 5.1 Cycles by <code>render/render_hardware.py</code> (re-create with <code>render/run_all.sh</code>). Housing from the STLs; PCB and components from the kicad-cli full-assembly GLB (<code>render/out/apriltag_cam_full.glb</code>, real 3D models on every footprint); PCB textures from kicad-cli layer exports. The interactive 3D viewers are in the other tabs.</p>'
    lay_btn = lay_pane = ''
    if os.path.exists(S('pcb', 'manifest.js')):
        lay_btn = '<button data-t="l">PCB layout</button>'
        lay_pane = ('<div class="tabpane" data-pane="m-l" hidden>'
                    '<div id="pcbview"><div class="vmsg">loading PCB layout...</div></div>'
                    '<p class="muted">Routed board <code>pcb/output/apriltag_cam.kicad_pcb</code> (copy exported with kicad-cli, rasterised with rsvg-convert at 8192 px = 170 px/mm; zoom in to see individual traces). '
                    'Layers mode shows F.Cu / In1 / In2 / B.Cu in separate colours with soldermask, silkscreen and drills as toggles; Photo-like mode is the soldermask / ENIG texture used by the Blender renders. '
                    'Click any trace, via or pad (or search a net / ref.pin) to highlight the whole net; it is drawn from the routed geometry (all tracks, vias and pads of the file). '
                    'The full-resolution PNGs are linked in the side panel.</p></div>')
    return '''<h1>3D models and renders</h1>
<div class="tabs" data-tabs="m"><button class="on" data-t="h">Housing</button><button data-t="p">PCB assembly</button><button data-t="r">Renders</button>%s</div>
<div class="tabpane" data-pane="m-h">
 <div class="v3host" id="v-housing"><div class="vmsg">loading 3D...</div></div>
 <p class="muted">Housing STLs: <code>housing/output/front.stl</code>, <code>back.stl</code> (OpenSCAD). Assembly positions follow <code>housing.scad</code>: the front cover sits on the split plane z = 8.0 mm, the PCB bottom at z = 6.4 mm. Every part is a real 3D model (official KiCad library or the dimensioned parametric models in <code>render/models</code>), including the M12 lens module, ECP5 BGA, RP2350, USB-C, oscillator and sensor. Click any component for its reference designator, value, footprint, position and pin nets; the search box finds a ref, value, footprint or net.</p>
</div>
<div class="tabpane" data-pane="m-p" hidden>
 <div class="v3host" id="v-pcb"><div class="vmsg">loading 3D...</div></div>
 %s
 <div class="gridimgs">%s%s%s</div>
</div>
<div class="tabpane" data-pane="m-r" hidden>
 <div class="renders">%s</div>
</div>%s''' % (lay_btn, pcbnote, pic('board_top', 'PCB top (board_top.png)'), pic('board_bottom', 'PCB bottom (board_bottom.png)'), pic('board_iso', 'PCB iso (board_iso.png)'),
              renders, lay_pane)


def gallery_html(imgs):
    cats = []
    for i in imgs:
        if i['cat'] not in cats: cats.append(i['cat'])
    cs = rd(S('assets', 'dummy')) if False else ''
    return '''<h1>Test images</h1>
<p class="muted">%d rendered 1280x800 frames (Blender Cycles, lens distortion + OV9281 sensor model) from <code>test_images/sensor</code>, shown as 1024x640 JPEG (thumbnails 256 px). Ground truth: <code>test_images/ground_truth.json</code>. Chip = simulated RTL chain (<code>results/rtl_chain_results.json</code>) run through the firmware pose solver; reference = pupil-apriltags + solvePnP (<code>results/reference_baseline.json</code>).</p>
<div class="gfilters"><input id="g-search" type="search" placeholder="filter by name"> <select id="g-cat"><option value="">all categories</option>%s</select>
<select id="g-sort"><option value="cat">sort: category</option><option value="name">name</option><option value="err">chip position error (desc)</option><option value="miss">missed tags (desc)</option></select>
<span id="g-count" class="muted"></span></div>
<div id="g-grid" class="ggrid"></div>
<h2>Contact sheet</h2><img class="hero" src="img/contact.jpg" alt="dataset contact sheet" loading="lazy">
<div id="g-modal" class="modal" hidden><div class="mbox">
 <div class="mhead"><b id="m-title"></b><span class="grow"></span><button id="m-prev">&larr;</button><button id="m-next">&rarr;</button><button id="m-close">close</button></div>
 <div class="mbody"><div class="mimg"><div class="imgwrap"><img id="m-img" alt=""><canvas id="m-cv"></canvas></div>
  <div class="vctl"><label class="chk"><input type="checkbox" id="m-gt" checked> ground truth (green)</label><label class="chk"><input type="checkbox" id="m-chip" checked> chip detections (blue)</label><label class="chk"><input type="checkbox" id="m-invis"> GT not visible (grey)</label><label class="chk"><input type="checkbox" id="m-ids" checked> ids</label><a id="m-full" target="_blank">open full frame image</a></div></div>
  <div class="minfo" id="m-info"></div></div></div></div>''' % (len(imgs), ''.join('<option>%s</option>' % c for c in cats))


def rtl_html(mods, hexes):
    rows = ''.join('<tr class="rtlrow" data-i="%d" tabindex="0"><td><a href="#/rtl/%s">%s</a></td><td>%d</td><td>%s</td><td class="desc">%s</td></tr>' % (
        i, esc(m['file']), esc(m['file']), m['lines'], esc(', '.join(m['modules'])), esc(m['desc'][:420] + ('...' if len(m['desc']) > 420 else ''))) for i, m in enumerate(mods))
    return '''<h1>RTL browser</h1><p class="muted"><code>rtl/*.v</code> and <code>apriltag_cam.lpf</code>. Descriptions are the leading comment block of each file. %d Verilog lines in total. Data files (not shown): %s.</p>
<div class="tablewrap"><table id="rtltable"><thead><tr><th>file</th><th>lines</th><th>modules</th><th>description (file header)</th></tr></thead><tbody>%s</tbody></table></div>
<div id="rtl-view" hidden><div class="mhead"><b id="rtl-name"></b><span class="grow"></span><span id="rtl-meta" class="muted"></span></div><div id="rtl-uses" class="muted"></div><input id="rtl-find" type="search" placeholder="find in file (highlights lines)"> <pre class="src" id="rtl-src"></pre></div>''' % (
        sum(m['lines'] for m in mods if m['kind'] == 'verilog'), esc(', '.join('%s (%d B)' % h for h in hexes)), rows)


def about_html():
    nt = ''.join('<li>%s</li>' % esc(n) for n in NOTES) or '<li>nothing missing</li>'
    return '''<h1>About this site</h1>
<p>Generated %s by <code>site/build_site.py</code> (run <code>py -3.12 site/build_site.py</code>; reads the repo, writes only under <code>site/</code>). All data is embedded or loaded with <code>&lt;script src&gt;</code>, so it works from file://.</p>
<ul><li>3D: three.js r147 (non-module build + OrbitControls) vendored in <code>site/vendor/</code>, MIT licence.</li>
<li>PCB 3D: full-assembly GLB from kicad-cli (<code>render/out/apriltag_cam_full.glb</code>) converted by <code>site/glb_convert.py</code>; the STEP was <code>render/out/apriltag_cam_full.step</code>.</li>
<li>Markdown rendered with markdown-it-py; charts are inline SVG.</li>
<li>Per-image chip pose errors were recomputed at build time (<code>tests/analyze_chain.py</code> logic: firmware solver on the stored RTL tag estimates), not read from a stored file.</li></ul>
<h2>Not included / caveats at build time</h2><ul>%s</ul>
<p>The repository has other material not mirrored here (firmware/host source, tests, tools, simulation logs in <code>results/*.log</code>, raw Blender renders in <code>test_images/raw</code>).</p>''' % (time.strftime('%Y-%m-%d %H:%M'), nt)


if __name__ == '__main__':
    main()
