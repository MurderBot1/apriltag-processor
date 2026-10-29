/* Interactive charts for the Verification / FPGA pages.
   1. progressive enhancement of the build-time inline SVG charts (svg.chart): hover tooltips with exact values, click a legend entry to toggle a series,
      axis titles with units, horizontal scroll instead of unreadable shrinking on phones, category labels link to the filtered gallery.
   2. the per-image error strip is rebuilt from GALLERY data as a responsive, sortable, filterable chart with hover thumbnails and click-through to the image.
   Vanilla JS, offline. */
(function () {
'use strict';
var NS = 'http://www.w3.org/2000/svg';
var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function sv(tag, attrs, txt) { var e = document.createElementNS(NS, tag); if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]); if (txt != null) e.textContent = txt; return e; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

/* ---------------- shared tooltip */
var tip = null;
function showTip(html, x, y) {
  if (!tip) { tip = el('div', 'ch-tip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
  tip.hidden = false; tip.innerHTML = html;
  var w = tip.offsetWidth, h = tip.offsetHeight, vx = window.innerWidth, vy = window.innerHeight;
  var px = x + 14; if (px + w > vx - 6) px = x - w - 14; var py = y + 14; if (py + h > vy - 6) py = y - h - 14;
  tip.style.left = Math.max(4, px) + 'px'; tip.style.top = Math.max(4, py) + 'px';
}
function hideTip() { if (tip) tip.hidden = true; }
var SERIES_COL = { c1: 'var(--c1)', c2: 'var(--c2)', c3: 'var(--c3)', c4: 'var(--c4)' };
function serOf(r) { var m = /\bc([1-4])\b/.exec(r.getAttribute('class') || ''); return m ? 'c' + m[1] : 'c1'; }

/* ---------------- 1. enhance static svg charts */
function enhance(svg) {
  if (svg.__ch || svg.closest('.errstrip')) return; svg.__ch = 1;
  var vb = svg.viewBox.baseVal; if (!vb || !vb.width) return;
  var title = ($('.ct', svg) || {}).textContent || svg.getAttribute('aria-label') || '';
  var wrap = el('div', 'chartwrap'); svg.parentNode.insertBefore(wrap, svg); wrap.appendChild(svg);
  var unitM = /\(([^()]*)\)\s*(?:\.|$)/.exec(title) || /\(([^()]*)\)[^()]*$/.exec(title), unit = unitM ? unitM[1] : '';
  /* legend: <rect.bar y=4 w=11 h=11> followed by <text.cl> */
  var legend = [];
  $$('rect.bar', svg).forEach(function (r) {
    if (r.getAttribute('y') === '4' && r.getAttribute('width') === '11') { var t = r.nextElementSibling; if (t && t.classList.contains('cl')) legend.push({ rect: r, text: t, cls: serOf(r), name: t.textContent }); }
  });
  var bars = $$('rect.bar', svg).filter(function (r) { return !legend.some(function (l) { return l.rect === r; }); });
  var dots = $$('.dot', svg);
  var isH = !!$('text.cv', svg);       /* horizontal bar chart (label left, value right) */
  /* make room for axis titles by growing the viewBox */
  var padL = isH ? 0 : 16, padB = 16;
  svg.setAttribute('viewBox', (vb.x - padL) + ' ' + vb.y + ' ' + (vb.width + padL) + ' ' + (vb.height + padB));
  if (!isH && unit) {
    var yt = sv('text', { 'class': 'axl', transform: 'translate(' + (vb.x - padL + 10) + ',' + (vb.height / 2 + 20) + ') rotate(-90)', 'text-anchor': 'middle' }, unit); svg.appendChild(yt);
    var cats = $$('text.ca[text-anchor="middle"]', svg); if (cats.length) svg.appendChild(sv('text', { 'class': 'axl', x: vb.width / 2, y: vb.height + padB - 3, 'text-anchor': 'middle' }, /seed/i.test(cats[0].textContent) ? 'place-and-route seed' : 'image category (click a label to open its images)'));
  }
  if (isH) svg.appendChild(sv('text', { 'class': 'axl', x: vb.width / 2 + 100, y: vb.height + padB - 3, 'text-anchor': 'middle' }, unit ? 'value (' + unit.trim() + ')' : 'value'));
  /* ----- tooltips */
  var catLabels = $$('text.ca[text-anchor="middle"]', svg).map(function (t) { return { t: t, x: parseFloat(t.getAttribute('x')), name: t.textContent }; });
  bars.forEach(function (r) { var ti = $('title', r); r.__t = ti ? ti.textContent : ''; if (ti) ti.remove(); });
  function colorDot(cls) { return '<i style="background:' + SERIES_COL[cls] + '"></i>'; }
  if (isH) {
    var labs = $$('text.cl', svg).filter(function (t) { return !legend.some(function (l) { return l.text === t; }); }), vals = $$('text.cv', svg);
    bars.forEach(function (r, k) {
      var lab = labs[k] ? labs[k].textContent : '', val = vals[k] ? vals[k].textContent : '';
      var y = parseFloat(r.getAttribute('y')), hit = sv('rect', { 'class': 'rowhit', x: 0, y: y - 3, width: vb.width, height: 24 }); svg.insertBefore(hit, r);
      function on(e) { r.classList.add('hl'); showTip('<b>' + colorDot(serOf(r)) + esc(lab) + '</b>' + esc(val), e.clientX, e.clientY); }
      hit.addEventListener('pointermove', on); hit.addEventListener('pointerleave', function () { r.classList.remove('hl'); hideTip(); }); hit.addEventListener('click', on);
      r.__label = lab;
    });
  } else {
    var nearest = function (x) { var b = null, bd = 1e9; catLabels.forEach(function (c) { var d = Math.abs(c.x - x); if (d < bd) { bd = d; b = c; } }); return b; };
    var groups = {};
    bars.forEach(function (r) { var c = nearest(parseFloat(r.getAttribute('x')) + parseFloat(r.getAttribute('width')) / 2); r.__cat = c ? c.name : ''; (groups[r.__cat] = groups[r.__cat] || []).push(r); });
    bars.forEach(function (r) {
      function on(e) {
        var g = groups[r.__cat] || [r], rows = g.map(function (b) { var m = /^(.*?):\s*(.*)$/.exec(b.__t) || [0, b.__t, '']; var sname = m[1].indexOf(r.__cat) === 0 ? m[1].slice(r.__cat.length).trim() : m[1]; return '<div' + (b === r ? '' : ' class="muted"') + '>' + colorDot(serOf(b)) + esc(sname) + ': <b style="display:inline">' + esc(m[2]) + '</b></div>'; }).join('');
        r.classList.add('hl'); showTip('<b>' + esc(r.__cat) + '</b>' + rows, e.clientX, e.clientY);
      }
      r.addEventListener('pointermove', on); r.addEventListener('pointerleave', function () { r.classList.remove('hl'); hideTip(); }); r.addEventListener('click', on);
    });
    /* category labels of per-category charts link to the gallery filtered by that category */
    var cn = window.GALLERY ? GALLERY.images.reduce(function (a, i) { a[i.cat] = 1; return a; }, {}) : {};
    catLabels.forEach(function (c) { if (cn[c.name]) { c.t.classList.add('catlink'); c.t.setAttribute('tabindex', '0'); c.t.setAttribute('role', 'link'); var go = function () { location.hash = '#/gallery?cat=' + encodeURIComponent(c.name); }; c.t.addEventListener('click', go); c.t.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); }); var tt = sv('title', null, 'open the ' + c.name + ' images'); c.t.appendChild(tt); } });
  }
  /* ----- legend toggles */
  legend.forEach(function (L) {
    var g = sv('g', { 'class': 'legend-item' }); L.rect.parentNode.insertBefore(g, L.rect); g.appendChild(L.rect); g.appendChild(L.text);
    var bb = { x: parseFloat(L.rect.getAttribute('x')) - 3, y: 1, w: 11 + 4 + L.text.textContent.length * 6.6 + 8, h: 17 };
    var hit = sv('rect', { 'class': 'legend-hit', x: bb.x, y: bb.y, width: bb.w, height: bb.h, tabindex: 0, role: 'button', 'aria-pressed': 'true', 'aria-label': 'toggle series ' + L.name }); g.appendChild(hit);
    hit.appendChild(sv('title', null, 'click to show / hide: ' + L.name));
    function tog() {
      var off = !g.classList.contains('off'); g.classList.toggle('off', off); hit.setAttribute('aria-pressed', String(!off));
      bars.concat(dots).forEach(function (b) { if (serOf(b) === L.cls) b.style.display = off ? 'none' : ''; });
      hideTip();
    }
    hit.addEventListener('click', tog); hit.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tog(); } });
  });
}

