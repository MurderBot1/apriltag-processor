#!/usr/bin/env py -3.12
"""Frame pipeline visualiser data: per test image, the chip's stage outputs as small PNG/JPEG files + overlay data.

    py -3.12 site/sim/gen_pipeline.py

Writes site/simout/pipe/<image>_<stage>.{jpg,png} and site/simout/pipe.js (window.PIPE).
Stage images are produced by the golden models in tools/golden.py (bit-exact with the RTL); for every image the
RTL itself (tb/tb_thresh.v, tb/tb_despeckle.v, tb/tb_ccl.v, run unmodified in site/sim/work/) is run on the same frame
and compared with the golden output - the result of that check is shown on the page.  The tag corners / ids are
the stored full-chain RTL results (results/rtl_chain_results.json); the pose is the firmware solver on those corners.
"""
import os, sys, json, time, shutil
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import simlib
from simlib import WORK, ROOT, build, run
import golden, geom, atcore, analyze_chain

OUT = os.path.join(os.path.dirname(HERE), 'simout')
PIPE_DIR = os.path.join(OUT, 'pipe')
IMAGES = [('normal_000', 'Normal (normal_000)'), ('dark_000', 'Dark (dark_000)'), ('noise_000', 'Sensor noise (noise_000)'),
          ('clutter_000', 'Clutter (clutter_000)'), ('persp_008', 'Strong perspective (persp_008)'),
          ('blur_009', 'Blur (blur_009)')]
CLK_MHZ = 85.714

STAGES = [
    dict(short='raw', title='Raw frame from the sensor', file='raw.jpg', rtl=['dphy_rx.v', 'csi2_rx.v'],
         caption='The OV9281 sends 1280x800 8-bit pixels over two MIPI lanes. dphy_rx recovers the bytes from the serial lanes (bit alignment, lane deskew, clock-domain crossing) and csi2_rx checks every packet (header ECC with single-bit correction, payload CRC-16) and hands on two pixels per clock. The MCU never sees this image.'),
    dict(short='threshold', title='Adaptive threshold (binary)', file='thr.png', rtl=['thresh_binarize.v'], golden='tools/golden.py binarize()',
         caption='thresh_binarize bins the frame 2x2, finds the min and max of each 8x8-pixel tile and of its 3x3 tile neighbourhood, and classifies a pixel as black when it is below (min+max)/2 in contrasty areas (or below a fixed level elsewhere). The 17-row delay line is why the output lags the input by 17 rows. Black = tag ink.'),
    dict(short='despeckle', title='Despeckle (3x3 majority)', file='desp.png', rtl=['despeckle.v'], golden='tools/golden.py despeckle()',
         caption='despeckle keeps a pixel only if at least 4 of the 9 pixels in its 3x3 neighbourhood are black. Isolated noise dots disappear (and 1-pixel holes fill) so the labeller is not flooded with tiny components. Latency: one row.'),
    dict(short='components', title='Connected components + extremes', file='ccl.png', ov='ccl', rtl=['run_ccl.v'], golden='tools/golden.py components()',
         caption='run_ccl labels the black regions on the fly (4-connected runs, union-find) and keeps per component the area and the eight extreme points (max/min of x, y, x+y, x-y). Components that pass the area / size / border filters become candidates: yellow boxes contain a tag that was decoded, red boxes are candidates that did not decode. The cyan dots are the extremes the TPU uses as a coarse quadrilateral.'),
    dict(short='TPU quads', title='Tag unit: refined quad corners + tag IDs', file='raw.jpg', ov='tpu', rtl=['ref/tpu/tpu_core.v'], golden='tools/tpu_isa.py (bit-exact ISS); firmware/core/attpu.c (C port, runs on the MCU)',
         caption='For each candidate the tag unit (C code on the RP2350, a bit-exact port of the former FPGA processor) refines the four sides to sub-pixel accuracy by line-fitting binary edge samples, builds the tag homography, samples the 6x6 data cells and matches them against the tag36h11 code ROM (587 codes x 4 rotations). Blue quads = decoded tags with their IDs; green = ground-truth corners from the renderer.'),
    dict(short='pose', title='Pose from the firmware solver vs ground truth', file='raw.jpg', ov='pose', rtl=['spi_slave.v', 'cam_core.v'], golden='firmware/core/atpose.c',
         caption='The FPGA streams the binary frame and the candidate list to the RP2350 (mask_stream, 8-bit frame bus); the MCU decodes the tags (attpu.c) and its firmware (atpose.c) undistorts the corners and solves the camera pose against the stored field map with Levenberg-Marquardt over all corners. Orange dashed quads are the field-map tags re-projected with the solved pose; blue = chip corners; green = ground truth.'),
]


