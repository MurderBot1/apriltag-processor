"""HTML for the 'Chip simulation' group of the site: waveform viewer, frame pipeline visualiser, block diagram.

Used by site/build_site.py:   from sim.pages import sim_pages, SIM_SCRIPTS, SIM_CSS_LINK
The heavy data (simout/waves.js, simout/pipe.js, simout/pipe/*) is produced by gen_sim.py / gen_pipeline.py and only
referenced here; if it is missing the pages say so.
"""
import os, re, html

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
esc = html.escape


def _have(*p):
    return os.path.exists(os.path.join(SITE, *p))


def _fpga_totals():
    """resource table of docs/fpga.md -> list of (resource, used, of, pct)"""
    try:
        t = open(os.path.join(ROOT, 'docs', 'fpga.md'), encoding='utf-8').read()
    except OSError:
        return []
    rows = []
    for l in t.splitlines():
        m = re.match(r'^\|\s*([^|]+?)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*\**(\d+)\**\s*\|\s*([^|]*?)\s*\|\s*$', l)
        if m: rows.append(m.groups())
    return rows


# ------------------------------------------------------------------------------------------------ waveform page
def wave_html():
    if not _have('simout', 'waves.js'):
        return '<h1>Waveform viewer</h1><p class="warn">Waveform data not generated yet: run <code>py -3.12 site/sim/gen_sim.py</code>, then rebuild the site.</p>'
    return '''<h1>Waveform viewer: the chip RTL in simulation</h1>
<p class="lead">Real simulation output: the unmodified RTL (<code>rtl/*.v</code>) run in Icarus Verilog with VCD dumping, converted by <code>site/sim/vcd_to_json.py</code> and drawn here with a small canvas viewer (no libraries, works offline).
Pick a scenario, then zoom with the mouse wheel, pan by dragging, click to place the cursor (values appear in the left column), use the arrows next to a signal to jump to its previous / next change, and add or remove signals on the right.</p>
<div id="wv-root">
 <div class="wv-bar">
  <label>Scenario <select id="wv-scen"></select></label>
  <span id="wv-radix" class="seg" title="number format of bus values"><button data-m="auto" class="on">auto</button><button data-m="hex">hex</button><button data-m="dec">dec</button><button data-m="sdec">signed</button><button data-m="bin">bin</button></span>
  <span class="seg"><button id="wv-zout" title="zoom out">&minus;</button><button id="wv-zin" title="zoom in">+</button><button id="wv-fit" title="fit whole scenario (double-click the waveform)">fit</button></span>
 </div>
 <h2 id="wv-title" class="wv-h"></h2>
 <p id="wv-desc"></p>
 <pre id="wv-pre" hidden></pre>
 <ol id="wv-steps" class="wv-steps"></ol>
 <p id="wv-src" class="muted"></p>
 <div class="wv-layout">
  <div class="wv-left">
   <div class="wv-body">
    <div id="wv-names" class="wv-names"></div>
    <div id="wv-wrap" class="wv-cvwrap"><canvas id="wv-cv"></canvas><div id="wv-tip" class="wv-tip" hidden></div></div>
   </div>
   <div id="wv-status" class="muted wv-status"></div>
   <div class="wv-markbar"><b>Events</b> <span id="wv-marks"></span></div>
  </div>
  <div class="wv-right">
   <b>Signals</b>
   <input id="wv-find" type="search" placeholder="search signals...">
   <div class="wv-pbtn"><button id="wv-def">default</button><button id="wv-all">all</button><button id="wv-none">none</button></div>
   <div id="wv-pick" class="wv-pick"></div>
  </div>
 </div>
 <p class="muted">Wheel: zoom at the pointer &middot; shift+wheel: pan &middot; drag: pan &middot; click: cursor &middot; double-click: fit. Grey hatched bands mark stretches of simulation time that were not dumped (kept small on purpose; the skipped duration is printed in the band). Orange bus segments are named states (FSM states, opcodes, program locations); red is an unknown (x) value.</p>
 <h2>How these were made</h2>
 <p>Each scenario is a short, purpose-built testbench in <code>site/sim/tb/</code> (adapted copies of <code>tb/*.v</code>: same stimulus, same DUT; only signal dumping and, for the large frames, a dump window were added). The generator <code>site/sim/gen_sim.py</code> builds the stimulus with the same Python golden models the regression tests use (<code>tools/golden.py</code>, <code>tools/dphy_stream.py</code>, <code>tools/tpu_prog.py</code>), runs <code>iverilog</code>/<code>vvp</code>, checks the RTL result against the golden model (despeckle crop, candidate list, TPU tag vs the Python instruction-set simulator) and writes <code>site/simout/waves.js</code>. Only a chosen set of signals is dumped, and only inside the windows described for each scenario, so the whole waveform data is small.</p>
</div>'''


