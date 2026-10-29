/* RTL cross-links: complements the viewer in app.js / ui.js (find, line anchors, jump list live there).
   - module instantiations inside the Verilog source become links to the module definition (#/rtl/<file>?L=<line>), with a hover title
   - module names in the RTL file table and in <code> elements on every other page link to their definition
   - the target line flashes after a jump
   Vanilla JS, works offline from file://. */
(function () {
'use strict';
var $ = function (s, r) { return (r || document).querySelector(s); }, $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
var defs = null, fileSet = null, reMods = null;

function build() {
  if (defs || !window.RTL || !RTL.mods) return !!defs;
  defs = {}; fileSet = {};
  RTL.mods.forEach(function (m) {
    fileSet[m.file] = m;
    var lines = m.html.replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').split('\n');
    m.modules.forEach(function (n) {
      var ln = 1; for (var i = 0; i < lines.length; i++) if (new RegExp('^\\s*module\\s+' + n + '\\b').test(lines[i])) { ln = i + 1; break; }
      defs[n] = { file: m.file, line: ln, lines: m.lines, mod: m };
    });
  });
  var names = Object.keys(defs).sort(function (a, b) { return b.length - a.length; });
  reMods = names.length ? new RegExp('\\b(' + names.join('|') + ')\\b', 'g') : null;
  return true;
}
function hrefOf(n) { var d = defs[n]; return '#/rtl/' + encodeURIComponent(d.file) + '?L=' + d.line; }
function titleOf(n) { var d = defs[n]; return 'module ' + n + ' - ' + d.file + ', line ' + d.line + ' (' + d.lines + ' lines in file). Click to open.'; }
function mkLink(n, txt) { var a = document.createElement('a'); a.className = 'modlink'; a.href = hrefOf(n); a.title = titleOf(n); a.textContent = txt == null ? n : txt; return a; }

/* link the module name of an instantiation line ("  name #(...) inst (" or "  name inst (") */
function linkLine(ln) {
  if (ln.__ml) return; ln.__ml = 1; if (!reMods) return;
  var m = /^\s*(\w+)\s*(?:#\s*\(|\w+\s*(?:\(|$))/.exec(ln.textContent);
  if (!m || !defs[m[1]]) return;
  var w = document.createTreeWalker(ln, NodeFilter.SHOW_TEXT, null), n = w.nextNode();
  while (n && !/\S/.test(n.nodeValue)) n = w.nextNode();
  if (!n) return;
  var mm = /^(\s*)(\w+)/.exec(n.nodeValue); if (!mm || mm[2] !== m[1]) return;
  var rest = n.nodeValue.slice(mm[0].length), frag = document.createDocumentFragment();
  frag.appendChild(document.createTextNode(mm[1])); frag.appendChild(mkLink(mm[2])); if (rest) frag.appendChild(document.createTextNode(rest));
  n.parentNode.replaceChild(frag, n);
}
function linkSource() { var pre = $('#rtl-src'); if (!pre || !build()) return; $$('.ln', pre).forEach(linkLine); }

function linkTable() {
  var tb = $('#rtltable'); if (!tb || !build() || tb.__ml) return; tb.__ml = 1;
  $$('tbody tr', tb).forEach(function (tr) {
    var td = tr.children[2]; if (!td) return; var names = td.textContent.split(/,\s*/).filter(Boolean);
    if (!names.length) return; td.textContent = '';
    names.forEach(function (n, k) { if (k) td.appendChild(document.createTextNode(', ')); if (defs[n]) { var a = mkLink(n); a.addEventListener('click', function (e) { e.stopPropagation(); }); td.appendChild(a); } else td.appendChild(document.createTextNode(n)); });
  });
}

/* <code>name</code>, <code>name.v</code>, <code>rtl/name.v</code> anywhere on a page */
function linkCode(root) {
  if (!build()) return;
  $$('code', root).forEach(function (c) {
    if (c.__ml || c.closest('a') || c.closest('pre') || c.closest('#rtl-view') || c.closest('.modal') || c.closest('.v3')) return; c.__ml = 1;
    var t = c.textContent.trim(), m = /^(?:rtl\/)?([\w]+\.(?:v|lpf))$/.exec(t), a;
    if (m && fileSet[m[1]]) { a = document.createElement('a'); a.className = 'modlink'; a.href = '#/rtl/' + encodeURIComponent(m[1]); a.title = 'open ' + m[1] + ' in the RTL browser (' + fileSet[m[1]].lines + ' lines)'; }
    else if (defs[t]) a = mkLink(t, t);
    if (a) { a.textContent = t; c.textContent = ''; c.appendChild(a); }
  });
}

/* flash the line a jump lands on */
function flash() {
  var q = location.hash.match(/[?&]L=(\d+)/); if (!q) return; var pre = $('#rtl-src'); if (!pre) return;
  var l = pre.querySelectorAll('.ln')[+q[1] - 1]; if (!l) return; l.classList.remove('flash'); void l.offsetWidth; l.classList.add('flash');
}

function pass() {
  var vis = $$('section.page').filter(function (s) { return !s.hidden; })[0]; if (!vis) return;
  if (vis.id === 'page-rtl') { linkTable(); linkSource(); setTimeout(flash, 80); }
  linkCode(vis);
}
function boot() {
  pass();
  var pre = $('#rtl-src');
  if (pre && !pre.__mo) { pre.__mo = 1; new MutationObserver(function () { linkSource(); setTimeout(flash, 60); }).observe(pre, { childList: true }); }
}
window.addEventListener('hashchange', function () { setTimeout(boot, 40); setTimeout(boot, 400); });
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 50); }); else setTimeout(boot, 50);
window.RtlLinks = { run: boot };
})();
