/* PCB layout deep-zoom viewer: tile pyramids per layer (pcb/tiles/<set>/<z>/<x>_<y>.png) on a canvas + vector net highlight from the routed geometry.
   Vanilla JS, no network: works from file://. Data: window.PCBVIEW (pcb/manifest.js). */
(function () {
'use strict';
var D = window.PCBVIEW, host = document.getElementById('pcbview');
if (!D || !host) return;
var G = D.geom, BX = D.bbox[0], BY = D.bbox[1], BS = D.bbox[2], N = D.N, TILE = D.tile, NL = D.levels, BASE = 'pcb/';
var LAYERS = [   /* id, label, tile set, copper index */
  { id: 'fcu', label: 'F.Cu', cu: 0 }, { id: 'in1', label: 'In1.Cu', cu: 1 }, { id: 'in2', label: 'In2.Cu', cu: 2 }, { id: 'bcu', label: 'B.Cu', cu: 3 },
  { id: 'fmask', label: 'F.Mask' }, { id: 'bmask', label: 'B.Mask' }, { id: 'fsilk', label: 'F.Silk' }, { id: 'bsilk', label: 'B.Silk' }, { id: 'drill', label: 'Drill' }];
var NETCOL = '#ffee3a';
function el(t, c, h) { var e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
var st = { side: 'top', mode: 'layers', on: { fcu: 1, in1: 1, in2: 1, bcu: 1, fmask: 0, bmask: 0, fsilk: 1, bsilk: 0, drill: 0 }, opacity: 0.8, net: -1, dim: 1, s: 1, ox: 0, oy: 0 };
var ready = false, W = 0, H = 0, dpr = 1, cv, ctx, raf = 0, hoverNet = -1;
var sets = {}; for (var k in D.sets) { sets[k] = D.sets[k].map(function (a) { var o = {}; a.forEach(function (x) { o[x] = 1; }); return o; }); }
var cache = {};

/* ---- net index */
var byNet = [], i;
for (i = 0; i < G.nets.length; i++) byNet.push({ t: [], v: [], p: [], len: 0 });
G.tracks.forEach(function (t) { var n = byNet[t[6]]; n.t.push(t); n.len += Math.hypot(t[3] - t[1] ? t[3] - t[1] : 0, 0) * 0 + Math.hypot(t[3] - t[1], t[4] - t[2]); });
G.vias.forEach(function (v) { byNet[v[4]].v.push(v); });
G.pads.forEach(function (p) { if (p[7] >= 0 && byNet[p[7]]) byNet[p[7]].p.push(p); });
var netIdx = []; G.nets.forEach(function (n, k2) { if (n && (byNet[k2].t.length || byNet[k2].p.length || byNet[k2].v.length)) netIdx.push(k2); });

/* ---- UI */
var bar = el('div', 'pv-bar'), main = el('div', 'pv-main'), stage = el('div', 'pv-stage'), side = el('div', 'pv-side');
cv = el('canvas', 'pv-cv'); stage.appendChild(cv); var readout = el('div', 'pv-read', ''), msg = el('div', 'pv-msg', 'loading tiles...'); stage.appendChild(readout); stage.appendChild(msg);
host.innerHTML = ''; host.className = 'pv'; host.appendChild(bar); main.appendChild(stage); main.appendChild(side); host.appendChild(main);
function grp(label) { var g = el('div', 'pv-grp'); if (label) g.appendChild(el('span', 'pv-lbl', label)); bar.appendChild(g); return g; }
function btn(g, t, title, fn) { var b = el('button', 'pv-b', t); b.type = 'button'; b.title = title || ''; b.onclick = fn; g.appendChild(b); return b; }
var g1 = grp('View');
var bTop = btn(g1, 'Top', 'View from the component / lens side', function () { setSide('top'); }), bBot = btn(g1, 'Bottom', 'View from below (mirrored, as if the board were flipped over)', function () { setSide('bottom'); });
var g2 = grp('Image');
var bLay = btn(g2, 'Layers', '4 copper layers in distinct colours, mask, silkscreen, drills', function () { setMode('layers'); }), bReal = btn(g2, 'Photo-like', 'Soldermask-covered copper, gold pads, silkscreen (the texture used in the Blender renders)', function () { setMode('real'); });
var g3 = grp('Layers'); var chks = {};
LAYERS.forEach(function (L) {
  var l = el('label', 'pv-chk'); var c = el('input'); c.type = 'checkbox'; c.checked = !!st.on[L.id]; c.onchange = function () { st.on[L.id] = c.checked ? 1 : 0; draw(); };
  var sw = el('span', 'pv-sw'); sw.style.background = L.id === 'drill' ? '#111' : 'rgb(' + D.colors[L.id].join(',') + ')'; l.appendChild(c); l.appendChild(sw); l.appendChild(document.createTextNode(L.label)); g3.appendChild(l); chks[L.id] = c;
});
var g4 = grp('Solo');
['fcu', 'in1', 'in2', 'bcu'].forEach(function (id) { btn(g4, LAYERS.filter(function (l) { return l.id === id; })[0].label, 'Show only this copper layer (+ silk of its side)', function () { solo(id); }); });
btn(g4, 'All', 'Show all four copper layers + top silk', function () { LAYERS.forEach(function (L) { st.on[L.id] = /^(fcu|in1|in2|bcu|fsilk)$/.test(L.id) ? 1 : 0; }); syncChks(); draw(); });
var g5 = grp('Opacity'); var os = el('input'); os.type = 'range'; os.min = 15; os.max = 100; os.value = 80; os.className = 'pv-range'; os.title = 'Copper layer opacity'; os.oninput = function () { st.opacity = os.value / 100; draw(); }; g5.appendChild(os);
var g6 = grp('Zoom'); btn(g6, '+', 'Zoom in', function () { zoomAt(W / 2, H / 2, 1.6); }); btn(g6, '-', 'Zoom out', function () { zoomAt(W / 2, H / 2, 1 / 1.6); }); btn(g6, 'Fit', 'Fit board', function () { fit(); }); btn(g6, '1:1', 'One image pixel per screen pixel (full resolution)', function () { var ppm = N / BS; zoomTo(W / 2, H / 2, ppm / dpr); });
function syncChks() { LAYERS.forEach(function (L) { chks[L.id].checked = !!st.on[L.id]; }); }
function solo(id) { LAYERS.forEach(function (L) { st.on[L.id] = L.id === id ? 1 : 0; }); st.on[id.charAt(0) === 'b' ? 'bsilk' : (id === 'fcu' ? 'fsilk' : 'bsilk')] = 0; if (id === 'fcu') st.on.fsilk = 1; if (id === 'bcu') st.on.bsilk = 1; if (st.mode !== 'layers') setMode('layers'); syncChks(); draw(); }

/* side panel: net search + info + downloads */
var sb = el('div', 'pv-sbox'); var inp = el('input'); inp.type = 'search'; inp.placeholder = 'net name, or ref.pin (U1.F2), e.g. MIPI, +3V3'; inp.autocomplete = 'off'; inp.setAttribute('aria-label', 'find net'); sb.appendChild(inp);
var res = el('div', 'pv-res'); res.hidden = true; sb.appendChild(res); side.appendChild(sb);
var dimL = el('label', 'pv-chk pv-dim'); var dimC = el('input'); dimC.type = 'checkbox'; dimC.checked = true; dimC.onchange = function () { st.dim = dimC.checked ? 1 : 0; draw(); }; dimL.appendChild(dimC); dimL.appendChild(document.createTextNode(' dim everything else when a net is selected')); side.appendChild(dimL);
var info = el('div', 'pv-info', '<p class="muted">Click a trace, via or pad to highlight its net. Scroll to zoom, drag to pan, double-click to zoom in. The highlight is drawn from the routed geometry (every track, via and pad of the .kicad_pcb).</p>'); side.appendChild(info);
var dl = el('div', 'pv-dl', ''); side.appendChild(dl);
function run() {
  var q = inp.value.trim().toLowerCase(); res.innerHTML = ''; if (!q) { res.hidden = true; return; }
  var items = [];
  netIdx.forEach(function (k2) { var n = G.nets[k2].toLowerCase(); var sc = n === q ? 0 : n.indexOf(q) === 0 ? 1 : n.indexOf(q) >= 0 ? 2 : -1; if (sc >= 0) items.push({ sc: sc, net: k2 }); });
  if (/[.]/.test(q) || /^[a-z]+\d+$/.test(q)) G.pads.forEach(function (p) { if (p[7] < 0 || !p[10]) return; var nm = (p[10] + '.' + p[11]).toLowerCase(); if (nm.indexOf(q) === 0) items.push({ sc: nm === q ? 0 : 3, net: p[7], pad: p }); });
  items.sort(function (a, b) { return a.sc - b.sc; }); items = items.slice(0, 24);
  items.forEach(function (it) {
    var r = el('div', 'pv-r', it.pad ? '<b>' + esc(it.pad[10] + '.' + it.pad[11]) + '</b><span>' + esc(G.nets[it.net]) + '</span>' : '<b>' + esc(G.nets[it.net]) + '</b><span>' + byNet[it.net].t.length + ' tracks, ' + byNet[it.net].v.length + ' vias, ' + byNet[it.net].p.length + ' pads</span>');
    r.onmousedown = function (ev) { ev.preventDefault(); selectNet(it.net, true); res.hidden = true; inp.value = ''; }; res.appendChild(r);
  });
  res.hidden = !items.length;
}
inp.addEventListener('input', run); inp.addEventListener('blur', function () { setTimeout(function () { res.hidden = true; }, 150); }); inp.addEventListener('focus', run);
inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { var f = res.firstChild; if (f) f.onmousedown({ preventDefault: function () { } }); } });

function netBox(k) {
  var n = byNet[k], x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  function add(x, y, r) { x0 = Math.min(x0, x - r); y0 = Math.min(y0, y - r); x1 = Math.max(x1, x + r); y1 = Math.max(y1, y + r); }
  n.t.forEach(function (t) { add(t[1], t[2], t[5]); add(t[3], t[4], t[5]); }); n.v.forEach(function (v) { add(v[0], v[1], v[2]); }); n.p.forEach(function (p) { add(p[0], p[1], Math.max(p[2], p[3]) / 2); });
  return x0 > 1e8 ? null : [x0, y0, x1, y1];
}
function selectNet(k, doFit) {
  st.net = k;
  if (k < 0) { info.innerHTML = '<p class="muted">No net selected. Click a trace, via or pad.</p>'; draw(); return; }
  var n = byNet[k], cu = [0, 0, 0, 0], lens = [0, 0, 0, 0]; n.t.forEach(function (t) { cu[t[0]]++; lens[t[0]] += Math.hypot(t[3] - t[1], t[4] - t[2]); });
  var pl = n.p.filter(function (p) { return p[10]; }).map(function (p) { return p[10] + '.' + p[11]; }), names = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'];
  info.innerHTML = '<div class="pv-net">' + esc(G.nets[k]) + '</div><table class="pv-kv"><tr><th>tracks</th><td>' + n.t.length + ' segments, ' + n.len.toFixed(1) + ' mm</td></tr>' +
    '<tr><th>per layer</th><td>' + names.map(function (nm, j) { return cu[j] ? nm + ': ' + cu[j] + ' (' + lens[j].toFixed(1) + ' mm)' : ''; }).filter(Boolean).join('<br>') + '</td></tr>' +
    '<tr><th>vias</th><td>' + n.v.length + '</td></tr><tr><th>pads</th><td>' + n.p.length + '</td></tr>' +
    '<tr><th>pins</th><td class="pv-pins">' + esc(pl.slice(0, 80).join(' ')) + (pl.length > 80 ? ' ...' : '') + '</td></tr></table><button class="pv-b" type="button" id="pv-clear">clear</button> <button class="pv-b" type="button" id="pv-zoomnet">zoom to net</button>';
  info.querySelector('#pv-clear').onclick = function () { selectNet(-1); }; info.querySelector('#pv-zoomnet').onclick = function () { fitNet(k); };
  if (doFit) fitNet(k); else draw();
}
function fitNet(k) {
  var b = netBox(k); if (!b) return; var w = Math.max(b[2] - b[0], 4), h = Math.max(b[3] - b[1], 4), s = Math.min(W / (w * 1.3), H / (h * 1.3)); s = Math.min(s, maxScale());
  var cx = (b[0] + b[2]) / 2 - BX, cy = (b[1] + b[3]) / 2 - BY; st.s = s; setCenter(cx, cy); draw();
}
function dlHtml() {
  var rows = [['pcb_top_' + N + '.png', 'Top-down, soldermask / copper / gold / silk (' + N + ' px)'], ['pcb_bottom_' + N + '.png', 'Bottom-down, as seen from below (' + N + ' px)'],
    ['pcb_layers_top_' + N + '.png', '4-layer colour layout, top view'], ['pcb_layers_bottom_' + N + '.png', '4-layer colour layout, bottom view (mirrored)']];
  dl.innerHTML = '<div class="pv-h">Full-resolution PNG (' + N + ' x ' + N + ', ' + (N / BS).toFixed(0) + ' px/mm)</div>' + rows.map(function (r) { return '<div><a href="' + BASE + r[0] + '" download>' + r[0] + '</a><br><span class="muted">' + r[1] + '</span></div>'; }).join('');
}
dlHtml();

/* ---- view transform: world mm (x right = kicad x - BX [mirrored for bottom], y down) -> screen */
function mir() { return st.side === 'bottom'; }
function setSide(s) { if (st.side === s) return; var cx = (W / 2 - st.ox) / st.s; var wx = mir() ? BS - 0 : 0; /* keep the centre point */
  var cxw = screenToWorld(W / 2, H / 2); st.side = s; setCenter(cxw[0], cxw[1]); upd(); draw(); }
function setMode(m) { st.mode = m; upd(); draw(); }
function upd() { bTop.classList.toggle('on', st.side === 'top'); bBot.classList.toggle('on', st.side === 'bottom'); bLay.classList.toggle('on', st.mode === 'layers'); bReal.classList.toggle('on', st.mode === 'real'); g3.classList.toggle('pv-off', st.mode === 'real'); g4.classList.toggle('pv-off', st.mode === 'real'); g5.classList.toggle('pv-off', st.mode === 'real'); }
/* canonical world coords: wx in 0..BS along the *image* x axis (kicad x). Screen x flips when mirrored. */
function w2s(wx, wy) { return [(mir() ? BS - wx : wx) * st.s + st.ox, wy * st.s + st.oy]; }
function screenToWorld(sx, sy) { var u = (sx - st.ox) / st.s; return [mir() ? BS - u : u, (sy - st.oy) / st.s]; }
function setCenter(wx, wy) { var u = mir() ? BS - wx : wx; st.ox = W / 2 - u * st.s; st.oy = H / 2 - wy * st.s; }
function minScale() { return Math.min(W, H) / BS * 0.5; }
function maxScale() { return (N / BS) * 2.2 / dpr; }
function fit() { st.s = Math.min(W, H) / (BS * 1.04); st.ox = (W - BS * st.s) / 2; st.oy = (H - BS * st.s) / 2; draw(); }
function zoomTo(sx, sy, s) { s = Math.max(minScale(), Math.min(maxScale(), s)); var w = screenToWorld(sx, sy); st.s = s; var u = mir() ? BS - w[0] : w[0]; st.ox = sx - u * s; st.oy = sy - w[1] * s; draw(); }
function zoomAt(sx, sy, f) { zoomTo(sx, sy, st.s * f); }

/* ---- tiles */
function tileImg(set, lv, tx, ty) {
  var key = set + '/' + lv + '/' + tx + '_' + ty, e = cache[key];
  if (e) return e.ok ? e.img : null;
  var img = new Image(); e = cache[key] = { img: img, ok: false }; img.onload = function () { e.ok = true; sched(); }; img.onerror = function () { e.err = true; };
  img.src = BASE + 'tiles/' + key + '.png'; return null;
}
function drawSet(set, alpha, cx0, cy0, cx1, cy1) {
  var ppmScreen = st.s * dpr, lv = NL - 1;
  while (lv > 0 && (N / BS) / Math.pow(2, NL - 1 - lv) > ppmScreen * 1.5) lv--;
  var ppm = (N / BS) / Math.pow(2, NL - 1 - lv), tmm = TILE / ppm, have = sets[set][lv], nt = Math.ceil(N / Math.pow(2, NL - 1 - lv) / TILE);
  var tx0 = Math.max(0, Math.floor(cx0 / tmm)), tx1 = Math.min(nt - 1, Math.floor(cx1 / tmm)), ty0 = Math.max(0, Math.floor(cy0 / tmm)), ty1 = Math.min(nt - 1, Math.floor(cy1 / tmm));
  ctx.globalAlpha = alpha;
  for (var ty = ty0; ty <= ty1; ty++) for (var tx = tx0; tx <= tx1; tx++) {
    if (!have[tx + '_' + ty]) continue;
    var img = tileImg(set, lv, tx, ty);
    if (img) { ctx.drawImage(img, tx * tmm, ty * tmm, tmm + 0.002, tmm + 0.002); continue; }
    for (var l2 = lv - 1, ax = tx >> 1, ay = ty >> 1, f = 2; l2 >= 0; l2--, ax >>= 1, ay >>= 1, f *= 2) {   /* fall back to a coarser tile that is already loaded */
      var e = cache[set + '/' + l2 + '/' + ax + '_' + ay]; if (e && e.ok) {
        var sz = TILE / f; ctx.drawImage(e.img, (tx % f) * sz, (ty % f) * sz, sz, sz, tx * tmm, ty * tmm, tmm, tmm); break; }
      if (!e && sets[set][l2][ax + '_' + ay]) tileImg(set, l2, ax, ay);
    }
  }
  ctx.globalAlpha = 1;
}
function sched() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; draw(true); }); }

