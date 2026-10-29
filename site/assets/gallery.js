/* Test-image gallery + frame viewer: smooth zoom/pan, overlays with legend, tag tooltips, A/B comparison (flip / wipe / side by side)
   against the pipeline stage images when they exist, keyboard navigation, URL state (#/gallery/<name>?o=...&a=...&b=...&m=...).
   Replaces the legacy initGallery()/openImg() of app.js (app.js calls Gallery.init()). Vanilla JS, works from file://. */
(function () {
'use strict';
var W0 = 1280, H0 = 800;      /* logical image size: all ground-truth / detection coordinates live in this space */
var $ = function (s, r) { return (r || document).querySelector(s); };
function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { } return null; }
function f(x, p) { return x == null ? '-' : Number(x).toFixed(p); }
function colorVar(n, d) { var v = getComputedStyle(document.documentElement).getPropertyValue(n).trim(); return v || d; }

var G = null, inited = false, list = [], cur = -1, modal, S = { ov: { gt: 1, chip: 1, invis: 0, ids: 1, err: 0, miss: 1, extra: 1 }, gain: 12, mode: 'single', A: 'frame', B: 'thr' };
try { var sv = JSON.parse(store('gv') || 'null'); if (sv) { S.ov = Object.assign(S.ov, sv.ov || {}); S.gain = sv.gain || S.gain; } } catch (e) { }
var STAGES = [['frame', 'Frame (JPEG, as shown above)'], ['thr', 'Binarised (threshold)'], ['desp', 'Despeckled'], ['ccl', 'CCL labels']];
var COL = { gt: '#3ddc84', chip: '#4aa3ff', invis: '#a0a0a0', miss: '#ff5252', extra: '#e45bff', err: '#ffb02e' };
var view = { x: 0, y: 0, s: 1 }, target = { x: 0, y: 0, s: 1 }, anim = 0, panes = [], stage, hov = null, selTag = null, avail = {}, probing = {};

function save() { store('gv', JSON.stringify({ ov: S.ov, gain: S.gain })); }
function stageUrl(name, st) { return st === 'frame' ? 'frames/' + name + '.jpg' : 'simout/pipe/' + name + '_' + st + '.png'; }

/* ------------------------------------------------------------------ grid */
function init() {
  if (!window.GALLERY) return;
  if (!inited) { inited = true; G = window.GALLERY; setupGrid(); setupModal(); window.addEventListener('hashchange', function () { if (!/^#\/gallery/.test(location.hash) && modal && !modal.hidden) hideModal(); }); }
  syncFromHash();
}
function sortKey(a, b) {
  var s = $('#g-sort').value;
  if (s === 'name') return a.name < b.name ? -1 : 1;
  if (s === 'err') return ((b.pose && b.pose.t_mm) || 0) - ((a.pose && a.pose.t_mm) || 0);
  if (s === 'miss') return (b.vis - b.found) - (a.vis - a.found);
  if (s === 'cerr') return maxErr(b) - maxErr(a);
  return a.cat < b.cat ? -1 : a.cat > b.cat ? 1 : (a.name < b.name ? -1 : 1);
}
function maxErr(i) { var m = 0; for (var k in i.tags) { var e = i.tags[k].err; if (e != null && e > m) m = e; } return m; }
function setupGrid() {
  var grid = $('#g-grid'), sort = $('#g-sort');
  if (!$('#g-sort option[value="cerr"]')) { var o = el('option', null, 'worst corner error (desc)'); o.value = 'cerr'; sort.appendChild(o); }
  if (!$('#g-show')) {
    var sel = el('select'); sel.id = 'g-show'; sel.title = 'show only...';
    [['', 'all images'], ['miss', 'with missed tags'], ['false', 'with false / unseen detections'], ['nopose', 'no pose solved'], ['ok', 'every visible tag found']].forEach(function (p) { var o = el('option', null, p[1]); o.value = p[0]; sel.appendChild(o); });
    $('#g-count').parentNode.insertBefore(sel, $('#g-count'));
  }
  function draw() {
    var q = $('#g-search').value.trim().toLowerCase(), c = $('#g-cat').value, sh = $('#g-show').value;
    list = G.images.filter(function (i) {
      if (q && i.name.toLowerCase().indexOf(q) < 0 && i.cat.toLowerCase().indexOf(q) < 0) return false;
      if (c && i.cat !== c) return false;
      if (sh === 'miss' && i.vis - i.found <= 0) return false; if (sh === 'false' && !(i.false || i.unseen)) return false;
      if (sh === 'nopose' && i.pose) return false; if (sh === 'ok' && (i.vis - i.found > 0 || !i.vis)) return false;
      return true;
    }).sort(sortKey);
    $('#g-count').textContent = list.length + ' of ' + G.images.length + ' images';
    grid.innerHTML = list.map(function (i, k) {
      var miss = i.vis - i.found;
      return '<div class="gitem" data-k="' + k + '" tabindex="0" role="button" aria-label="open ' + esc(i.name) + '"><img loading="lazy" src="thumbs/' + esc(i.name) + '.jpg" alt="' + esc(i.name) + '"><div><b>' + esc(i.name) + '</b> <span class="muted">' + esc(i.cat) + '</span><br>' +
        i.found + '/' + i.vis + ' tags <span class="' + (miss > 0 ? 'bad' : 'good') + '">' + (miss > 0 ? '(' + miss + ' missed)' : 'ok') + '</span>' + (i.false || i.unseen ? ' <span class="bad">+' + (i.false + i.unseen) + ' extra</span>' : '') + '<br>' +
        (i.pose ? 'pos err ' + i.pose.t_mm.toFixed(1) + ' mm' : 'no pose') + '</div></div>';
    }).join('');
  }
  grid.addEventListener('click', function (e) { var it = e.target.closest('.gitem'); if (it) openIdx(+it.getAttribute('data-k')); });
  grid.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { var it = e.target.closest('.gitem'); if (it) { e.preventDefault(); openIdx(+it.getAttribute('data-k')); } } });
  ['g-search', 'g-cat', 'g-sort', 'g-show'].forEach(function (id) { $('#' + id).addEventListener('input', function () { draw(); }); });
  draw(); S.redrawGrid = draw;
}

/* ------------------------------------------------------------------ modal DOM */
function setupModal() {
  modal = $('#g-modal');
  modal.innerHTML = '<div class="mbox gv-box"><div class="mhead"><b id="m-title"></b><span class="muted" id="m-sub"></span><span class="grow"></span>' +
    '<button id="m-prev" title="previous image (left arrow / [)">&larr;</button><span class="muted" id="m-pos"></span><button id="m-next" title="next image (right arrow / ])">&rarr;</button>' +
    '<button id="m-close" title="close (Esc)">close</button></div>' +
    '<div class="gv-bar"><div class="gv-grp"><span class="v3-lbl">Zoom</span><button id="gv-zo" title="zoom out (-)">&minus;</button><span id="gv-zv" class="gv-zv">100%</span><button id="gv-zi" title="zoom in (+)">+</button><button id="gv-fit" title="fit to window (0 / double-click)">fit</button><button id="gv-1" title="1:1 source pixels (1)">1:1</button></div>' +
    '<div class="gv-grp"><span class="v3-lbl">Compare</span><select id="gv-mode" title="comparison mode"><option value="single">single</option><option value="flip">flip A/B</option><option value="wipe">wipe A|B</option><option value="side">side by side</option></select>' +
    '<label class="gv-lab">A <select id="gv-A"></select></label><label class="gv-lab gv-bsel">B <select id="gv-B"></select></label><button id="gv-flip" title="swap shown layer in flip mode (F / hold Space)" hidden>flip</button></div></div>' +
    '<div class="gv-main"><div><div class="gv-stage" id="gv-stage" tabindex="0"></div>' +
    '<div class="gv-legend" id="gv-legend"></div>' +
    '<div class="v3-hint gv-hint"><b>Wheel / pinch</b> zoom &middot; <b>drag</b> pan &middot; <b>double-click</b> zoom in / fit &middot; <b>hover</b> a tag for details &middot; <b>click</b> a tag to zoom to it &middot; keys: <kbd>&larr;</kbd><kbd>&rarr;</kbd> image, <kbd>+</kbd><kbd>-</kbd><kbd>0</kbd><kbd>1</kbd> zoom, <kbd>G</kbd> ground truth, <kbd>C</kbd> chip, <kbd>E</kbd> error vectors, <kbd>T</kbd> ids, <kbd>F</kbd> flip A/B, <kbd>Esc</kbd> close</div></div>' +
    '<div class="minfo" id="m-info"></div></div></div>';
  stage = $('#gv-stage');
  var selA = $('#gv-A'), selB = $('#gv-B');
  STAGES.forEach(function (s) { [selA, selB].forEach(function (sel) { var o = el('option', null, s[1]); o.value = s[0]; sel.appendChild(o); }); });
  $('#m-close').onclick = closeModal;
  $('#m-prev').onclick = function () { step(-1); }; $('#m-next').onclick = function () { step(1); };
  $('#gv-zi').onclick = function () { zoomBy(1.6); }; $('#gv-zo').onclick = function () { zoomBy(1 / 1.6); };
  $('#gv-fit').onclick = function () { fit(true); }; $('#gv-1').onclick = function () { zoomTo(1, true); };
  $('#gv-mode').onchange = function () { S.mode = this.value; buildPanes(); updateUrl(); };
  selA.onchange = function () { S.A = this.value; loadLayers(); updateUrl(); }; selB.onchange = function () { S.B = this.value; loadLayers(); updateUrl(); };
  $('#gv-flip').onclick = function () { flipLayer(); };
  modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(); });
  buildLegend();
  document.addEventListener('keydown', keydown, true);
  window.addEventListener('resize', function () { if (!modal.hidden) { layout(); } });
  if (window.ResizeObserver) new ResizeObserver(function () { if (!modal.hidden) layout(); }).observe(stage);
}
function buildLegend() {
  var lg = $('#gv-legend'), items = [
    ['gt', 'ground truth quad', COL.gt, 'G'], ['chip', 'chip detection', COL.chip, 'C'], ['miss', 'missed (GT visible, not detected)', COL.miss, ''], ['extra', 'detection of a tag GT says is not visible', COL.extra, ''],
    ['invis', 'GT not visible', COL.invis, ''], ['err', 'corner error vectors', COL.err, 'E'], ['ids', 'tag ids', 'var(--fg)', 'T']];
  lg.innerHTML = items.map(function (it) { return '<label class="chk" title="' + it[1] + (it[3] ? ' (key ' + it[3] + ')' : '') + '"><input type="checkbox" data-o="' + it[0] + '"><i class="gv-sw" style="background:' + it[2] + '"></i>' + it[1] + '</label>'; }).join('') +
    '<label class="chk" title="the error vectors are drawn this many times longer than the real error">gain &times;<input type="range" id="gv-gain" min="1" max="60" value="' + S.gain + '"><b id="gv-gv">' + S.gain + '</b></label>' +
    '<span class="muted gv-note">Reference (pupil-apriltags) per-tag corner quads are not stored in the result files, so only its tag count, pose error and corner-error statistics are shown (table at the right).</span>';
  [].forEach.call(lg.querySelectorAll('input[data-o]'), function (c) { c.checked = !!S.ov[c.getAttribute('data-o')]; c.onchange = function () { S.ov[c.getAttribute('data-o')] = c.checked ? 1 : 0; save(); drawAll(); updateUrl(); }; });
  $('#gv-gain').oninput = function () { S.gain = +this.value; $('#gv-gv').textContent = S.gain; save(); if (!S.ov.err) { S.ov.err = 1; syncLegend(); } drawAll(); };
}
function syncLegend() { [].forEach.call(document.querySelectorAll('#gv-legend input[data-o]'), function (c) { c.checked = !!S.ov[c.getAttribute('data-o')]; }); }

/* ------------------------------------------------------------------ open / close / url */
function syncFromHash() {
  var m = location.hash.match(/^#\/gallery\/([^?]+)(?:\?(.*))?/), mi = location.hash.match(/^#\/gallery\?(?:.*&)?img=([^&]+)/);
  if (!m && mi) m = [0, mi[1], ''];     /* deep links of the command palette: #/gallery?img=<name> */
  var mq = location.hash.match(/^#\/gallery\?(.*)$/);
  if (mq && !m) {      /* filter deep links: #/gallery?cat=dist&q=foo&sort=err */
    var fq = {}; mq[1].split('&').forEach(function (x) { var s = x.split('='); if (s[0]) fq[s[0]] = decodeURIComponent(s[1] || ''); });
    if (fq.cat != null || fq.q != null || fq.sort) { $('#g-cat').value = fq.cat || ''; $('#g-search').value = fq.q || ''; if (fq.sort && $('#g-sort option[value="' + fq.sort + '"]')) $('#g-sort').value = fq.sort; S.redrawGrid(); }
  }
  if (!m) { if (modal && !modal.hidden && /^#\/gallery\/?(\?|$)/.test(location.hash) || (modal && !modal.hidden && !/^#\/gallery/.test(location.hash))) hideModal(); return; }
  var name = decodeURIComponent(m[1]), q = {}; (m[2] || '').split('&').forEach(function (x) { if (x) { var s = x.split('='); q[s[0]] = decodeURIComponent(s[1] || ''); } });
  if (q.o != null) { var on = q.o.split('.'); Object.keys(S.ov).forEach(function (k) { S.ov[k] = on.indexOf(k) >= 0 ? 1 : 0; }); syncLegend(); }
  if (q.a) S.A = q.a; if (q.b) S.B = q.b; if (q.m) S.mode = q.m;
  var idx = -1; list.forEach(function (i, k) { if (i.name === name) idx = k; });
  if (idx < 0) { /* filtered out: reset filters */ $('#g-search').value = ''; $('#g-cat').value = ''; $('#g-show').value = ''; S.redrawGrid(); list.forEach(function (i, k) { if (i.name === name) idx = k; }); }
  if (idx >= 0) openIdx(idx, true, q);
}
function updateUrl() {
  if (cur < 0 || modal.hidden) return;
  var on = Object.keys(S.ov).filter(function (k) { return S.ov[k]; }).join('.');
  try { history.replaceState(null, '', location.pathname + location.search + '#/gallery/' + encodeURIComponent(list[cur].name) + '?o=' + on + '&a=' + S.A + '&b=' + S.B + '&m=' + S.mode); } catch (e) { }
}
function closeModal() {
  hideModal(); try { history.replaceState(null, '', location.pathname + location.search + '#/gallery'); } catch (e) { }
}
function hideModal() { modal.hidden = true; document.body.style.overflow = ''; cancelAnim(); }
function step(d) { if (!list.length) return; openIdx((cur + d + list.length) % list.length); }

function openIdx(k, fromUrl, q) {
  cur = k; var i = list[k]; modal.hidden = false; document.body.style.overflow = 'hidden';
  $('#m-title').textContent = i.name; $('#m-sub').textContent = '[' + i.cat + ']'; $('#m-pos').textContent = (k + 1) + ' / ' + list.length;
  $('#gv-mode').value = S.mode; $('#gv-A').value = S.A; $('#gv-B').value = S.B; syncLegend();
  selTag = (q && q.tag) || null; hov = null;
  buildInfo(i); probeStages(i.name); buildPanes();
  /* prefetch neighbours so keyboard navigation feels instant */
  [1, -1].forEach(function (d) { var n = list[(k + d + list.length) % list.length]; if (n) new Image().src = stageUrl(n.name, 'frame'); });
  if (!fromUrl) updateUrl(); else updateUrl();
}

/* stage image availability (the pipeline visualiser writes simout/pipe/<frame>_{thr,desp,ccl}.png for some frames) */
function probeStages(name) {
  ['thr', 'desp', 'ccl'].forEach(function (s) {
    var key = name + '/' + s; if (avail[key] != null || probing[key]) return; probing[key] = 1;
    var im = new Image(); im.onload = function () { avail[key] = 1; delete probing[key]; if (list[cur] && list[cur].name === name) refreshStageSelects(); }; im.onerror = function () { avail[key] = 0; delete probing[key]; if (list[cur] && list[cur].name === name) refreshStageSelects(); }; im.src = stageUrl(name, s);
  });
  refreshStageSelects();
}
function hasStage(name, s) { return s === 'frame' || avail[name + '/' + s] === 1; }
function refreshStageSelects() {
  var name = list[cur].name, n = 0;
  ['gv-A', 'gv-B'].forEach(function (id) { var sel = $('#' + id); [].forEach.call(sel.options, function (o) { var ok = hasStage(name, o.value); o.disabled = !ok; o.textContent = STAGES.filter(function (s) { return s[0] === o.value; })[0][1] + (ok ? '' : ' (not available for this frame)'); }); });
  STAGES.forEach(function (s) { if (hasStage(name, s[0])) n++; });
  var pend = ['thr', 'desp', 'ccl'].some(function (s) { return probing[name + '/' + s]; });
  var cmp = $('#gv-mode'); [].forEach.call(cmp.options, function (o) { if (o.value !== 'single') o.disabled = n < 2; });
  if (!pend && (!hasStage(name, S.B) || S.B === S.A)) { var alt = STAGES.filter(function (s) { return s[0] !== S.A && hasStage(name, s[0]); })[0]; if (alt) { S.B = alt[0]; $('#gv-B').value = S.B; } }
  if (n < 2 && !pend && S.mode !== 'single') { S.mode = 'single'; cmp.value = 'single'; buildPanes(); }
  $('#gv-bsel') && 0; [].forEach.call(document.querySelectorAll('.gv-bsel'), function (e) { e.style.display = S.mode === 'single' ? 'none' : ''; });
  $('#gv-flip').hidden = S.mode !== 'flip' && S.mode !== 'wipe';
  if (!hasStage(name, S.A)) { S.A = 'frame'; $('#gv-A').value = 'frame'; }
  loadLayers();
}

/* ------------------------------------------------------------------ panes and layers */
function buildPanes() {
  stage.innerHTML = ''; panes = []; stage.className = 'gv-stage gv-m-' + S.mode;
  var n = S.mode === 'side' ? 2 : 1;
  for (var k = 0; k < n; k++) {
    var p = { el: el('div', 'gv-pane'), world: el('div', 'gv-world'), cv: el('canvas', 'gv-ov'), layers: [] };
    p.world.style.width = W0 + 'px'; p.world.style.height = H0 + 'px';
    var nl = (S.mode === 'flip' || S.mode === 'wipe') ? 2 : 1;
    for (var j = 0; j < nl; j++) { var im = el('img', 'gv-img'); im.draggable = false; im.alt = ''; im.style.width = W0 + 'px'; im.style.height = H0 + 'px'; p.world.appendChild(im); p.layers.push(im); }
    p.el.appendChild(p.world); p.el.appendChild(p.cv); stage.appendChild(p.el); panes.push(p); bindPane(p);
    if (n === 2) p.el.appendChild(el('div', 'gv-tag', k ? 'B: ' + labelOf(S.B) : 'A: ' + labelOf(S.A)));
  }
  if (S.mode === 'wipe') {
    var h = el('div', 'gv-wipe'); h.innerHTML = '<span></span>'; stage.appendChild(h); stage.wipe = h; stage.wipeX = 0.5; setWipe();
    h.addEventListener('pointerdown', function (e) { e.stopPropagation(); h.setPointerCapture(e.pointerId); h.classList.add('on'); });
    h.addEventListener('pointermove', function (e) { if (!h.classList.contains('on')) return; var r = stage.getBoundingClientRect(); stage.wipeX = Math.max(0.02, Math.min(0.98, (e.clientX - r.left) / r.width)); setWipe(); });
    h.addEventListener('pointerup', function () { h.classList.remove('on'); });
    stage.appendChild(el('div', 'gv-tag', 'A: ' + labelOf(S.A))); var tb = el('div', 'gv-tag gv-tagr', 'B: ' + labelOf(S.B)); stage.appendChild(tb);
  }
  stage.flipShowB = false; var tip = el('div', 'gv-tip'); tip.hidden = true; stage.appendChild(tip); stage.tip = tip;
  refreshStageSelects(); layout(true);
}
function labelOf(s) { return STAGES.filter(function (x) { return x[0] === s; })[0][1].replace(/ \(.*/, ''); }
function setWipe() { var x = stage.wipeX * 100; stage.wipe.style.left = x + '%'; if (panes[0] && panes[0].layers[1]) panes[0].layers[1].style.clipPath = 'inset(0 0 0 0)'; applyWipeClip(); }
function applyWipeClip() {
  if (S.mode !== 'wipe' || !panes[0]) return;
  /* B layer is clipped so that only the part right of the divider (in screen space) shows */
  var w = stage.clientWidth, xs = stage.wipeX * w, lx = (xs - view.x) / view.s;
  panes[0].layers[1].style.clipPath = 'polygon(' + lx + 'px 0, ' + W0 + 'px 0, ' + W0 + 'px ' + H0 + 'px, ' + lx + 'px ' + H0 + 'px)';
}
function loadLayers() {
  if (!panes.length || cur < 0) return; var n = list[cur].name;
  var srcs = (S.mode === 'side') ? [S.A, S.B] : (S.mode === 'single' ? [S.A] : [S.A, S.B]);
  if (S.mode === 'side') { panes[0].layers[0].src = stageUrl(n, S.A); panes[1].layers[0].src = stageUrl(n, S.B); }
  else panes[0].layers.forEach(function (im, j) { im.src = stageUrl(n, srcs[j] || S.A); });
  panes.forEach(function (p) { p.layers.forEach(function (im, j) { im.style.display = (S.mode === 'flip' && j === 1 && !stage.flipShowB) ? 'none' : ''; im.style.imageRendering = view.s > 3 ? 'pixelated' : 'auto'; }); });
  if (S.mode === 'flip' && stage.flipShowB) panes[0].layers[0].style.display = 'none';
  $('#gv-flip').hidden = !(S.mode === 'flip' || S.mode === 'wipe');
  [].forEach.call(document.querySelectorAll('.gv-bsel'), function (e) { e.style.display = S.mode === 'single' ? 'none' : ''; });
}
function flipLayer() { if (S.mode !== 'flip') return; stage.flipShowB = !stage.flipShowB; panes[0].layers[0].style.display = stage.flipShowB ? 'none' : ''; panes[0].layers[1].style.display = stage.flipShowB ? '' : 'none'; var t = stage.querySelector('.gv-tagflip'); if (!t) { t = el('div', 'gv-tag gv-tagflip'); stage.appendChild(t); } t.textContent = (stage.flipShowB ? 'B: ' + labelOf(S.B) : 'A: ' + labelOf(S.A)); }

/* ------------------------------------------------------------------ view transform */
function paneSize() { var p = panes[0] && panes[0].el; if (p && p.clientWidth) return { w: p.clientWidth, h: p.clientHeight }; return { w: stage.clientWidth, h: stage.clientHeight }; }
function fitView() { var p = paneSize(), s = Math.min(p.w / W0, p.h / H0) * 0.98; return { s: s, x: (p.w - W0 * s) / 2, y: (p.h - H0 * s) / 2 }; }
function layout(first) {
  var wide = stage.clientWidth || 600; var stk = S.mode === 'side' && window.innerWidth <= 860; stage.style.height = Math.round(stk ? Math.max(380, wide / 1.6 * 2) : Math.max(260, Math.min(window.innerHeight * 0.68, wide / (S.mode === 'side' ? 1.25 : 1.6)))) + 'px';
  var dpr = window.devicePixelRatio || 1;
  panes.forEach(function (p) { p.cv.width = Math.round(p.el.clientWidth * dpr); p.cv.height = Math.round(p.el.clientHeight * dpr); p.cv.style.width = p.el.clientWidth + 'px'; p.cv.style.height = p.el.clientHeight + 'px'; });
  if (first) { var fv = fitView(); view.x = target.x = fv.x; view.y = target.y = fv.y; view.s = target.s = fv.s; if (selTag && list[cur].tags[selTag]) focusTag(selTag, false); }
  else clampTarget();
  applyView();
}
function fit(animated) { var fv = fitView(); setTarget(fv.x, fv.y, fv.s, !animated); }
function minScale() { return fitView().s * 0.7; }
function clampTarget() {
  var p = paneSize(), s = Math.max(minScale(), Math.min(40, target.s)); target.s = s;
  var w = W0 * s, h = H0 * s, m = 60;
  target.x = Math.min(p.w - m, Math.max(m - w, target.x)); target.y = Math.min(p.h - m, Math.max(m - h, target.y));
}
function setTarget(x, y, s, instant) { target.x = x; target.y = y; target.s = s; clampTarget(); if (instant) { view.x = target.x; view.y = target.y; view.s = target.s; applyView(); } else kick(); }
function kick() { if (!anim) anim = requestAnimationFrame(tick); }
function cancelAnim() { if (anim) cancelAnimationFrame(anim); anim = 0; }
function tick() {
  anim = 0; var k = 0.28, dx = target.x - view.x, dy = target.y - view.y, ds = target.s / view.s;
  view.x += dx * k; view.y += dy * k; view.s *= Math.pow(ds, k);
  var done = Math.abs(dx) < 0.3 && Math.abs(dy) < 0.3 && Math.abs(ds - 1) < 0.002;
  if (done) { view.x = target.x; view.y = target.y; view.s = target.s; }
  applyView(); if (!done) kick();
}
function applyView() {
  var t = 'translate(' + view.x + 'px,' + view.y + 'px) scale(' + view.s + ')', px = view.s > 3 ? 'pixelated' : 'auto';
  panes.forEach(function (p) { p.world.style.transform = t; p.layers.forEach(function (im) { im.style.imageRendering = px; }); });
  var z = $('#gv-zv'); if (z) z.textContent = Math.round(view.s / (1) * 100) + '%';
  applyWipeClip(); drawAll();
}
function zoomAt(px, py, factor, instant) {   /* zoom about a point given in pane coordinates; works on the *target* so wheel bursts compose */
  var s0 = target.s, s1 = Math.max(minScale(), Math.min(40, s0 * factor)), r = s1 / s0;
  setTarget(px - (px - target.x) * r, py - (py - target.y) * r, s1, instant);
}
function zoomBy(f) { var p = paneSize(); zoomAt(p.w / 2, p.h / 2, f); }
function zoomTo(s, animated) { var p = paneSize(); zoomAt(p.w / 2, p.h / 2, s / target.s); }
function focusTag(id, animated) {
  var t = list[cur].tags[id], q = (t && (t.gt || t.chip)); if (!q) return; var p = paneSize(), xs = q.map(function (a) { return a[0]; }), ys = q.map(function (a) { return a[1]; });
  var x0 = Math.min.apply(0, xs), x1 = Math.max.apply(0, xs), y0 = Math.min.apply(0, ys), y1 = Math.max.apply(0, ys), s = Math.min(p.w / ((x1 - x0) * 2.6), p.h / ((y1 - y0) * 2.6), 12);
  setTarget(p.w / 2 - (x0 + x1) / 2 * s, p.h / 2 - (y0 + y1) / 2 * s, s, animated === false);
}

/* ------------------------------------------------------------------ pointer input */
function bindPane(p) {
  var ptrs = {}, pinch = null, moved = 0, downPt = null;
  function local(e) { var r = p.el.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  p.el.addEventListener('wheel', function (e) {
    e.preventDefault(); var l = local(e), d = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY; zoomAt(l.x, l.y, Math.exp(-d * 0.0016));
  }, { passive: false });
  p.el.addEventListener('pointerdown', function (e) {
    if (e.button && e.pointerType === 'mouse' && e.button !== 0) return;
    p.el.setPointerCapture(e.pointerId); ptrs[e.pointerId] = local(e); moved = 0; downPt = local(e); p.el.classList.add('grab'); cancelAnim(); view.x = target.x = view.x; stage.focus({ preventScroll: true });
    view.x = target.x; view.y = target.y; view.s = target.s;
    var ids = Object.keys(ptrs); if (ids.length === 2) { var a = ptrs[ids[0]], b = ptrs[ids[1]]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: view.s }; }
    hideTip();
  });
  p.el.addEventListener('pointermove', function (e) {
    var l = local(e);
    if (ptrs[e.pointerId]) {
      var prev = ptrs[e.pointerId], ids = Object.keys(ptrs); ptrs[e.pointerId] = l;
      if (ids.length >= 2 && pinch) {
        var a = ptrs[ids[0]], b = ptrs[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y) || 1, cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2, ns = Math.max(minScale(), Math.min(40, pinch.s * d / pinch.d)), r = ns / view.s;
        view.x = cx - (cx - view.x) * r + (e.movementX || 0) * 0; view.y = cy - (cy - view.y) * r; view.s = ns; target.x = view.x; target.y = view.y; target.s = ns; applyView();
      } else {
        moved += Math.abs(l.x - prev.x) + Math.abs(l.y - prev.y);
        view.x += l.x - prev.x; view.y += l.y - prev.y; target.x = view.x; target.y = view.y; clampTarget(); view.x = target.x; view.y = target.y; applyView();
      }
    } else if (e.pointerType !== 'touch') hover(l, e, p);
  });
  function up(e) {
    if (!ptrs[e.pointerId]) return; var l = local(e); delete ptrs[e.pointerId]; pinch = null; p.el.classList.remove('grab');
    if (moved < 5 && Object.keys(ptrs).length === 0) { var t = tagAt(l); if (t) { selTag = t; focusTag(t, true); markRow(t); updateUrlTag(); } }
  }
  p.el.addEventListener('pointerup', up); p.el.addEventListener('pointercancel', up);
  p.el.addEventListener('pointerleave', function () { if (hov) { hov = null; drawAll(); } hideTip(); });
  p.el.addEventListener('dblclick', function (e) {
    e.preventDefault(); var l = local(e), fs = fitView().s;
    if (view.s > fs * 1.6) fit(true); else zoomAt(l.x, l.y, Math.max(3.5 / target.s, 1.5));
  });
}
function updateUrlTag() { }

/* hit testing */
function inPoly(q, x, y) { var c = false; for (var i = 0, j = q.length - 1; i < q.length; j = i++) if (((q[i][1] > y) !== (q[j][1] > y)) && (x < (q[j][0] - q[i][0]) * (y - q[i][1]) / (q[j][1] - q[i][1]) + q[i][0])) c = !c; return c; }
function tagAt(l) {
  var x = (l.x - view.x) / view.s, y = (l.y - view.y) / view.s, best = null, bd = 1e9, tags = list[cur].tags;
  for (var id in tags) { var t = tags[id], hit = false; [t.gt, t.chip].forEach(function (q) { if (q && inPoly(q, x, y)) hit = true; });
    if (hit) { var q = t.gt || t.chip, cx = (q[0][0] + q[2][0]) / 2, cy = (q[0][1] + q[2][1]) / 2, d = Math.hypot(cx - x, cy - y); if (d < bd) { bd = d; best = id; } } }
  return best;
}
function hover(l, e, p) {
  var id = tagAt(l); if (id !== hov) { hov = id; drawAll(); markRow(id, true); }
  if (!id) { hideTip(); p.el.style.cursor = ''; return; }
  p.el.style.cursor = 'pointer'; var t = list[cur].tags[id], tip = stage.tip, r = stage.getBoundingClientRect();
  tip.hidden = false; tip.innerHTML = tipHtml(id, t);
  var x = e.clientX - r.left + 14, y = e.clientY - r.top + 14; if (x > r.width - 230) x -= 250; if (y > r.height - 120) y -= 130; tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
}
function hideTip() { if (stage && stage.tip) stage.tip.hidden = true; }
function cornerErrs(t) { if (!t.gt || !t.chip) return null; return t.gt.map(function (g, k) { return Math.hypot(t.chip[k][0] - g[0], t.chip[k][1] - g[1]); }); }
function status(t) {
  if (t.chip && t.vis) return ['found', 'ok']; if (t.chip) return ['detected, but GT says not visible', 'bad']; if (t.vis) return ['MISSED by the chip', 'bad']; return ['not visible in this frame', 'muted'];
}
function tipHtml(id, t) {
  var st = status(t), ce = cornerErrs(t), h = '<b>tag ' + esc(id) + '</b> <span class="' + (st[1] === 'ok' ? 'tag-ok' : st[1] === 'bad' ? 'tag-miss' : 'muted') + '">' + st[0] + '</span><br>';
  if (t.px != null) h += 'GT width ' + t.px + ' px<br>';
  if (ce) h += 'max corner error <b>' + t.err + ' px</b><br>per corner ' + ce.map(function (x) { return x.toFixed(2); }).join(' / ') + '<br>mean ' + (ce.reduce(function (a, b) { return a + b; }, 0) / 4).toFixed(2) + ' px<br>';
  if (t.ham != null) h += 'hamming distance ' + t.ham + '<br>';
  var ref = list[cur].ref; if (ref && ref.rms_px != null) h += '<span class="muted">reference frame rms ' + ref.rms_px + ' px</span>';
  return h;
}

/* ------------------------------------------------------------------ overlay drawing */
function drawAll() { panes.forEach(drawPane); }
function drawPane(p) {
  if (cur < 0) return; var cv = p.cv, c = cv.getContext('2d'), dpr = window.devicePixelRatio || 1, i = list[cur], O = S.ov;
  c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, cv.width, cv.height); c.setTransform(dpr, 0, 0, dpr, 0, 0);
  var s = view.s, X = function (x) { return x * s + view.x; }, Y = function (y) { return y * s + view.y; };
  function poly(q, col, w, dash, fill) {
    c.beginPath(); q.forEach(function (a, k) { k ? c.lineTo(X(a[0]), Y(a[1])) : c.moveTo(X(a[0]), Y(a[1])); }); c.closePath();
    if (fill) { c.fillStyle = fill; c.fill(); } c.setLineDash(dash || []); c.strokeStyle = col; c.lineWidth = w; c.stroke(); c.setLineDash([]);
    c.fillStyle = col; c.beginPath(); c.arc(X(q[0][0]), Y(q[0][1]), Math.max(2, w + 1), 0, 7); c.fill();   /* corner 0 marker shows the winding start */
  }
  function label(txt, x, y, col) { c.font = 'bold 12px system-ui,sans-serif'; c.textBaseline = 'middle'; c.lineWidth = 3; c.strokeStyle = 'rgba(0,0,0,.75)'; c.strokeText(txt, x, y); c.fillStyle = col; c.fillText(txt, x, y); }
  Object.keys(i.tags).forEach(function (id) {
    var t = i.tags[id], hot = id === hov || id === selTag, w = hot ? 2.6 : 1.6, q = t.gt || t.chip, cx = (q[0][0] + q[2][0]) / 2, cy = (q[0][1] + q[2][1]) / 2, off = 0;
    var isMiss = t.vis && !t.chip, isExtra = t.chip && !t.vis;
    if (t.gt && t.vis && O.gt) poly(t.gt, COL.gt, w);
    if (t.gt && !t.vis && O.invis) poly(t.gt, COL.invis, w, [5, 4]);
    if (isMiss && O.miss) poly(t.gt, COL.miss, w + 0.6, [7, 4], 'rgba(255,82,82,.16)');
    if (t.chip && O.chip && !isExtra) poly(t.chip, COL.chip, w);
    if (isExtra && O.extra) poly(t.chip, COL.extra, w + 0.6, [3, 3], 'rgba(228,91,255,.14)');
    if (hot && t.chip) { poly(t.chip, '#ffffff', 1, [2, 3]); }
    if (O.err && t.gt && t.chip && t.vis) {
      var g = S.gain; c.strokeStyle = COL.err; c.fillStyle = COL.err; c.lineWidth = 1.6;
      t.gt.forEach(function (a, k) {
        var b = t.chip[k], dx = (b[0] - a[0]) * g, dy = (b[1] - a[1]) * g, x0 = X(a[0]), y0 = Y(a[1]), x1 = x0 + dx * s, y1 = y0 + dy * s, L = Math.hypot(x1 - x0, y1 - y0);
        c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
        if (L > 4) { var an = Math.atan2(y1 - y0, x1 - x0); c.beginPath(); c.moveTo(x1, y1); c.lineTo(x1 - 6 * Math.cos(an - 0.45), y1 - 6 * Math.sin(an - 0.45)); c.lineTo(x1 - 6 * Math.cos(an + 0.45), y1 - 6 * Math.sin(an + 0.45)); c.closePath(); c.fill(); }
        c.beginPath(); c.arc(x0, y0, 2, 0, 7); c.fill();
      });
    }
    if (O.ids) { var col = isMiss ? COL.miss : isExtra ? COL.extra : (t.vis ? COL.gt : COL.invis); if ((t.gt && t.vis) || t.chip || O.invis) label(id + (t.err != null && (hot || s > 2) ? '  ' + t.err + 'px' : ''), X(cx) - 6, Y(cy), col); }
  });
  /* scale bar: 50 source pixels */
  var bl = 50 * s; c.fillStyle = 'rgba(0,0,0,.55)'; c.fillRect(8, cv.clientHeight - 26, bl + 54, 18); c.fillStyle = '#fff'; c.fillRect(12, cv.clientHeight - 14, bl, 3); c.font = '11px system-ui,sans-serif'; c.textBaseline = 'middle'; c.fillText('50 px', 16 + bl, cv.clientHeight - 17);
}

/* ------------------------------------------------------------------ info panel */
function buildInfo(i) {
  var h = '<table><tr><th colspan=2>Ground truth camera pose (camera to world)</th></tr><tr><td>position (m)</td><td>' + i.gt_t.join(', ') + '</td></tr><tr><td>R_wc</td><td><code>' + i.gt_R.map(function (r) { return r.map(function (x) { return x.toFixed(3); }).join(' '); }).join('<br>') + '</code></td></tr>' +
    (i.light ? '<tr><td>light scale / shift</td><td>' + i.light.scale + ' / ' + i.light.shift + '</td></tr>' : '') + '</table>';
  h += '<table><tr><th></th><th>chip + MCU solver</th><th>reference</th></tr>' +
    '<tr><td>tags detected / visible</td><td>' + i.found + ' / ' + i.vis + '</td><td>' + (i.ref && i.ref.det != null ? i.ref.det : '-') + ' / ' + i.vis + '</td></tr>' +
    '<tr><td>false / unseen-tag detections</td><td>' + i.false + ' / ' + i.unseen + '</td><td>' + (i.ref && i.ref.false != null ? i.ref.false : '-') + '</td></tr>' +
    '<tr><td>position error (mm)</td><td>' + (i.pose ? f(i.pose.t_mm, 2) : '-') + '</td><td>' + (i.ref ? f(i.ref.t_mm, 2) : '-') + '</td></tr>' +
    '<tr><td>orientation error (deg)</td><td>' + (i.pose ? f(i.pose.rot_deg, 3) : '-') + '</td><td>' + (i.ref ? f(i.ref.rot_deg, 3) : '-') + '</td></tr>' +
    '<tr><td>reprojection rms (px)</td><td>' + (i.pose ? f(i.pose.rms_px, 2) + ' (' + i.pose.n + ' tags)' : '-') + '</td><td>' + (i.ref ? f(i.ref.rms_px, 2) : '-') + '</td></tr></table>';
  var rows = Object.keys(i.tags).sort(function (a, b) { return a - b; }).map(function (id) {
    var t = i.tags[id], st = status(t), cls = st[1] === 'ok' ? 'tag-ok' : st[1] === 'bad' ? 'tag-miss' : 'muted';
    return '<tr class="gv-row" data-id="' + id + '" tabindex="0" title="zoom to tag ' + id + '"><td>' + id + '</td><td>' + (t.px != null ? t.px : '-') + '</td><td><span class="' + cls + '">' + (st[0] === 'found' ? 'found' : st[0] === 'MISSED by the chip' ? 'missed' : st[0] === 'not visible in this frame' ? 'not visible' : 'detected, GT not visible') + '</span></td><td>' + (t.err != null ? t.err : '-') + '</td></tr>';
  }).join('');
  h += '<table id="gv-tags"><tr><th>tag</th><th>GT width px</th><th>chip</th><th>max corner err px</th></tr>' + rows + '</table><p class="muted gv-note">Click a row (or a tag in the image) to zoom to it.</p>';
  var s = i.stats; h += '<table><tr><th colspan=2>Chip status registers (simulation)</th></tr>' + Object.keys(s).map(function (k) { return '<tr><td>' + esc(k) + '</td><td><code>' + esc(s[k]) + '</code></td></tr>'; }).join('') + '<tr><td>sim wall time</td><td>' + i.sim_s + ' s</td></tr></table>';
  h += '<p><a href="frames/' + esc(i.name) + '.jpg" target="_blank">open 1024x640 frame</a></p>';
  var info = $('#m-info'); info.innerHTML = h;
  info.onclick = function (e) { var tr = e.target.closest('.gv-row'); if (tr) { selTag = tr.getAttribute('data-id'); focusTag(selTag, true); markRow(selTag); drawAll(); } };
  info.onmouseover = function (e) { var tr = e.target.closest('.gv-row'); var id = tr ? tr.getAttribute('data-id') : null; if (id !== hov) { hov = id; drawAll(); } };
  info.onmouseleave = function () { if (hov) { hov = null; drawAll(); } };
}
function markRow(id, scroll) {
  [].forEach.call(document.querySelectorAll('#gv-tags .gv-row'), function (tr) { var on = tr.getAttribute('data-id') === id; tr.classList.toggle('on', on); if (on && scroll && tr.scrollIntoView) { /* keep it simple: no scrolling of the page while hovering */ } });
}

/* ------------------------------------------------------------------ keyboard */
function keydown(e) {
  if (!modal || modal.hidden) return; if (e.ctrlKey || e.metaKey || e.altKey) return;
  var t = e.target; if (t && (t.tagName === 'INPUT' && t.type !== 'checkbox' && t.type !== 'range' || t.tagName === 'TEXTAREA')) return;
  var k = e.key, h = true;
  if (k === 'Escape') closeModal(); else if (k === 'ArrowLeft' || k === '[') step(-1); else if (k === 'ArrowRight' || k === ']') step(1);
  else if (k === '+' || k === '=') zoomBy(1.5); else if (k === '-' || k === '_') zoomBy(1 / 1.5); else if (k === '0') fit(true); else if (k === '1') zoomTo(1);
  else if (k === 'g' || k === 'G') tog('gt'); else if (k === 'c' || k === 'C') tog('chip'); else if (k === 'e' || k === 'E') tog('err'); else if (k === 't' || k === 'T') tog('ids');
  else if (k === 'f' || k === 'F' || k === ' ') { if (S.mode === 'flip') flipLayer(); else if (S.mode === 'single' && hasStage(list[cur].name, S.B) && S.B !== S.A) { S.mode = 'flip'; $('#gv-mode').value = 'flip'; buildPanes(); } else h = k !== ' '; }
  else h = false;
  if (h) { e.preventDefault(); e.stopImmediatePropagation(); }
}
function tog(k) { S.ov[k] = S.ov[k] ? 0 : 1; save(); syncLegend(); drawAll(); updateUrl(); }

window.Gallery = { S: S, init: init, open: function (name) { location.hash = '#/gallery/' + encodeURIComponent(name); } };
})();
