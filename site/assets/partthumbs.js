/* partthumbs.js - part thumbnails shared by the BOM page (bom2.js) and the PCB viewer info panel (viewers3d.js).
   Images are rendered offline from the real 3D models (render/render_part_thumbs.py -> img/parts/*.webp, rules in data/partthumbs.js).
   Rows without a rendered image (fab/assembly fees, unknown parts) get an inline SVG icon. No network access. */
(function () {
'use strict';
var D = window.PARTTHUMBS || { dir: 'img/parts/', ext: '.webp', keys: [], rules: [], fp: [] };
var have = {}; D.keys.forEach(function (k) { have[k] = 1; });
var rx = D.rules.map(function (r) { return [r[0], new RegExp(r[1], 'i'), r[2]]; });
var fprx = D.fp.map(function (r) { return [new RegExp(r[0], 'i'), r[1]]; });
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

var ICONS = {
  'fee-setup': '<path d="M4 7h9M17 7h3M4 17h3M11 17h9M4 12h16"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/><circle cx="9" cy="12" r="0.01"/>',
  'fee-stencil': '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><g fill="currentColor" stroke="none"><rect x="7" y="7" width="3" height="2" rx=".5"/><rect x="14" y="7" width="3" height="2" rx=".5"/><rect x="7" y="11" width="3" height="2" rx=".5"/><rect x="14" y="11" width="3" height="2" rx=".5"/><rect x="7" y="15" width="10" height="2" rx=".5"/></g>',
  'fee-feeder': '<circle cx="9" cy="12" r="6"/><circle cx="9" cy="12" r="1.6"/><path d="M15 12h6M15 7.5l5 0M15 16.5h5"/><path d="M9 6v2.4M9 15.6V18M3 12h2.4M12.6 12H15"/>',
  'fee-place': '<path d="M12 3v8M9 8l3 3 3-3"/><rect x="9" y="11" width="6" height="3" rx=".8"/><rect x="3.5" y="17.5" width="17" height="3" rx="1"/><path d="M7 17.5v-1M17 17.5v-1"/>',
  'generic': '<rect x="6" y="6" width="12" height="12" rx="1.5"/><path d="M9 6V3M12 6V3M15 6V3M9 21v-3M12 21v-3M15 21v-3M6 9H3M6 12H3M6 15H3M21 9h-3M21 12h-3M21 15h-3"/>'
};
function icon(k) {
  return '<svg class="pt-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[k] || ICONS.generic) + '</svg>';
}

/* BOM item -> thumbnail key */
function keyOf(it) {
  if (!it) return null;
  for (var i = 0; i < rx.length; i++) { var v = it[rx[i][0]]; if (v && rx[i][1].test(v)) return rx[i][2]; }
  return null;
}
function keyOfFp(fp) { for (var i = 0; i < fprx.length; i++) if (fprx[i][0].test(fp || '')) return fprx[i][1]; return null; }
function url(k) { return have[k] ? D.dir + k + D.ext : null; }
/* inner HTML of a thumbnail tile (image, svg icon or generic glyph) */
function inner(k, alt) {
  if (k && have[k]) return '<img src="' + D.dir + k + D.ext + '" alt="' + esc(alt || '') + '" loading="lazy" decoding="async" draggable="false">';
  return icon(k && ICONS[k] ? k : 'generic');
}

/* designator list ("C1-C9 C13 FB2-FB6 U1") -> {ref: BOM item} */
var rm = null;
function refMap() {
  if (rm) return rm; rm = {};
  var B = window.BOM; if (!B) return rm;
  B.items.forEach(function (it) {
    String(it.designators || '').split(/[\s,]+/).forEach(function (t) {
      var m = /^([A-Za-z]+)(\d+)(?:-([A-Za-z]*)(\d+))?$/.exec(t); if (!m) return;
      var a = +m[2], b = m[4] ? +m[4] : a; if (b < a || b - a > 400) b = a;
      for (var n = a; n <= b; n++) rm[m[1] + n] = it;
    });
  });
  return rm;
}
function host(l) { try { return String(l).replace(/^https?:\/\/(www\.)?/, '').split('/')[0]; } catch (e) { return ''; } }
function vendor(l) { var h = host(l); var p = h.split('.'); var n = p.length > 1 ? p[p.length - 2] : h; if (/^(lcsc|jlcpcb|pcb|ti|mouser|digikey)$/i.test(n) && n.length <= 7) return n.toUpperCase().replace('PCB','PCB'); return n ? n.charAt(0).toUpperCase() + n.slice(1) : ''; }

/* PCB viewer info panel head: thumbnail on the left, name / maker / price / buy button on the right */
function panelHead(p, d, ref) {
  var it = ref ? refMap()[ref] : null;
  var k = it ? keyOf(it) : (d ? keyOfFp(d.fp) : null);
  var title = it ? (it.mpn || String(it.value).split(/ \(|, /)[0]) : (d ? d.val : (p.title || p.name || 'Part'));
  var sub = [];
  if (it && it.mfr) sub.push(esc(it.mfr));
  if (d && d.val && (!it || String(d.val) !== title)) sub.push(esc(d.val));
  var h = '<div class="v3-card"><div class="pt-tile">' + inner(k, title) + '</div><div class="v3-ct">';
  h += '<div class="v3-ref">' + esc(ref || p.title || '') + '</div>';
  h += '<div class="v3-name" title="' + esc(title) + '">' + esc(title) + '</div>';
  if (sub.length) h += '<div class="v3-sub">' + sub.join(' &middot; ') + '</div>';
  h += '<div class="v3-chips">';
  if (d) h += '<span class="v3-chip">' + esc(d.side) + ' side</span>';
  if (it && it.unit_price != null) h += '<span class="v3-chip">$' + Number(it.unit_price).toFixed(it.unit_price < 1 ? 3 : 2) + ' ea</span>';
  h += '</div>';
  if (it && it.link) h += '<a class="v3-buy" href="' + esc(it.link) + '" target="_blank" rel="noopener" title="Open ' + esc(host(it.link)) + '">Buy &#8599;</a>';
  if (it) h += ' <a class="v3-more" href="#/bom?q=' + encodeURIComponent(it.mpn || ref || '') + '">BOM line</a>';
  h += '</div></div>';
  return h;
}

window.PartThumbs = { keyOf: keyOf, keyOfFp: keyOfFp, url: url, inner: inner, icon: icon, refMap: refMap, host: host, vendor: vendor, panelHead: panelHead, esc: esc };
})();