/* ---- drawing */
function padPath(p) {
  var w = p[2], h = p[3], hw = w / 2, hh = h / 2; ctx.save(); ctx.translate(p[0] - BX, p[1] - BY); ctx.rotate(p[4] * Math.PI / 180); ctx.beginPath();
  if (p[5] === 'c' || (p[5] === 'o' && Math.abs(w - h) < 1e-3)) ctx.arc(0, 0, hw, 0, 6.2832);
  else if (p[5] === 'o') { var r = Math.min(hw, hh); if (hw >= hh) { ctx.moveTo(-hw + r, -hh); ctx.lineTo(hw - r, -hh); ctx.arc(hw - r, 0, r, -1.5708, 1.5708); ctx.lineTo(-hw + r, hh); ctx.arc(-hw + r, 0, r, 1.5708, 4.7124); } else { ctx.moveTo(-hw, -hh + r); ctx.arc(0, -hh + r, r, 3.1416, 6.2832); ctx.lineTo(hw, hh - r); ctx.arc(0, hh - r, r, 0, 3.1416); } ctx.closePath(); }
  else if (p[5] === 'q') { var rr = Math.min(hw, hh) * 0.25; ctx.moveTo(-hw + rr, -hh); ctx.arcTo(hw, -hh, hw, hh, rr); ctx.arcTo(hw, hh, -hw, hh, rr); ctx.arcTo(-hw, hh, -hw, -hh, rr); ctx.arcTo(-hw, -hh, hw, -hh, rr); ctx.closePath(); }
  else ctx.rect(-hw, -hh, w, h);
  ctx.restore();
}
function visCu() { var a = [0, 0, 0, 0]; if (st.mode === 'layers') LAYERS.forEach(function (L) { if (L.cu != null && st.on[L.id]) a[L.cu] = 1; }); else if (mir()) a[3] = 1; else a[0] = 1; return a; }
function draw() {
  if (!ready) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.setTransform(dpr * st.s * (mir() ? -1 : 1), 0, 0, dpr * st.s, dpr * (st.ox + (mir() ? BS * st.s : 0)), dpr * st.oy);   /* world mm in image orientation */
  var a = screenToWorld(0, 0), b = screenToWorld(W, H), x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  /* board body */
  var P = G.poly; ctx.beginPath(); P.forEach(function (q, j) { if (j) ctx.lineTo(q[0] - BX, q[1] - BY); else ctx.moveTo(q[0] - BX, q[1] - BY); }); ctx.closePath();
  ctx.fillStyle = st.mode === 'real' ? '#0d4a2a' : '#0e1613'; ctx.fill();
  if (st.mode === 'real') drawSet(mir() ? 'rbot' : 'rtop', 1, x0, y0, x1, y1);
  else {
    var order = ['bsilk', 'bmask', 'bcu', 'in2', 'in1', 'fcu', 'fmask', 'fsilk']; if (mir()) order = ['fsilk', 'fmask', 'fcu', 'in1', 'in2', 'bcu', 'bmask', 'bsilk'];
    order.forEach(function (id) { if (st.on[id]) drawSet(id, /cu|in/.test(id) ? st.opacity * (/^in/.test(id) ? 0.55 : 1) : 1, x0, y0, x1, y1); });
  }
  ctx.lineWidth = 0.1; ctx.strokeStyle = '#d8c25a'; ctx.beginPath(); P.forEach(function (q, j) { if (j) ctx.lineTo(q[0] - BX, q[1] - BY); else ctx.moveTo(q[0] - BX, q[1] - BY); }); ctx.closePath(); ctx.stroke();
  if (st.on.drill || st.mode === 'real' && false) {
    ctx.fillStyle = '#050506'; ctx.strokeStyle = '#8a8f98'; ctx.lineWidth = 0.03;
    G.vias.forEach(function (v) { ctx.beginPath(); ctx.arc(v[0] - BX, v[1] - BY, v[3] / 2, 0, 6.2832); ctx.fill(); ctx.stroke(); });
    G.pads.forEach(function (p) { if (p[8] > 0) { ctx.beginPath(); if (Math.abs(p[8] - p[9]) < 1e-3) ctx.arc(p[0] - BX, p[1] - BY, p[8] / 2, 0, 6.2832); else { ctx.save(); ctx.translate(p[0] - BX, p[1] - BY); ctx.rotate(p[4] * Math.PI / 180); ctx.scale(p[8] / 2, p[9] / 2); ctx.arc(0, 0, 1, 0, 6.2832); ctx.restore(); } ctx.fill(); ctx.stroke(); } });
  }
  /* net highlight (vector, from the routed geometry) */
  var hk = st.net >= 0 ? st.net : -1;
  if (hk >= 0) {
    var n = byNet[hk], vc = visCu();
    if (st.dim) { ctx.fillStyle = 'rgba(0,0,0,0.55)'; ctx.fillRect(-5, -5, BS + 10, BS + 10); }
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    var halo = Math.max(0.22, 5 / st.s);
    n.t.forEach(function (t) { if (!vc[t[0]]) return; ctx.strokeStyle = 'rgba(255,238,58,0.35)'; ctx.lineWidth = t[5] + halo; ctx.beginPath(); ctx.moveTo(t[1] - BX, t[2] - BY); ctx.lineTo(t[3] - BX, t[4] - BY); ctx.stroke(); });
    n.t.forEach(function (t) { if (!vc[t[0]]) return; ctx.strokeStyle = NETCOL; ctx.lineWidth = Math.max(t[5], 1.5 / st.s); ctx.beginPath(); ctx.moveTo(t[1] - BX, t[2] - BY); ctx.lineTo(t[3] - BX, t[4] - BY); ctx.stroke(); });
    ctx.fillStyle = NETCOL; ctx.strokeStyle = 'rgba(255,238,58,0.4)';
    n.p.forEach(function (p) { var vis = false; for (var j = 0; j < 4; j++) if ((p[6] >> j & 1) && vc[j]) vis = true; if (!vis) return; padPath(p); ctx.lineWidth = halo; ctx.stroke(); ctx.fill(); });
    n.v.forEach(function (v) { ctx.beginPath(); ctx.arc(v[0] - BX, v[1] - BY, v[2] / 2 + halo / 2, 0, 6.2832); ctx.fillStyle = 'rgba(255,238,58,0.4)'; ctx.fill(); ctx.beginPath(); ctx.arc(v[0] - BX, v[1] - BY, v[2] / 2, 0, 6.2832); ctx.fillStyle = NETCOL; ctx.fill(); ctx.beginPath(); ctx.arc(v[0] - BX, v[1] - BY, v[3] / 2, 0, 6.2832); ctx.fillStyle = '#050506'; ctx.fill(); });
  }
  updReadout();
}
var lastM = null;
function updReadout() {
  var t = 'zoom ' + (st.s * dpr).toFixed(1) + ' px/mm (image ' + (N / BS).toFixed(0) + ' px/mm)';
  if (lastM) { var w = screenToWorld(lastM[0], lastM[1]); t = 'x ' + (w[0] + BX).toFixed(2) + '  y ' + (w[1] + BY).toFixed(2) + ' mm &middot; ' + t; if (hoverNet >= 0) t = '<b>' + esc(G.nets[hoverNet]) + '</b> &middot; ' + t; }
  readout.innerHTML = t;
}

