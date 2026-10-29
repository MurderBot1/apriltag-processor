/* bom2.js - BOM page v2: part cards with rendered thumbnails (default) or a compact table; replaces window.initBom from bom.js.
   Data: window.BOM (data/bom.js, from docs/bom/bom.json).  Thumbnails: assets/partthumbs.js.  Vanilla JS, no network. */
(function () {
'use strict';
var D = window.BOM; if (!D) return;
var PT = window.PartThumbs || { keyOf: function () { return null; }, inner: function () { return ''; }, host: function (l) { return String(l || ''); }, vendor: function () { return ''; } };
var started = false;

window.initBom = function () {
  if (started) return; started = true;
  var root = document.getElementById('page-bom');
  function $(i) { return document.getElementById('bom-' + i); }
  var S = { sort: 'cat', desc: false, group: true, view: 'cards', details: false, m: 1, closed: {} };
  try { var sv = JSON.parse(localStorage.getItem('bom2') || '{}'); if (sv.view) S.view = sv.view; if (sv.group === false) S.group = false; if (sv.details) S.details = true; } catch (e) {}
  function save() { try { localStorage.setItem('bom2', JSON.stringify({ view: S.view, group: S.group, details: S.details })); } catch (e) {} }

  var items = D.items.map(function (x, i) { x.i = i; return x; });
  var cats = []; items.forEach(function (x) { if (cats.indexOf(x.category) < 0) cats.push(x.category); });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function money(v) { return v == null ? '-' : '$' + v.toFixed(v < 1 ? 4 : 2); }
  function money2(v) { return v == null ? '-' : '$' + v.toFixed(v < 0.1 && v > 0 ? 3 : 2); }
  function mult(x) { return x.fixed ? 1 : S.m; }
  function ext(x) { return x.unit_price == null ? null : x.qty * x.unit_price * mult(x); }
  function isV(x) { return x.status === 'verified' && x.unit_price != null && !!x.link; }
  function kind(x) { return isV(x) ? 'v' : (x.unit_price == null ? 'q' : 'u'); }
  var KL = { v: 'Verified', u: 'Unverified', q: 'Quote only' };
  var KT = { v: 'Exact MPN, a vendor link and an explicitly stated unit price', u: 'Priced, but the MPN, link or price is a suggestion that has not been confirmed. Not counted in the verified total.', q: 'No catalogue price found - request a quote. Not counted in the verified total.' };
  function name(x) { return x.mpn || String(x.value).split(/ \(|, /)[0]; }
  function spec(x) {
    var t = x.mpn ? String(x.value).split(', ')[0] : String(x.value).split(/ \(|, /).slice(1).join(', ');
    if (!x.mpn && !t && x.fixed) t = 'one-time per order';
    t = t.replace(/\)\s*$/, ''); if (t.length > 46) t = t.slice(0, 44).replace(/[\s,;(]+\S*$/, '') + '...';
    return t === name(x) ? '' : t;
  }
  function linkify(t) { return esc(t).replace(/(https?:\/\/[^\s)]+)/g, '<a href="$1" target="_blank" rel="noopener">link</a>'); }
  function tile(x, cls) { var k = PT.keyOf(x); return '<div class="pt-tile ' + (cls || '') + '">' + PT.inner(k, name(x)) + '</div>'; }
  function buyBtn(x, cls) {
    if (!x.link) return '<span class="bbtn off ' + (cls || '') + '" title="No purchase link in the BOM data">No link</span>';
    var q = x.unit_price == null;
    var v = PT.vendor(x.link);
    return '<a class="bbtn ' + (q ? 'quote ' : '') + (cls || '') + '" href="' + esc(x.link) + '" target="_blank" rel="noopener" title="' + esc(PT.host(x.link)) + '">' + (q ? 'Request quote' : 'Buy' + (v ? ' at ' + esc(v) : '')) + ' <i aria-hidden="true">&#8599;</i></a>';
  }
  function badge(x) { var k = kind(x); return '<span class="badge ' + k + '" title="' + esc(KT[k]) + '">' + KL[k] + '</span>'; }
  function hardChip(x) { return x.hard ? '<span class="badge h" title="' + esc(x.hard) + '">Hard to source</span>' : ''; }

  function detailsHtml(x) {
    var r = [];
    if (x.designators && x.designators !== '-') r.push(['Designators', '<span class="pins">' + esc(x.designators) + '</span>']);
    r.push(['Description', esc(x.value)]);
    if (x.hard) r.push(['Sourcing', '<span class="warn-t">' + linkify(x.hard) + '</span>']);
    if (x.notes) r.push(['Notes', linkify(x.notes)]);
    if (x.price_source) r.push(['Price source', esc(x.price_source)]);
    if (x.mpn && x.mpn_suggested) r.push(['MPN', 'suggested, not checked against a datasheet']);
    if (x.fixed) r.push(['Scaling', 'one-time per order (not multiplied by the number of boards)']);
    if (x.checked) r.push(['Checked', esc(x.checked)]);
    return '<dl>' + r.map(function (a) { return '<div><dt>' + a[0] + '</dt><dd>' + a[1] + '</dd></div>'; }).join('') + '</dl>';
  }

  function card(x) {
    var e = ext(x), k = kind(x), unit = x.unit_price;
    var q = x.fixed ? '<span class="pc-qty">one-time &times; <b>' + x.qty + '</b></span>' : '<span class="pc-qty">&times; <b>' + x.qty * 1 + '</b></span>';
    var s = spec(x);
    return '<article class="pc k-' + k + '" data-i="' + x.i + '">' +
      tile(x, 'pc-img') +
      '<div class="pc-main"><div class="pc-top"><h3 class="pc-name" title="' + esc(name(x)) + '">' + esc(name(x)) + '</h3>' + badge(x) + hardChip(x) + '</div>' +
      '<div class="pc-sub">' + (x.mfr ? '<span>' + esc(x.mfr) + '</span>' : '') + (x.mfr && s ? '<i>&middot;</i>' : '') + (s ? '<span>' + esc(s) + '</span>' : '') + '</div>' +
      '<details class="pc-det"' + (S.details ? ' open' : '') + '><summary>Details</summary>' + detailsHtml(x) + '</details></div>' +
      '<div class="pc-buy"><div class="pc-price"><div class="pc-ext' + (k === 'v' ? '' : ' est') + '">' + (e == null ? 'n/a' : money2(e)) + (e != null && k !== 'v' ? '<sup title="' + esc(KT[k]) + '">est.</sup>' : '') + '</div>' +
      '<div class="pc-unit">' + q + (unit != null ? ' <span>@ ' + money(unit) + '</span>' : '') + '</div></div>' + buyBtn(x) + '</div></article>';
  }

  function cmp(a, b) {
    var k = S.sort, A, B;
    if (k === 'name') { A = name(a); B = name(b); }
    else if (k === 'qty') { A = a.qty; B = b.qty; }
    else if (k === 'unit') { A = a.unit_price; B = b.unit_price; }
    else if (k === 'ext') { A = ext(a); B = ext(b); }
    else if (k === 'status') { A = ['v', 'u', 'q'].indexOf(kind(a)); B = ['v', 'u', 'q'].indexOf(kind(b)); }
    else if (k === 'mfr') { A = a.mfr; B = b.mfr; }
    else { A = a.i; B = b.i; }
    if (A == null || A === '') A = S.desc ? -Infinity : Infinity; if (B == null || B === '') B = S.desc ? -Infinity : Infinity;
    var r = typeof A === 'number' && typeof B === 'number' ? (A === B ? 0 : A < B ? -1 : 1) : String(A).localeCompare(String(B), undefined, { numeric: true });
    return (S.desc ? -r : r) || a.i - b.i;
  }
  function filtered() {
    var q = $('q').value.toLowerCase().trim(), cat = $('cat').value, st = $('st').value;
    return items.filter(function (x) {
      if (cat && x.category !== cat) return false;
      var k = kind(x);
      if (st === 'verified' && k !== 'v') return false; if (st === 'unverified' && k === 'v') return false; if (st === 'quote' && k !== 'q') return false; if (st === 'hard' && !x.hard) return false;
      return !q || [x.category, x.designators, x.value, x.mpn, x.mfr, x.notes, x.hard].join(' ').toLowerCase().indexOf(q) >= 0;
    }).sort(cmp);
  }

  var cols = [['name', 'Part'], ['category', 'Category', 'cat'], ['qty', 'Qty', 'qty', 1], ['unit', 'Unit $', 'unit', 1], ['ext', 'Ext $', 'ext', 1], ['status', 'Status', 'status'], ['buy', 'Buy']];
  function tableHtml(L) {
    var tc = cols.filter(function (c) { return !(S.group && c[0] === 'category'); }); var nc = tc.length + (S.details ? 2 : 0);
    var head = tc.map(function (c) {
      var sk = c[0] === 'category' ? 'cat' : c[0], sortable = c[0] !== 'buy';
      return '<th' + (c[3] ? ' class="n"' : '') + (sortable ? ' data-k="' + sk + '" tabindex="0" role="button"' : '') + (S.sort === sk ? ' aria-sort="' + (S.desc ? 'descending' : 'ascending') + '"' : '') + '>' + c[1] + (S.sort === sk ? '<i class="ar">' + (S.desc ? '&#9662;' : '&#9652;') + '</i>' : '') + '</th>';
    }).join('') + (S.details ? '<th>Designators</th><th>Description</th>' : '');
    $('hd').innerHTML = head;
    var html = '', last = null;
    L.forEach(function (x) {
      if (S.group && x.category !== last) { last = x.category; html += '<tr class="grp"><td colspan="' + nc + '">' + esc(last) + '</td></tr>'; }
      var e = ext(x), k = kind(x);
      html += '<tr class="k-' + k + '"><td data-l="Part"><div class="tp">' + tile(x, 'pt-sm') + '<div><b>' + esc(name(x)) + '</b><div class="muted sm">' + esc(x.mfr || '') + (spec(x) ? (x.mfr ? ' &middot; ' : '') + esc(spec(x)) : '') + '</div></div></div></td>' +
        (S.group ? '' : '<td data-l="Category">' + esc(x.category) + '</td>') + '<td class="n" data-l="Qty">' + x.qty + '</td><td class="n" data-l="Unit $">' + money(x.unit_price) + '</td><td class="n" data-l="Ext $">' + (e == null ? '-' : money2(e) + (k === 'v' ? '' : '*')) + '</td>' +
        '<td data-l="Status">' + badge(x) + '</td><td data-l="Buy">' + buyBtn(x, 'sm') + '</td>' +
        (S.details ? '<td data-l="Designators"><span class="pins">' + esc(x.designators) + '</span></td><td data-l="Description">' + esc(x.value) + '</td>' : '') + '</tr>';
    });
    $('tb').innerHTML = html;
    Array.prototype.forEach.call($('hd').children, function (th) {
      var k = th.getAttribute('data-k'); if (!k) return;
      function go() { if (S.sort === k) S.desc = !S.desc; else { S.sort = k; S.desc = false; } $('sort').value = S.sort; render(); }
      th.onclick = go; th.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } };
    });
  }

  function cardsHtml(L) {
    if (!S.group) return '<div class="pg-list">' + L.map(card).join('') + '</div>';
    var out = '', done = {};
    cats.forEach(function (c) {
      var G = L.filter(function (x) { return x.category === c; }); if (!G.length || done[c]) return; done[c] = 1;
      var sub = 0, unv = 0; G.forEach(function (y) { if (isV(y)) sub += ext(y); else unv++; });
      var closed = !!S.closed[c];
      out += '<section class="pg' + (closed ? ' closed' : '') + '" data-c="' + esc(c) + '"><header class="pg-h" tabindex="0" role="button" aria-expanded="' + !closed + '"><i class="chev" aria-hidden="true"></i><h2>' + esc(c) + '</h2><span class="pg-n">' + G.length + ' line' + (G.length > 1 ? 's' : '') + '</span><span class="grow"></span>' +
        '<span class="pg-sub" title="Verified lines only">' + money2(sub) + (unv ? ' <em>+ ' + unv + ' not verified</em>' : '') + '</span></header>' +
        '<div class="pg-list">' + G.map(card).join('') + '</div></section>';
    });
    return out;
  }

  function render() {
    var L = filtered(), table = S.view === 'table';
    $('cards').hidden = table; $('twrap').hidden = !table;
    root.classList.toggle('bom-table-on', table);
    if (!L.length) {
      $('cards').hidden = false; $('twrap').hidden = true;
      $('cards').innerHTML = '<div class="bom-empty"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="21" cy="21" r="12"/><path d="M30 30l11 11M16 21h10"/></svg><h3>No parts match</h3><p class="muted">Nothing in the BOM matches the current search and filters.</p><button type="button" id="bom-clear" class="primary">Clear filters</button></div>';
      $('clear').onclick = function () { $('q').value = ''; $('cat').value = ''; $('st').value = ''; render(); };
    } else if (table) tableHtml(L);
    else $('cards').innerHTML = cardsHtml(L);
    $('count').textContent = L.length === items.length ? items.length + ' lines' : L.length + ' of ' + items.length + ' lines';
    /* totals (always over the whole BOM) */
    var perBoard = 0, fixed = 0, unv = 0, hard = 0;
    items.forEach(function (x) { if (isV(x)) { if (x.fixed) fixed += x.qty * x.unit_price; else perBoard += x.qty * x.unit_price; } else unv++; if (x.hard) hard++; });
    var tot = perBoard * S.m + fixed;
    Array.prototype.forEach.call(root.getElementsByClassName('bn'), function (e) { e.textContent = S.m; });
    $('tV').textContent = money(tot); $('tVb').textContent = money(perBoard); $('tF').textContent = money(fixed);
    $('tU').textContent = unv + ' of ' + items.length; $('tH').textContent = hard;
    $('tf').innerHTML = '<tr><td colspan="9"><b>' + money(tot) + '</b> verified total for ' + S.m + ' board' + (S.m > 1 ? 's' : '') + ' <span class="muted">(' + money(perBoard) + ' &times; ' + S.m + ' + ' + money(fixed) + ' one-time; per-board average ' + money(tot / S.m) + ')</span></td></tr>';
    Array.prototype.forEach.call(root.querySelectorAll('[data-m]'), function (b) { var on = +b.getAttribute('data-m') === S.m; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    Array.prototype.forEach.call(root.querySelectorAll('[data-view]'), function (b) { var on = b.getAttribute('data-view') === S.view; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    $('grp').classList.toggle('on', S.group); $('grp').setAttribute('aria-pressed', S.group);
    $('det').classList.toggle('on', S.details); $('det').setAttribute('aria-pressed', S.details);
    $('dir').innerHTML = S.desc ? '&#9662; Desc' : '&#9652; Asc'; $('dir').setAttribute('aria-label', 'Sort direction: ' + (S.desc ? 'descending' : 'ascending'));
  }

  /* events */
  $('sub').textContent = D.project + ' - prices checked ' + D.price_checked + ' - sources: ' + D.sources;
  $('ft').textContent = D.notes + ' * / est. = extended price shown but excluded from the verified total. Fixed-cost scaling (e.g. fab setup, stencil, 5-board minimum) is not modelled for quantities above one order.';
  cats.forEach(function (c) { var o = document.createElement('option'); o.value = o.textContent = c; $('cat').appendChild(o); });
  $('q').oninput = $('cat').onchange = $('st').onchange = render;
  $('sort').onchange = function () { S.sort = this.value; S.desc = (S.sort === 'ext' || S.sort === 'qty'); render(); };
  $('dir').onclick = function () { S.desc = !S.desc; render(); };
  $('mult').oninput = function () { var v = parseInt(this.value, 10); S.m = v > 0 ? v : 1; render(); };
  Array.prototype.forEach.call(root.querySelectorAll('[data-m]'), function (b) { b.onclick = function () { S.m = +b.getAttribute('data-m'); $('mult').value = S.m; render(); }; });
  Array.prototype.forEach.call(root.querySelectorAll('[data-view]'), function (b) { b.onclick = function () { S.view = b.getAttribute('data-view'); save(); render(); }; });
  $('grp').onclick = function () { S.group = !S.group; save(); render(); };
  $('det').onclick = function () { S.details = !S.details; save(); render(); };
  function toggleGroup(h) { var c = h.parentNode.getAttribute('data-c'); S.closed[c] = !S.closed[c]; h.parentNode.classList.toggle('closed', S.closed[c]); h.setAttribute('aria-expanded', !S.closed[c]); }
  $('cards').onclick = function (e) { var h = e.target.closest && e.target.closest('.pg-h'); if (h) toggleGroup(h); };
  $('cards').onkeydown = function (e) { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('pg-h')) { e.preventDefault(); toggleGroup(e.target); } };
  $('csv').onclick = function () {
    var L = filtered(), c = function (s) { s = String(s == null ? '' : s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    var rows = [['category', 'name', 'manufacturer', 'designators', 'qty', 'unit_usd', 'extended_usd', 'status', 'buy_link', 'description', 'notes']];
    L.forEach(function (x) { var e = ext(x); rows.push([x.category, name(x), x.mfr, x.designators, x.qty, x.unit_price, e == null ? '' : e.toFixed(4), KL[kind(x)], x.link, x.value, x.notes]); });
    try {
      var b = new Blob([rows.map(function (r) { return r.map(c).join(','); }).join('\r\n') + '\r\n'], { type: 'text/csv' }), a = document.createElement('a');
      a.download = 'bom.csv'; a.href = URL.createObjectURL(b); document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    } catch (err) {}
  };
  render();
};
})();