def pal_png(arr, palette, path):
    im = Image.fromarray(arr.astype(np.uint8), 'P')
    pal = []
    for c in palette: pal += list(c)
    im.putpalette(pal + [0] * (768 - len(pal)))
    im.save(path, optimize=True)


def rtl_stages(name, img):
    """run the unmodified RTL testbenches on this frame (threshold -> despeckle -> CCL, each fed with the previous
    RTL output).  Returns (thr, desp, cand_records, ccl_result_line)"""
    img.astype(np.uint8).tofile(os.path.join(WORK, 'p_img.raw'))
    v = build('p_thresh', ['rtl/thresh_binarize.v', 'tb/tb_thresh.v'], top='tb_thresh')
    run(v, ['img=p_img.raw', 'out=p_thr.bin'])
    thr = np.fromfile(os.path.join(WORK, 'p_thr.bin'), np.uint8).reshape(800, 1280).astype(bool)
    thr.astype(np.uint8).tofile(os.path.join(WORK, 'p_mask.bin'))
    v = build('p_desp', ['rtl/despeckle.v', 'tb/tb_despeckle.v'], top='tb_despeckle')
    run(v, ['mask=p_mask.bin', 'out=p_desp.bin'])
    desp = np.fromfile(os.path.join(WORK, 'p_desp.bin'), np.uint8).reshape(800, 1280).astype(bool)
    desp.astype(np.uint8).tofile(os.path.join(WORK, 'p_mask2.bin'))
    v = build('p_ccl', ['rtl/run_ccl.v', 'tb/tb_ccl.v'], top='tb_ccl')
    log = run(v, ['mask=p_mask2.bin', 'out=p_ccl.txt'])
    res = [l for l in log.splitlines() if l.startswith('RESULT')]
    lines = open(os.path.join(WORK, 'p_ccl.txt')).read().split()
    n = int(lines[0]); words = [int(x, 16) for x in lines[1:]]
    return thr, desp, [words[16 * i:16 * i + 16] for i in range(n)], (res[-1] if res else '')