/* ---- hit test: topmost visible copper feature under the cursor */
function hit(sx, sy) {
  var w = screenToWorld(sx, sy), x = w[0] + BX, y = w[1] + BY, tol = 4 / st.s, vc = visCu(), best = -1, bd = 1e9, j;
  for (j = 0; j < G.pads.length; j++) {
    var p = G.pads[j]; if (p[7] < 0) continue; var ok = false; for (var l = 0; l < 4; l++) if ((p[6] >> l & 1) && vc[l]) ok = true; if (!ok) continue;
    var dx = x - p[0], dy = y - p[1], r = p[4] * Math.PI / 180, lx = dx * Math.cos(r) + dy * Math.sin(r), ly = -dx * Math.sin(r) + dy * Math.cos(r);
    if (Math.abs(lx) <= p[2] / 2 + tol * 0.3 && Math.abs(ly) <= p[3] / 2 + tol * 0.3) { return p[7]; }
  }
  for (j = 0; j < G.vias.length; j++) { var v = G.vias[j]; var d = Math.hypot(x - v[0], y - v[1]); if (d <= v[2] / 2 + tol * 0.3 && v[4] >= 0) return v[4]; }
  for (j = 0; j < G.tracks.length; j++) {
    var t = G.tracks[j]; if (!vc[t[0]]) continue; var ax = t[1], ay = t[2], bx = t[3], by = t[4], vx = bx - ax, vy = by - ay, L2 = vx * vx + vy * vy, u = L2 ? Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) : 0;
    var d2 = Math.hypot(x - (ax + u * vx), y - (ay + u * vy)) - t[5] / 2; if (d2 <= tol && d2 < bd) { bd = d2; best = t[6]; }
  }
  return best;
}