# ------------------------------------------------------------------------------------------------ pipeline page
def _pipe_notes():
    """simulation notes computed by gen_pipeline.py from the checks of its run (stored in pipe.js)"""
    import json
    try:
        t = open(os.path.join(SITE, 'simout', 'pipe.js'), encoding='utf-8').read()
        return json.loads(t[len('window.PIPE='):t.rindex(';')]).get('notes', [])
    except (OSError, ValueError):
        return []



def pipe_html():
    if not _have('simout', 'pipe.js'):
        return '<h1>Frame pipeline</h1><p class="warn">Pipeline data not generated yet: run <code>py -3.12 site/sim/gen_pipeline.py</code>, then rebuild the site.</p>'
    notes = ''.join('  <li>%s</li>' % n for n in _pipe_notes())
    return '''<h1>Frame pipeline: what each block does to a real test frame</h1>
<p class="lead">Six of the 100 rendered test frames (different categories of the dataset) pushed through the FPGA RTL, stage by stage, then through the tag unit and pose solver that run on the RP2350. Use the stage buttons or the slider; tick <i>side by side</i> to compare a stage with the one before it. Wheel zooms (try the despeckle stage at 8x), drag pans, double-click resets.</p>
<div id="pv-root">
 <div class="pv-bar">
  <label>Frame <select id="pv-img"></select></label>
  <label class="chk"><input type="checkbox" id="pv-side"> side by side with previous stage</label>
  <span id="pv-ovl" class="pv-ovl"><label class="chk"><input type="checkbox" data-o="chip" checked> chip</label><label class="chk"><input type="checkbox" data-o="gt" checked> ground truth</label><label class="chk"><input type="checkbox" data-o="ids" checked> labels</label><label class="chk"><input type="checkbox" data-o="bb" checked> boxes</label><label class="chk"><input type="checkbox" data-o="ext" checked> extremes</label></span>
  <button id="pv-tags" title="zoom to the tag region">zoom to tags</button><button id="pv-reset">reset view</button>
 </div>
 <div id="pv-stages" class="pv-stages"></div>
 <input type="range" id="pv-slider" min="0" max="5" value="0" step="1" class="pv-slider" aria-label="pipeline stage">
 <div id="pv-wrap" class="pv-wrap"><canvas id="pv-cv"></canvas></div>
 <div id="pv-cap" class="pv-cap"></div>
 <div id="pv-info" class="pv-info"></div>
 <h2>RTL vs golden model, per frame</h2>
 <div id="pv-sum" class="tablewrap"></div>
 <h2>Simulation notes</h2>
 <ul>
%s
  <li><b>Scope.</b> The FPGA blocks (threshold, despeckle, run_ccl) are simulated here on the full 1280x800 frame with the project's own testbenches (a few seconds per block per frame in Icarus Verilog). The tag unit is no longer in the FPGA: the stored tag results come from the full-chain RTL simulation with the reference processor <code>ref/tpu/tpu_core.v</code> over all 100 frames, which <code>firmware/core/attpu.c</code> reproduces bit-exactly (<code>tests/test_fw_tpu.py</code>, all 100 frames). Tag unit timing on the MCU is an estimate from <code>tools/m33_cycles.py</code>, not a measurement on hardware.</li>
 </ul>
 <p class="muted">The stage images are the outputs of the RTL (<code>tb/tb_thresh.v</code> &rarr; <code>tb/tb_despeckle.v</code> &rarr; <code>tb/tb_ccl.v</code>, the unmodified project testbenches, each run on the whole 1280x800 frame in Icarus Verilog and fed with the previous block's RTL output). The labelled-component picture and the extreme points are drawn from <code>tools/golden.py</code> components() applied to the RTL mask (the RTL candidate records are compared with it). Tag corners and IDs are the stored full-chain RTL results (<code>results/rtl_chain_results.json</code>, the whole chip simulated from CSI-2 packets to the result bank); the pose is the firmware C solver (<code>firmware/core/atpose.c</code>, float32 build) run on those corners, exactly as for the Test images page. Frames are stored as 1280x800 JPEG (raw) and 2-3 colour PNGs (masks) under <code>site/simout/pipe/</code>.</p>
</div>''' % notes