def main():
    os.makedirs(PIPE_DIR, exist_ok=True); os.makedirs(WORK, exist_ok=True)
    gtj = json.load(open(os.path.join(ROOT, 'test_images', 'ground_truth.json')))
    rtl_all = json.load(open(os.path.join(ROOT, 'results', 'rtl_chain_results.json')))
    m33_rows = json.load(open(os.path.join(ROOT, 'results', 'tpu_c_m33_cycles.json')))['rows']
    ref = json.load(open(os.path.join(ROOT, 'results', 'reference_baseline.json')))
    tmap = geom.load_tag_map()
    sol = atcore.Solver(False); sol.set_field(tmap)
    K = geom.K_matrix()
    rng = np.random.default_rng(1)
    pal = [(255, 255, 255), (0, 0, 0)]
    cols = [(255, 140, 0), (0, 160, 255), (0, 200, 90), (230, 60, 160), (170, 110, 255), (240, 220, 0), (0, 210, 210), (255, 90, 90)]
    images = []
    for name, label in IMAGES:
        print(name)
        img = np.array(Image.open(os.path.join(ROOT, 'test_images', 'sensor', name + '.png')).convert('L'))
        g = gtj['images'][name]
        thr_g = golden.binarize(img)
        thr, desp, recs, ccl_line = rtl_stages(name, img)          # displayed stages = RTL outputs
        keep, lab, allc = golden.components(desp)                   # labels / extremes for the overlay (golden model on the RTL mask)
        thr_rows = sorted(set(np.nonzero(thr != thr_g)[0].tolist()))
        chk = dict(thr_diff=int((thr != thr_g).sum()), thr_rows=thr_rows, desp_diff=int((desp != golden.despeckle(thr)).sum()))
        rtl_c = sorted((r[0], r[10] & 0xFFFF, r[11] & 0xFFFF, r[10] >> 16, r[11] >> 16) for r in recs)
        gold_c = sorted((c['area'], c['x0'], c['y0'], c['x1'], c['y1']) for c in keep)
        import re as _re
        m_ = _re.search(r'count=(\d+) flags=(\d+) max_row_cycles=(\d+)', ccl_line)
        chk.update(ccl_n_rtl=len(recs), ccl_n_gold=len(gold_c), ccl_match=rtl_c == gold_c, ccl_flags=int(m_.group(2), 2) if m_ else -1, ccl_row_cycles=int(m_.group(3)) if m_ else -1)
        # --- stage images
        Image.fromarray(img).save(os.path.join(PIPE_DIR, name + '_raw.jpg'), quality=70, optimize=True)
        pal_png(thr.astype(np.uint8), [(255, 255, 255), (20, 20, 20)], os.path.join(PIPE_DIR, name + '_thr.png'))
        pal_png(desp.astype(np.uint8), [(255, 255, 255), (20, 20, 20)], os.path.join(PIPE_DIR, name + '_desp.png'))
        # labelled components: kept ones coloured, others dark grey on light background
        pim = np.zeros(desp.shape, np.uint8)
        pim[desp] = 1
        keep_l = {c['label']: i for i, c in enumerate(keep)}
        for L, i in keep_l.items():
            pim[lab == L] = 2 + i % len(cols)
        pal_png(pim, [(246, 246, 246), (150, 150, 150)] + cols, os.path.join(PIPE_DIR, name + '_ccl.png'))
        # --- chip detections / GT
        det = {t['id']: t for t in rtl_all[name]['tags']}
        tags = []
        ids = set(det) | {int(k) for k in g['tags']}
        for tid in sorted(ids):
            e = {'id': tid}
            gt = g['tags'].get(str(tid))
            if gt: e['gt'] = [[round(a, 1), round(b, 1)] for a, b in gt['corners']]; e['vis'] = bool(gt['visible'])
            if tid in det: e['chip'] = [[round(a, 2), round(b, 2)] for a, b in det[tid]['corners']]
            tags.append(e)
        chip_cent = [np.array(det[t]['corners']).mean(axis=0) for t in det]
        cc = []
        for c in keep:
            ys, xs = np.nonzero(lab == c['label'])
            sc = np.stack([xs, -xs, ys, -ys, xs + ys, -(xs + ys), xs - ys, ys - xs])
            ext = []
            for row in sc:
                k = int(np.argmax(row)); p = [int(xs[k]), int(ys[k])]
                if p not in ext: ext.append(p)
            istag = any(c['x0'] <= q[0] <= c['x1'] and c['y0'] <= q[1] <= c['y1'] for q in chip_cent)
            cc.append(dict(l=int(c['label']), a=c['area'], x0=c['x0'], y0=c['y0'], x1=c['x1'], y1=c['y1'], tag=bool(istag), ext=ext))
        # --- pose
        pose = sol.solve([(t, np.array(det[t]['corners'])) for t in det if t in tmap]) if det else None
        reproj = []
        info = {}
        if pose:
            R, t_, rms, n, fl = pose
            for tid in det:
                if tid in tmap:
                    px_, z = geom.project(geom.tag_corners_world(tmap, tid), R, t_, K, geom.DIST_TRUE)
                    reproj.append([[round(float(a), 2), round(float(b), 2)] for a, b in px_])
            terr = float(np.linalg.norm(t_ - np.array(g['t_wc'])) * 1000); rerr = float(geom.rot_angle_deg(R, np.array(g['R_wc'])))
            info = dict(t=[round(float(x), 4) for x in t_], terr=round(terr, 2), rerr=round(rerr, 3), rms=round(float(rms), 3), n=int(n))
        vis = [t for t in g['tags'].values() if t['visible']]
        found = [t for t in det if str(t) in g['tags'] and g['tags'][str(t)]['visible']]
        cerr = [float(np.linalg.norm(np.array(det[t]['corners']) - np.array(g['tags'][str(t)]['corners']), axis=1).max()) for t in found]
        st = rtl_all[name]['stats']
        tpu_ms = next((r['cycles']['nominal'] / 150e3 for r in m33_rows if r['name'] == name), 0.0)      # estimate, tools/m33_cycles.py
        rd = ref['per_image'].get(name, {})
        # --- RTL equality checks (unmodified testbenches)
        print('   rtl checks', chk)
        flagtxt = ', '.join(n_ for bit, n_ in enumerate(['row overrun', 'run overflow', 'label overflow', 'candidate overflow']) if chk['ccl_flags'] > 0 and chk['ccl_flags'] >> bit & 1)
        notes = [
            'Frame %s: mean grey %.0f, min %d, max %d. (Stage images below are the outputs of the RTL simulated in Icarus Verilog, one testbench per block, each fed with the RTL output of the previous block.)' % (name, img.mean(), img.min(), img.max()),
            'Black pixels: %d (%.1f%% of the frame). RTL vs golden model tools/golden.py binarize(): %s' % (int(thr.sum()), 100 * thr.mean(),
                '<span class="good">identical</span> (0 of 1,024,000 pixels differ).' if chk['thr_diff'] == 0 else '<span class="bad">%d pixels differ</span>, all in image row%s %s (golden says %s). See the simulation notes below.' % (chk['thr_diff'], '' if len(thr_rows) == 1 else 's', ', '.join(map(str, thr_rows)), 'black' if (thr_g & ~thr).any() else 'white')),
            'Despeckle changed %d pixels. RTL vs golden despeckle() on the same input: %s' % (int((thr != desp).sum()), '<span class="good">identical</span>.' if chk['desp_diff'] == 0 else '<span class="bad">%d differ</span>.' % chk['desp_diff']),
            '%d components in the frame, %d pass the candidate filters (%d contain a decoded tag). RTL run_ccl candidate list (area + bounding box) vs golden components(): %s' % (len(allc), len(keep), sum(c['tag'] for c in cc),
                '<span class="good">identical</span> (%d candidates).' % chk['ccl_n_rtl'] if chk['ccl_match'] else '<span class="bad">RTL reports %d candidates, golden %d</span>%s (worst row %d clocks).' % (chk['ccl_n_rtl'], chk['ccl_n_gold'], ' - run_ccl status flags: ' + flagtxt if flagtxt else '', chk['ccl_row_cycles'])),
            'Chip decoded %d of %d ground-truth-visible tags%s. Mean/max corner error vs ground truth: %s px. Tag unit on the MCU: %.2f ms (estimate, Cortex-M33 at 150 MHz, tools/m33_cycles.py); chain data from results/rtl_chain_results.json.' % (
                len(found), len(vis), '' if len(det) == len(found) else ' (+%d further detections that match no visible ground-truth tag: wrong id or non-visible tag)' % (len(det) - len(found)),
                '%.2f / %.2f' % (np.mean(cerr), np.max(cerr)) if cerr else '-', tpu_ms),
            ('Solved from %d tags: position error %.1f mm, orientation error %.3f deg, reprojection rms %.2f px (reference pupil-apriltags + solvePnP: %s mm).' % (info['n'], info['terr'], info['rerr'], info['rms'], ('%.1f' % rd['t_err_mm']) if rd.get('t_err_mm') is not None else 'n/a')
             if pose else 'No pose: the chip decoded no tag in this frame, so the solver has nothing to work with.'),
        ]
        gtt = g['t_wc']
        tbl = '<table><tr><th></th><th>x (m)</th><th>y (m)</th><th>z (m)</th></tr><tr><td>ground truth camera position</td>' + ''.join('<td>%.4f</td>' % x for x in gtt) + '</tr>'
        if pose:
            tbl += '<tr><td>chip + firmware solver</td>' + ''.join('<td>%.4f</td>' % x for x in info['t']) + '</tr>'
        tbl += '</table>'
        row_info = ('<b>%s</b> &middot; category <code>%s</code> &middot; %d / %d visible tags decoded by the chip' % (label, g['category'], len(found), len(vis))
                    + (' &middot; position error <b>%.1f mm</b>, orientation error <b>%.3f deg</b>, %d tags in the solve' % (info['terr'], info['rerr'], info['n']) if pose else ' &middot; <b>no pose</b>') + tbl)
        images.append(dict(name=name, label=label, cat=g['category'], info=row_info, notes=notes, ccl=cc, tags=tags, reproj=reproj, pose=info, checks={k: (bool(v) if isinstance(v, (bool, np.bool_)) else v) for k, v in chk.items()}))
    # simulation notes: derived from the checks of this run (never hand-written numbers)
    notes = []
    td = [(i['name'], i['checks']['thr_diff'], i['checks']['thr_rows']) for i in images if i['checks']['thr_diff']]
    if td:
        notes.append('<b>Threshold RTL vs golden.</b> ' + '; '.join('%s: %d pixels differ (image rows %s)' % (n_, d_, ', '.join(map(str, r_[:6])) + (' ...' if len(r_) > 6 else '')) for n_, d_, r_ in td)
                     + '. The RTL was not modified and the cause was not investigated; the table above lists every frame.')
    else:
        notes.append('<b>Threshold RTL vs golden.</b> Identical on all %d frames shown.' % len(images))
    dd = [i['name'] for i in images if i['checks']['desp_diff']]
    notes.append('<b>Despeckle RTL vs golden.</b> ' + ('differs on ' + ', '.join(dd) + '.' if dd else 'Identical on all %d frames shown.' % len(images)))
    cc_ = [i for i in images if not i['checks']['ccl_match']]
    if cc_:
        notes.append('<b>run_ccl RTL vs golden components().</b> ' + '; '.join('%s: RTL %d candidates, golden %d, status flags %s, worst row %d clocks' % (i['name'], i['checks']['ccl_n_rtl'], i['checks']['ccl_n_gold'], bin(i['checks']['ccl_flags']), i['checks']['ccl_row_cycles']) for i in cc_) + '.')
    else:
        notes.append('<b>run_ccl RTL vs golden components().</b> Candidate lists (area + bounding box) identical on all %d frames shown.' % len(images))
    data = dict(dir='simout/pipe', w=1280, h=800, stages=STAGES, images=images, notes=notes)
    open(os.path.join(OUT, 'pipe.js'), 'w').write('window.PIPE=' + json.dumps(data, separators=(',', ':')) + ';')
    for f in os.listdir(WORK):
        fp = os.path.join(WORK, f)
        if f.startswith('p_') and os.path.isfile(fp): os.remove(fp)
    tot = sum(os.path.getsize(os.path.join(PIPE_DIR, f)) for f in os.listdir(PIPE_DIR))
    print('pipe images %.1f MB; pipe.js %d KB' % (tot / 1e6, os.path.getsize(os.path.join(OUT, 'pipe.js')) // 1000))


if __name__ == '__main__':
    main()