/* ---- input */
var ptrs = {}, drag = null, moved = 0;
cv.addEventListener('pointerdown', function (e) { cv.setPointerCapture(e.pointerId); var r = cv.getBoundingClientRect(); ptrs[e.pointerId] = [e.clientX - r.left, e.clientY - r.top]; moved = 0; drag = { x: e.clientX, y: e.clientY, ox: st.ox, oy: st.oy, n: Object.keys(ptrs).length, d0: pinchDist(), s0: st.s }; cv.classList.add('grab'); });
function pinchDist() { var k = Object.keys(ptrs); if (k.length < 2) return 0; var a = ptrs[k[0]], b = ptrs[k[1]]; return Math.hypot(a[0] - b[0], a[1] - b[1]); }
cv.addEventListener('pointermove', function (e) {
  var r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top; lastM = [px, py];
  if (ptrs[e.pointerId]) {
    ptrs[e.pointerId] = [px, py]; var n = Object.keys(ptrs).length;
    if (n >= 2 && drag.d0) { var d = pinchDist(); if (d) { var k = Object.keys(ptrs), a = ptrs[k[0]], b = ptrs[k[1]]; zoomTo((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, drag.s0 * d / drag.d0); moved = 9; } }
    else if (drag && n === 1) { var dx = e.clientX - drag.x, dy = e.clientY - drag.y; moved = Math.max(moved, Math.abs(dx) + Math.abs(dy)); st.ox = drag.ox + dx; st.oy = drag.oy + dy; draw(); }
  } else {
    var h = hit(px, py); if (h !== hoverNet) { hoverNet = h; cv.style.cursor = h >= 0 ? 'pointer' : 'grab'; } updReadout();
  }
});
function up(e) { if (ptrs[e.pointerId]) { delete ptrs[e.pointerId]; if (!Object.keys(ptrs).length) { cv.classList.remove('grab'); if (moved < 4 && e.type === 'pointerup') { var r = cv.getBoundingClientRect(); var h = hit(e.clientX - r.left, e.clientY - r.top); selectNet(h >= 0 && h !== st.net ? h : -1); } drag = null; } else drag = { x: e.clientX, y: e.clientY, ox: st.ox, oy: st.oy, n: 1, d0: 0, s0: st.s }; } }
cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
cv.addEventListener('wheel', function (e) { e.preventDefault(); var r = cv.getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0016))); }, { passive: false });
cv.addEventListener('dblclick', function (e) { var r = cv.getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, 2); });
cv.addEventListener('pointerleave', function () { lastM = null; hoverNet = -1; updReadout(); });

function resize() {
  var r = stage.getBoundingClientRect(); if (r.width < 10 || r.height < 10) return false;
  var first = !ready; dpr = Math.min(window.devicePixelRatio || 1, 2); W = r.width; H = r.height; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
  ctx = cv.getContext('2d'); ready = true; if (first) { fit(); msg.hidden = true; } else draw(); return true;
}
upd();
if (window.ResizeObserver) new ResizeObserver(function () { resize(); }).observe(stage); else { window.addEventListener('resize', resize); setTimeout(resize, 200); }
window.__pcbview = { st: st, select: selectNet, fit: fit, byNet: byNet, nets: G.nets, setMode: setMode, setSide: setSide, zoomTo: zoomTo, draw: draw };
})();
