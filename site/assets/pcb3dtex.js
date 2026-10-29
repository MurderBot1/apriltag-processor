/* Routed-board texture for the interactive 3D viewers: top / bottom faces of the board get the soldermask + copper traces + gold pads + silkscreen
   image generated from the routed .kicad_pcb (render/make_pcb_textures.py). The textures live in data/pcbtex.js (data URIs: WebGL can use them from file://)
   and are loaded lazily, the first time a viewer with a PCB is created. */
(function () {
var T = window.THREE; if (!T) return;
var loading = null, waiting = [];
function load(cb) {
  if (window.PCBTEX) return cb(window.PCBTEX);
  waiting.push(cb); if (loading) return; loading = document.createElement('script'); loading.src = 'data/pcbtex.js';
  loading.onload = function () { var w = waiting; waiting = []; w.forEach(function (f) { f(window.PCBTEX); }); }; loading.onerror = function () { waiting = []; };
  document.head.appendChild(loading);
}
function shapeGeo(D, z) {
  var sh = new T.Shape(); D.poly.forEach(function (p, i) { if (i) sh.lineTo(p[0], p[1]); else sh.moveTo(p[0], p[1]); });
  D.holes.forEach(function (h) { var pa = new T.Path(); pa.absarc(h[0], h[1], h[2], 0, Math.PI * 2, true); sh.holes.push(pa); });
  var g = new T.ShapeGeometry(sh, 24), pos = g.attributes.position, uv = g.attributes.uv, s = D.size;
  for (var i = 0; i < pos.count; i++) { uv.setXY(i, pos.getX(i) / s + 0.5, pos.getY(i) / s + 0.5); pos.setZ(i, z); }
  g.computeVertexNormals(); return g;
}
function tex(url, renderer, cb) {
  var im = new Image(); im.onload = function () { var t = new T.Texture(im); t.encoding = T.sRGBEncoding; t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy()); t.needsUpdate = true; cb(t); }; im.src = url;
}
window.PCB3D = {
  attach: function (v, board, topZ, botZ) {
    var h = { meshes: [], on: true, setVisible: function (on) { h.on = on; h.meshes.forEach(function (m) { m.visible = on; }); v.invalidate(); } };
    v.pcbTex = h;
    load(function (D) {
      var faces = [['top', topZ + 0.02, 1], ['bottom', botZ - 0.02, -1]];
      faces.forEach(function (f) {
        tex(D[f[0]], v.renderer, function (t) {
          var m = new T.Mesh(shapeGeo(D, f[1]), new T.MeshPhysicalMaterial({ map: t, roughness: 0.38, metalness: 0.0, clearcoat: 0.5, clearcoatRoughness: 0.3, side: T.DoubleSide, envMapIntensity: 0.8, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
          m.receiveShadow = true; m.name = 'pcbtex_' + f[0]; m.visible = h.on; m.userData.noPick = true; board.add(m); h.meshes.push(m); v.invalidate();
        });
      });
    });
    return h;
  }
};
})();