/* ---------------- 2. per-image error strip */
var METRICS = {
  chip_t: { label: 'chip + solver camera position error', unit: 'mm', get: function (i) { return i.pose ? i.pose.t_mm : null; }, ref: function (i) { return i.ref ? i.ref.t_mm : null; } },
  chip_r: { label: 'chip + solver orientation error', unit: 'deg', get: function (i) { return i.pose ? i.pose.rot_deg : null; }, ref: function (i) { return i.ref ? i.ref.rot_deg : null; } },
  rms: { label: 'reprojection rms', unit: 'px', get: function (i) { return i.pose ? i.pose.rms_px : null; }, ref: function (i) { return i.ref ? i.ref.rms_px : null; } },
  corner: { label: 'worst tag corner error (chip)', unit: 'px', get: function (i) { var m = null; for (var k in i.tags) { var e = i.tags[k].err; if (e != null && (m == null || e > m)) m = e; } return m; }, ref: function () { return null; } },
  miss: { label: 'missed tags (visible but not detected)', unit: 'tags', get: function (i) { return i.vis - i.found; }, ref: function (i) { return i.ref && i.ref.det != null ? Math.max(0, i.vis - i.ref.det) : null; } }
};
function median(a) { a = a.filter(function (x) { return x != null; }).sort(function (x, y) { return x - y; }); return a.length ? a[a.length >> 1] : null; }
function niceMax(v) { var p = Math.pow(10, Math.floor(Math.log10(v || 1))), n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; }