# ------------------------------------------------------------------------------------------------ block diagram
def block_html(mods):
    lines = {m['file']: m['lines'] for m in mods}
    ln = lambda f: ('%d ln' % lines[f]) if f in lines else ''
    tot = _fpga_totals()
    W, H = 1340, 700
    bw, bh, gx = 158, 118, 32
    X = lambda c: 20 + c * (bw + gx)
    Y = {'A': 96, 'B': 292, 'C': 488}
    o = []
    a = o.append
    mid = bh // 2
    a('<svg class="bd" viewBox="0 0 %d %d" role="img" aria-label="block diagram of the ECP5 AprilTag chip">' % (W, H))
    a('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="arh"/></marker></defs>')
    cx0, cx1 = X(1) - 16, X(6) + bw + 16
    a('<rect x="%d" y="34" width="%d" height="%d" rx="16" class="chipbox"/>' % (cx0, cx1 - cx0, Y['C'] + bh + 36 - 34))
    a('<text x="%d" y="26" class="chipt">ECP5 LFE5U-25F-8BG381I &mdash; top level rtl/apriltag_cam_top.v</text>' % cx0)
    a('<rect x="%d" y="52" width="%d" height="%d" rx="12" class="dom dom-sensor"/>' % (X(1) - 8, bw + 16, bh + 52))
    a('<text x="%d" y="68" class="domt">sensor lane clocks</text>' % (X(1) - 2))
    a('<rect x="%d" y="52" width="%d" height="%d" rx="12" class="dom dom-core"/>' % (X(2) - 8, 5 * bw + 4 * gx + 16, Y['C'] + bh + 20 - 52))
    a('<text x="%d" y="68" class="domt">core clock domain 85.714 MHz (PLL from the 24 MHz oscillator; named clk100 in the RTL)</text>' % (X(2) - 2))
    a('<rect x="%d" y="%d" width="%d" height="%d" rx="12" class="dom dom-spi"/>' % (X(5) - 8, Y['C'] - 24, bw + 16, bh + 38))
    a('<text x="%d" y="%d" class="domt">SPI SCK &le; 16 MHz</text>' % (X(5) - 2, Y['C'] - 9))

    def blk(c, r, title, file, lines_, cls='', span=1):
        x, y = X(c), Y[r]; w = bw * span + gx * (span - 1)
        h = '#/rtl/' + file if file else None
        g = ['<g class="blk %s">' % cls]
        if h: g.append('<a href="%s" aria-label="open %s"><title>open rtl/%s</title>' % (h, esc(file), esc(file)))
        g.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8"/>' % (x, y, w, bh))
        g.append('<text x="%d" y="%d" class="bt">%s</text>' % (x + 9, y + 21, esc(title)))
        if file: g.append('<text x="%d" y="%d" class="bf">%s</text>' % (x + 9, y + 37, esc(file) + ('  ' + ln(file) if ln(file) else '')))
        for i, t in enumerate(lines_):
            g.append('<text x="%d" y="%d" class="bl">%s</text>' % (x + 9, y + 57 + i * 15, esc(t)))
        if h: g.append('</a>')
        g.append('</g>')
        a(''.join(g))

    def path(d, label=None, lx=0, ly=0, both=False):
        a('<path d="%s" class="arw" marker-end="url(#ar)"%s/>' % (d, ' marker-start="url(#ar)"' if both else ''))
        if label: a('<text x="%d" y="%d" class="al">%s</text>' % (lx, ly, esc(label)))

    blk(0, 'A', 'OV9281 sensor', None, ['1280x800 RAW8, 120.08 fps', 'global shutter', '2-lane MIPI, 400 MHz DDR', '(external part)'], 'ext')
    blk(1, 'A', 'D-PHY receiver', 'dphy_rx.v', ['LVDS DDR 4:1 gearing,', 'sync hunt 0xB8, deskew,', 'CDC FIFO to core clock', '(+ dphy_lane, async_fifo)'], 'sens')
    blk(2, 'A', 'CSI-2 packet layer', 'csi2_rx.v', ['header ECC (1-bit fix),', 'CRC-16, FS/FE, 2 px/clk', 'latency 3 clocks'])
    blk(3, 'A', 'Adaptive threshold', 'thresh_binarize.v', ['2x2 bin, 8x8 tile min/max,', '3x3 tile neighbourhood,', '17-row delay line,', '27 BRAM (docs/fpga.md)'])
    blk(4, 'A', 'Despeckle', 'despeckle.v', ['3x3 majority (>= 4 of 9)', '2 small row buffers', 'latency 1 row'])
    blk(5, 'A', 'Connected components', 'run_ccl.v', ['run-based 4-connected', 'labeller, union-find,', 'area + 8 extremes,', '~26 BRAM (docs/fpga.md)'])
    blk(6, 'A', 'Candidate store', 'mask_stream.v', ['candidate RAM 1024 x 32', '(2 BRAM), written by', 'run_ccl, read by the', 'streamer'], 'mem')
    for c in range(0, 6):
        path('M%d %d L%d %d' % (X(c) + bw, Y['A'] + mid, X(c + 1), Y['A'] + mid))
    # row B
    blk(1, 'B', 'System PLL', 'sys_pll.v', ['24 MHz osc in; out:', '85.714 MHz core,', '24 MHz XVCLK to sensor,', '200 MHz spare'])
    blk(2, 'B', 'I2C bring-up', 'i2c_master.v', ['+ sensor_init.v ROM', '(sensor_init.hex):', 'programs the OV9281'])
    blk(3, 'B', 'Registers / sequencer', 'cam_core.v', ['wrapper: status, config,', 'counters, ID 0x41544731,', 'device clock, IRQ'])
    blk(4, 'B', 'Mask streamer', 'mask_stream.v', ['packs 2 px/beat into words,', '16-word FIFO, 1 byte per', '4 clocks on the 8-bit bus;', 'no frame store in the FPGA'], 'mem', span=2)
    blk(6, 'B', 'Tag unit (on the MCU)', None, ['attpu.c: C port of the', 'former FPGA processor', '(ref/tpu/tpu_core.v),', 'bit-exact, runs on RP2350'], 'ext')
    # row C
    blk(0, 'C', 'RP2350 MCU', None, ['USB CDC, field map,', 'tag unit (C), pose', 'solve (LM), auto-exposure', '(external part)'], 'ext')
    blk(5, 'C', 'SPI slave', 'spi_slave.v', ['mode 0, <= 16 MHz,', '24-bit address space:', 'registers only'])
    blk(6, 'C', 'MCU frame bus', 'mask_stream.v', ['mcu_d[7:0], clk, fs:', '132,128-byte packet per', 'frame -> RP2350 PIO + DMA'], 'mem')
    # connections
    path('M%d %d L%d %d' % (X(4) + bw // 2, Y['A'] + bh, X(4) + bw // 2, Y['B']), 'binary rows', X(4) + bw // 2 + 6, Y['A'] + bh + 34)
    path('M%d %d L%d %d' % (X(6) + bw // 2, Y['A'] + bh, X(6) + bw // 2, Y['B']), 'candidates', X(6) + bw // 2 + 6, Y['A'] + bh + 34)
    path('M%d %d L%d %d' % (X(5) + bw, Y['B'] + mid, X(6), Y['B'] + mid))
    a('<text x="%d" y="%d" class="al">pixels</text>' % (X(5) + bw - 8, Y['B'] + mid - 7))
    path('M%d %d L%d %d' % (X(6) + bw // 2, Y['B'] + bh, X(6) + bw // 2, Y['C']), 'results', X(6) + bw // 2 + 6, Y['B'] + bh + 34)
    path('M%d %d L%d %d' % (X(6), Y['C'] + mid, X(5) + bw, Y['C'] + mid))
    path('M%d %d L%d %d' % (X(5), Y['C'] + mid - 16, X(0) + bw, Y['C'] + mid - 16), 'MISO (results out), IRQ on frame done', X(2) + 20, Y['C'] + mid - 22)
    path('M%d %d L%d %d' % (X(0) + bw, Y['C'] + mid + 16, X(5), Y['C'] + mid + 16), 'MOSI, SCK, CS_N (register / result reads)', X(2) + 20, Y['C'] + mid + 34)
    # sensor <-> I2C, PLL -> sensor
    path('M%d %d L%d %d L%d %d L%d %d' % (X(2) + bw // 2, Y['B'] + bh, X(2) + bw // 2, Y['B'] + bh + 14, X(0) + bw // 2 - 24, Y['B'] + bh + 14, X(0) + bw // 2 - 24, Y['A'] + bh), 'I2C (SCL, SDA)', X(0) + bw // 2 - 20, Y['B'] + bh + 28, both=True)
    path('M%d %d L%d %d L%d %d' % (X(1), Y['B'] + 30, X(0) + bw // 2 + 24, Y['B'] + 30, X(0) + bw // 2 + 24, Y['A'] + bh), '24 MHz XVCLK', X(0) + bw // 2 + 28, Y['B'] + 24)
    a('</svg>')
    legend = ['<div class="bd-leg"><span class="lg sens"></span> sensor-side clocks (eclk 400 MHz DDR / sclk, target 200 MHz, closes at 201.5-217.5 MHz over 6 seeds) '
              '<span class="lg core"></span> core clock 85.714 MHz (4 of 6 seeds close; default seed 1: 90.99 MHz; nextpnr estimates) '
              '<span class="lg spi"></span> SPI SCK domain (synchronised into the core clock) '
              '<span class="lg mem"></span> block-RAM storage <span class="lg ext"></span> external part</div>']
    tb = ''
    if tot:
        tb = ('<h2>Whole-chip resources, measured on the LFE5U-45F with older RTL (docs/fpga.md, seed 1, Yosys + nextpnr-ecp5 estimates). Shipping LFE5U-25F: 13,389 LUT4 (55%), 56 of 56 DP16KD (100%)</h2><div class="tablewrap"><table><thead><tr><th>resource</th><th>used</th><th>available</th><th>%</th><th>old all-FPGA design (85F)</th></tr></thead><tbody>' +
              ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s%%</td><td>%s</td></tr>' % tuple(esc(x) for x in r) for r in tot) + '</tbody></table></div>')
    return '''<h1>Chip block diagram</h1>
<p class="lead">Click a block to open its RTL source in the RTL browser. Pixels flow left to right along the top row; the FPGA keeps no frame store: the binary mask is streamed out at the pixel rate and the RP2350 stores it in its SRAM (three frame buffers) while it decodes the previous frame; only the registers and the 132,128-byte frame packet (binary mask plus candidate list) are exchanged with the RP2350: the mask goes over the 8-bit frame bus, registers over SPI. Tag decoding and pose run on the RP2350.</p>
%s
%s
%s
<p class="muted">Resource numbers are from <code>docs/fpga.md</code> (Yosys + nextpnr-ecp5 estimates, not signoff; nothing has been loaded onto a device): whole chip 56 DP16KD (52%% of the 108 on the 45F where this was measured; 100%% of the 56 on the shipping 25F). The per-block block-RAM figures are the ones listed there; LUT and flip-flop counts are only available for the whole chip. Lines of Verilog are counted from <code>rtl/</code>. Clock numbers: <a href="#/fpga">FPGA results</a>.</p>
<h2>Blocks and where they are specified</h2>
<div class="tablewrap"><table><thead><tr><th>block</th><th>RTL</th><th>testbench / waveform scenario</th></tr></thead><tbody>
<tr><td>D-PHY receiver</td><td><a href="#/rtl/dphy_rx.v"><code>dphy_rx.v</code></a>, <a href="#/rtl/dphy_lane.v"><code>dphy_lane.v</code></a>, <a href="#/rtl/async_fifo.v"><code>async_fifo.v</code></a></td><td><a href="#/wave?s=dphy_burst">D-PHY receive</a></td></tr>
<tr><td>CSI-2 packet layer</td><td><a href="#/rtl/csi2_rx.v"><code>csi2_rx.v</code></a></td><td><a href="#/wave?s=csi2_clean">CSI-2 clean</a>, <a href="#/wave?s=csi2_errors">CSI-2 errors</a></td></tr>
<tr><td>Adaptive threshold</td><td><a href="#/rtl/thresh_binarize.v"><code>thresh_binarize.v</code></a></td><td><a href="#/wave?s=thresh_tile">threshold tile</a></td></tr>
<tr><td>Despeckle</td><td><a href="#/rtl/despeckle.v"><code>despeckle.v</code></a></td><td><a href="#/wave?s=despeckle_tile">despeckle crop</a></td></tr>
<tr><td>Connected components</td><td><a href="#/rtl/run_ccl.v"><code>run_ccl.v</code></a></td><td><a href="#/wave?s=ccl_labels">CCL labelling</a></td></tr>
<tr><td>Tag unit (now C on the MCU)</td><td><code>firmware/core/attpu.c</code>; reference RTL <code>ref/tpu/tpu_core.v</code> (+ <code>tpu_prog.hex</code>, <code>tag36h11.hex</code>)</td><td><a href="#/wave?s=tpu_tag">reference TPU on one tag</a></td></tr>
<tr><td>Bridge, streamer, registers</td><td><a href="#/rtl/cam_core.v"><code>cam_core.v</code></a>, <a href="#/rtl/mask_stream.v"><code>mask_stream.v</code></a>, <a href="#/rtl/spi_slave.v"><code>spi_slave.v</code></a></td><td><a href="#/wave?s=mask_stream">mask streamer packet</a>, <a href="#/pipeline">pipeline page</a> (whole chain)</td></tr>
<tr><td>Sensor bring-up</td><td><a href="#/rtl/i2c_master.v"><code>i2c_master.v</code></a>, <a href="#/rtl/sensor_init.v"><code>sensor_init.v</code></a></td><td>-</td></tr>
<tr><td>Clocking, top level</td><td><a href="#/rtl/sys_pll.v"><code>sys_pll.v</code></a>, <a href="#/rtl/apriltag_cam_top.v"><code>apriltag_cam_top.v</code></a>, <a href="#/rtl/apriltag_cam.lpf"><code>apriltag_cam.lpf</code></a></td><td>-</td></tr>
</tbody></table></div>''' % (''.join(legend), ''.join(o), tb)


SIM_CSS_LINK = '<link rel="stylesheet" href="assets/sim.css">'
def sim_scripts():
    s = []
    for f in ('waves.js', 'pipe.js'):
        if _have('simout', f): s.append('<script src="simout/%s"></script>' % f)
    s.append('<script src="assets/sim.js"></script>')
    return '\n'.join(s)


def sim_pages(mods):
    """-> list of (id, group, title, html) for build_site.P_"""
    return [('blocks', 'Chip simulation', 'Block diagram', block_html(mods)),
            ('wave', 'Chip simulation', 'Waveform viewer', wave_html()),
            ('pipeline', 'Chip simulation', 'Frame pipeline', pipe_html())]