function buildStrip(host, old) {
  var G = window.GALLERY; if (!G) return;
  var cats = []; G.images.forEach(function (i) { if (cats.indexOf(i.cat) < 0) cats.push(i.cat); });
  var st = { metric: 'chip_t', sort: 'val', cat: '', ref: true, chip: true, cap: 'auto', cur: -1 }, rows = [];
  var box = el('div', 'errstrip'); box.setAttribute('aria-label', 'per-image error chart');
  box.innerHTML = '<div class="esbar"><label>metric <select data-k="metric">' + Object.keys(METRICS).map(function (k) { return '<option value="' + k + '">' + METRICS[k].label + '</option>'; }).join('') + '</select></label>' +
    '<label>sort <select data-k="sort"><option value="val">value (low to high)</option><option value="vald">value (high to low)</option><option value="name">name</option><option value="cat">category</option></select></label>' +
    '<label>category <select data-k="cat"><option value="">all</option>' + cats.map(function (c) { return '<option>' + c + '</option>'; }).join('') + '</select></label>' +
    '<label>y limit <select data-k="cap"><option value="auto">auto (clip outliers)</option><option value="max">full range</option></select></label>' +
    '<span class="muted" id="es-n"></span></div><div class="es-svg" tabindex="0" role="img" aria-label="Per-image error bars. Use left and right arrow keys to move, Enter to open the image."></div>' +
    '<div class="muted" style="font-size:.82em">Hover a bar for details, click it to open that image in the viewer. Click the legend entries to hide the chip bars or the reference dots. Arrow keys move the cursor, Enter opens.</div>';
  host.parentNode.insertBefore(box, host); host.style.display = 'none'; host.setAttribute('aria-hidden', 'true');
  var svgBox = $('.es-svg', box), nlab = $('#es-n', box);
  $$('select', box).forEach(function (s) { s.value = st[s.getAttribute('data-k')]; s.onchange = function () { st[s.getAttribute('data-k')] = s.value; draw(); }; });
  function data() {
    var M = METRICS[st.metric];
    rows = G.images.filter(function (i) { return !st.cat || i.cat === st.cat; }).map(function (i) { return { i: i, v: M.get(i), r: M.ref(i) }; }).filter(function (r) { return r.v != null; });
    rows.sort(function (a, b) { return st.sort === 'val' ? a.v - b.v : st.sort === 'vald' ? b.v - a.v : st.sort === 'name' ? (a.i.name < b.i.name ? -1 : 1) : (a.i.cat < b.i.cat ? -1 : a.i.cat > b.i.cat ? 1 : a.v - b.v); });
  }
  function draw() {
    data(); var M = METRICS[st.metric], W = Math.max(svgBox.clientWidth || box.clientWidth || 700, 320), H = W < 520 ? 230 : 280, ml = 46, mr = 8, mt = 34, mb = 40;
    var vals = rows.map(function (r) { return r.v; }), med = median(vals), medRef = median(rows.map(function (r) { return r.r; })), s = vals.slice().sort(function (a, b) { return a - b; });
    var p95 = s.length ? s[Math.min(s.length - 1, Math.floor(s.length * 0.95))] : 1, mx = s.length ? s[s.length - 1] : 1;
    var cap = niceMax((st.cap === 'auto' ? Math.max(p95 * 1.15, med * 2, 1e-6) : Math.max(mx, 1e-6)) * 1.0);
    if (st.metric === 'miss') cap = Math.max(1, Math.ceil(st.cap === 'auto' ? Math.max(p95, 1) : mx));
    var pw = W - ml - mr, ph = H - mt - mb, bw = pw / Math.max(rows.length, 1);
    nlab.textContent = rows.length + ' images' + (med != null ? ', median ' + med.toFixed(M.unit === 'tags' ? 0 : 2) + ' ' + M.unit : '') + (medRef != null ? ' (reference median ' + medRef.toFixed(2) + ')' : '');
    var svg = sv('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'presentation' });
    svg.appendChild(sv('text', { x: 0, y: 14, 'class': 'ct' }, 'Per-image ' + M.label + ' (' + M.unit + ')' + (rows.some(function (r) { return r.v > cap; }) ? ', clipped at ' + cap : '')));
    for (var k = 0; k <= 4; k++) { var y = mt + ph - ph * k / 4; svg.appendChild(sv('line', { x1: ml, x2: W - mr, y1: y, y2: y, 'class': 'grid' })); svg.appendChild(sv('text', { x: ml - 5, y: y + 4, 'class': 'ca', 'text-anchor': 'end' }, +(cap * k / 4).toPrecision(3))); }
    var yl = sv('text', { 'class': 'axl ca', transform: 'translate(11,' + (mt + ph / 2) + ') rotate(-90)', 'text-anchor': 'middle', style: 'font-style:italic' }, M.unit); svg.appendChild(yl);
    svg.appendChild(sv('text', { x: ml + pw / 2, y: H - 6, 'class': 'ca', 'text-anchor': 'middle', style: 'font-style:italic' }, 'test image (' + (st.sort === 'val' ? 'sorted by value' : st.sort === 'vald' ? 'sorted by value, descending' : st.sort === 'name' ? 'by name' : 'by category') + ')'));
    if (med != null && med <= cap) { var my = mt + ph - ph * med / cap; svg.appendChild(sv('line', { x1: ml, x2: W - mr, y1: my, y2: my, 'class': 'emed' })); svg.appendChild(sv('text', { x: W - mr - 2, y: my - 3, 'class': 'ca', 'text-anchor': 'end', fill: 'var(--c3)' }, 'median ' + med.toFixed(M.unit === 'tags' ? 0 : 2))); }
    var gb = sv('g'), gd = sv('g'); svg.appendChild(gb); svg.appendChild(gd);
    rows.forEach(function (r, k) {
      var h = ph * Math.min(r.v, cap) / cap, x = ml + k * bw;
      if (st.chip) {
        var b = sv('rect', { 'class': 'eb', x: x + (bw > 3 ? 0.4 : 0), y: mt + ph - h, width: Math.max(bw - (bw > 3 ? 0.8 : 0), 0.8), height: Math.max(h, 0.8), 'data-k': k }); gb.appendChild(b);
        if (r.v > cap) gb.appendChild(sv('path', { 'class': 'eclip', d: 'M' + (x + bw / 2 - 3) + ' ' + (mt - 1) + 'l3 6 3 -6z' }));
      }
      if (st.ref && r.r != null) gd.appendChild(sv('circle', { 'class': 'ed', cx: x + bw / 2, cy: mt + ph - ph * Math.min(r.r, cap) / cap, r: bw > 6 ? 2.6 : 1.8, 'data-k': k }));
    });
    var cur = sv('line', { 'class': 'escur', y1: mt, y2: mt + ph, x1: 0, x2: 0 }); cur.style.display = 'none'; svg.appendChild(cur);
    /* category colour ticks along the x axis when sorted by category */
    if (st.sort === 'cat') { var last = null, x0 = 0; rows.concat([{ i: { cat: null } }]).forEach(function (r, k) { if (r.i.cat !== last) { if (last != null) { var xa = ml + x0 * bw, xb = ml + k * bw; svg.appendChild(sv('line', { x1: xa + 1, x2: xb - 1, y1: mt + ph + 4, y2: mt + ph + 4, stroke: 'var(--muted)' })); if (xb - xa > 28) svg.appendChild(sv('text', { x: (xa + xb) / 2, y: mt + ph + 16, 'class': 'ca', 'text-anchor': 'middle' }, last)); } last = r.i.cat; x0 = k; } }); }
    /* legend (clickable) */
    var lx = W - mr, items = [['chip + solver (bar)', 'chip'], ['reference (dot)', 'ref']];
    items.reverse().forEach(function (it) {
      var wlg = it[0].length * 6.2 + 22; lx -= wlg; var g = sv('g', { 'class': 'eslg' + (st[it[1]] ? '' : ' off'), tabindex: 0, role: 'button', 'aria-pressed': String(!!st[it[1]]) });
      if (it[1] === 'chip') g.appendChild(sv('rect', { x: lx, y: 4, width: 11, height: 11, 'class': 'eb', rx: 2, style: 'pointer-events:none' })); else g.appendChild(sv('circle', { cx: lx + 5.5, cy: 9.5, r: 4.5, 'class': 'ed' }));
      g.appendChild(sv('text', { x: lx + 16, y: 14 }, it[0])); g.appendChild(sv('rect', { x: lx - 3, y: 1, width: wlg, height: 17, fill: 'transparent' }));
      var t = function () { st[it[1]] = !st[it[1]]; draw(); }; g.addEventListener('click', t); g.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); t(); } }); svg.appendChild(g);
    });
    svgBox.innerHTML = ''; svgBox.appendChild(svg);
    function idxAt(e) { var r = svg.getBoundingClientRect(), x = (e.clientX - r.left) * (W / r.width); return Math.floor((x - ml) / bw); }
    function setCur(k, e, open) {
      st.cur = k; $$('.eb.hl', svg).forEach(function (b) { b.classList.remove('hl'); });
      if (k < 0 || k >= rows.length) { cur.style.display = 'none'; hideTip(); return; }
      var rr = rows[k], i = rr.i, b = $('.eb[data-k="' + k + '"]', svg); if (b) b.classList.add('hl');
      cur.style.display = ''; cur.setAttribute('x1', ml + k * bw + bw / 2); cur.setAttribute('x2', ml + k * bw + bw / 2);
      var miss = i.vis - i.found, nd = M.unit === 'tags' ? 0 : 2;
      var html = '<b>' + esc(i.name) + ' <span class="muted">[' + esc(i.cat) + ']</span></b>' + esc(M.label) + ': <b style="display:inline">' + rr.v.toFixed(nd) + ' ' + M.unit + '</b><br>' + (rr.r != null ? 'reference: ' + rr.r.toFixed(nd) + ' ' + M.unit + '<br>' : '') +
        'tags found ' + i.found + '/' + i.vis + (miss > 0 ? ' (' + miss + ' missed)' : '') + (i.false || i.unseen ? ', ' + (i.false + i.unseen) + ' extra' : '') + '<br><span class="muted">click to open</span><img src="thumbs/' + encodeURIComponent(i.name) + '.jpg" alt="">';
      var cx, cy; if (e && e.clientX != null) { cx = e.clientX; cy = e.clientY; } else { var sr = svg.getBoundingClientRect(); cx = sr.left + (ml + k * bw + bw / 2) * sr.width / W; cy = sr.top + mt * sr.height / H; }
      showTip(html, cx, cy);
      if (open) location.hash = '#/gallery/' + encodeURIComponent(i.name);
    }
    svg.addEventListener('pointermove', function (e) { var k = idxAt(e); setCur(k, e); svg.style.cursor = k >= 0 && k < rows.length ? 'pointer' : ''; });
    svg.addEventListener('pointerleave', function () { setCur(-1); });
    svg.addEventListener('click', function (e) { var k = idxAt(e); if (k >= 0 && k < rows.length) location.hash = '#/gallery/' + encodeURIComponent(rows[k].i.name); });
    svgBox.onkeydown = function (e) {
      if (e.key === 'ArrowRight') setCur(Math.min(rows.length - 1, st.cur + 1)); else if (e.key === 'ArrowLeft') setCur(Math.max(0, st.cur < 0 ? 0 : st.cur - 1));
      else if (e.key === 'Enter' && st.cur >= 0) location.hash = '#/gallery/' + encodeURIComponent(rows[st.cur].i.name); else if (e.key === 'Escape') setCur(-1); else return; e.preventDefault();
    };
    svgBox.onblur = function () { hideTip(); };
  }
  var tmr = 0, lastW = 0;
  if (window.ResizeObserver) new ResizeObserver(function () { var w = svgBox.clientWidth; if (w && Math.abs(w - lastW) > 2) { lastW = w; clearTimeout(tmr); tmr = setTimeout(draw, 60); } }).observe(svgBox);
  draw();
}

/* ---------------- boot */
function run() {
  var strip = $$('svg.chart').filter(function (s) { return /per-image position error/i.test(s.getAttribute('aria-label') || ''); })[0];
  if (strip) strip.__ch = 1;
  $$('svg.chart').forEach(enhance);
  if (strip && !strip.__strip) { strip.__strip = 1; buildStrip(strip); }
}
function boot() { try { run(); } catch (e) { if (window.console) console.error('charts.js', e); } }
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
window.addEventListener('hashchange', function () { setTimeout(boot, 30); });
window.Charts = { run: boot };
})();
