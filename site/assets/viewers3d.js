/* Interactive 3D viewers (housing assembly + PCB from STEP).  Vanilla JS on top of vendor/three.min.js (r147, classic build) and
   vendor/OrbitControls.js.  Loaded before app.js; app.js calls Viewers3D.init() instead of its legacy initModels.
   Data: window.MODELS (data/models.js) incl. MODELS.pcb.parts (per-solid ranges, ref designators) and MODELS.pcb.info (refs, nets). */
(function () {
'use strict';
if (!window.THREE) return;
var T = THREE;

/* ------------------------------------------------------------------ small helpers */
function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
function b64buf(s, Type) { var bin = atob(s), n = bin.length, u = new Uint8Array(n); for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i); return new Type(u.buffer); }
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { } return null; }
function isDark() { var t = document.documentElement.getAttribute('data-theme'); if (t) return t === 'dark'; return !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches); }
function lin(hex) { return new T.Color(hex).convertSRGBToLinear(); }
function ease(t) { t = Math.max(0, Math.min(1, t)); return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function fmt(x, d) { return (Math.round(x * Math.pow(10, d == null ? 1 : d)) / Math.pow(10, d == null ? 1 : d)).toFixed(d == null ? 1 : d); }
function hash(o) { try { return history.replaceState(null, '', location.pathname + location.search + o); } catch (e) { } }

/* flat-shaded non-indexed copy of an indexed range */
function flatGeom(pos, idx, i0, n, v0, vn) {
  var out = new Float32Array(n * 3), k = 0;
  for (var i = 0; i < n; i++) { var vi = idx[i0 + i]; out[k++] = pos[vi * 3]; out[k++] = pos[vi * 3 + 1]; out[k++] = pos[vi * 3 + 2]; }
  var g = new T.BufferGeometry(); g.setAttribute('position', new T.BufferAttribute(out, 3)); g.computeVertexNormals(); g.computeBoundingBox(); g.computeBoundingSphere(); return g;
}
/* smooth normals with a crease angle for triangle soup (STL) */
function creasedGeom(pos, deg) {
  var n = pos.length / 9, fn = new Float32Array(n * 3), fa = new Float32Array(n * 3), map = new Map(), cosT = Math.cos(deg * Math.PI / 180), f, k, i;
  function key(o) { return Math.round(pos[o] * 400) + ',' + Math.round(pos[o + 1] * 400) + ',' + Math.round(pos[o + 2] * 400); }
  for (f = 0; f < n; f++) {
    var o = f * 9, ax = pos[o + 3] - pos[o], ay = pos[o + 4] - pos[o + 1], az = pos[o + 5] - pos[o + 2], bx = pos[o + 6] - pos[o], by = pos[o + 7] - pos[o + 1], bz = pos[o + 8] - pos[o + 2];
    var cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx, l = Math.hypot(cx, cy, cz) || 1;
    fa[f * 3] = cx; fa[f * 3 + 1] = cy; fa[f * 3 + 2] = cz; fn[f * 3] = cx / l; fn[f * 3 + 1] = cy / l; fn[f * 3 + 2] = cz / l;
    for (k = 0; k < 3; k++) { var kk = key(o + k * 3), a = map.get(kk); if (!a) map.set(kk, a = []); a.push(f); }
  }
  var nor = new Float32Array(n * 9);
  for (f = 0; f < n; f++) for (k = 0; k < 3; k++) {
    var list = map.get(key(f * 9 + k * 3)), sx = 0, sy = 0, sz = 0;
    for (i = 0; i < list.length; i++) { var g = list[i]; if (fn[f * 3] * fn[g * 3] + fn[f * 3 + 1] * fn[g * 3 + 1] + fn[f * 3 + 2] * fn[g * 3 + 2] > cosT) { sx += fa[g * 3]; sy += fa[g * 3 + 1]; sz += fa[g * 3 + 2]; } }
    var L = Math.hypot(sx, sy, sz) || 1; nor[f * 9 + k * 3] = sx / L; nor[f * 9 + k * 3 + 1] = sy / L; nor[f * 9 + k * 3 + 2] = sz / L;
  }
  var gm = new T.BufferGeometry(); gm.setAttribute('position', new T.BufferAttribute(pos, 3)); gm.setAttribute('normal', new T.BufferAttribute(nor, 3)); gm.computeBoundingBox(); gm.computeBoundingSphere(); return gm;
}

/* hand-made studio environment for reflections (gradient dome + softboxes), no HDR file needed */
function makeEnv(renderer) {
  try {
    var sc = new T.Scene();
    var dome = new T.Mesh(new T.SphereGeometry(60, 32, 16), new T.ShaderMaterial({
      side: T.BackSide, depthWrite: false,
      vertexShader: 'varying vec3 vP;void main(){vP=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
      fragmentShader: 'varying vec3 vP;void main(){float h=normalize(vP).z*.5+.5;vec3 top=vec3(.62,.70,.85),hor=vec3(.40,.42,.47),bot=vec3(.10,.10,.12);vec3 c=mix(bot,hor,smoothstep(.0,.5,h));c=mix(c,top,smoothstep(.5,1.,h));gl_FragColor=vec4(c,1.);}'
    }));
    sc.add(dome);
    function box(x, y, z, w, h, s) { var m = new T.Mesh(new T.PlaneGeometry(w, h), new T.MeshBasicMaterial({ color: new T.Color(s, s, s * 1.02), side: T.DoubleSide })); m.position.set(x, y, z); m.lookAt(0, 0, 0); sc.add(m); }
    box(35, -30, 38, 34, 22, 7); box(-40, 18, 26, 24, 16, 4.2); box(0, 40, 14, 40, 8, 3.4); box(0, 0, 55, 30, 30, 3.2); box(-45, -40, 12, 30, 6, 2.4);
    var pm = new T.PMREMGenerator(renderer), rt = pm.fromScene(sc, 0.03); pm.dispose();
    return rt.texture;
  } catch (e) { return null; }
}

/* ------------------------------------------------------------------ the viewer */
var STYLE_KEYS = ['Low', 'Medium', 'High'];
var all = [];   // live viewers

function Viewer3D(host, cfg) {
  var self = this;
  this.cfg = cfg; this.host = host; this.dead = false; this.vis = {}; this.dirty = true; this.anims = []; this.live = 0; this.selected = null; this.hovered = null;
  this.parts = []; this.meshes = []; this.mats = []; this.measure = { on: false, pts: [], objs: [] }; this.net = null; this.hiddenParts = [];
  this.quality = store('v3q') || 'High'; if (STYLE_KEYS.indexOf(this.quality) < 0) this.quality = 'High';
  this.visibleOnScreen = true; this.explodeVal = 0; this.playState = null; this.clipOn = false;
  this.build();
  if (this.dead) return;
  all.push(this);
}

Viewer3D.prototype.build = function () {
  var self = this, host = this.host, cfg = this.cfg;
  host.innerHTML = '';
  var root = this.root = el('div', 'v3'); root.tabIndex = 0; root.setAttribute('data-kind', cfg.kind);
  host.appendChild(root);
  /* toolbar */
  var bar = this.bar = el('div', 'v3-bar'); root.appendChild(bar);
  var main = el('div', 'v3-main'); root.appendChild(main);
  var stage = this.stage = el('div', 'v3-stage'); main.appendChild(stage);
  var side = this.side = el('div', 'v3-side'); main.appendChild(side);
  root.appendChild(this.hintEl = el('div', 'v3-hint', '<b>Drag</b> orbit &middot; <b>right-drag / shift-drag</b> pan &middot; <b>wheel / pinch</b> zoom &middot; <b>click</b> select &middot; <b>double-click</b> fly to &middot; keys: <kbd>1</kbd>-<kbd>7</kbd> views, <kbd>F</kbd> fit, <kbd>E</kbd> explode, <kbd>Space</kbd> play, <kbd>M</kbd> measure, <kbd>W</kbd> wire, <kbd>Esc</kbd> clear'));
  /* renderer */
  try {
    this.renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance', preserveDrawingBuffer: false });
  } catch (e) { host.innerHTML = '<div class="vmsg">WebGL is not available in this browser, so the interactive 3D view cannot run. The rendered images on the Renders tab still work.</div>'; this.dead = true; return; }
  var r = this.renderer; r.outputEncoding = T.sRGBEncoding; r.setClearColor(0x000000, 0); r.localClippingEnabled = false;
  r.shadowMap.enabled = true; r.shadowMap.type = T.PCFSoftShadowMap; r.shadowMap.autoUpdate = false;
  stage.appendChild(r.domElement); r.domElement.className = 'v3-canvas';
  r.domElement.addEventListener('webglcontextlost', function (e) { e.preventDefault(); self.msg('Graphics context lost; it will be restored automatically.'); });
  r.domElement.addEventListener('webglcontextrestored', function () { self.msg(''); self.shadowDirty = true; self.invalidate(); });
  var sc = this.scene = new T.Scene();
  var cam = this.camera = new T.PerspectiveCamera(32, 1, 0.1, 2000); cam.up.set(0, 0, 1); cam.position.set(80, -100, 80);
  this.env = makeEnv(r); if (this.env) sc.environment = this.env;
  /* lights: hemisphere + key (shadow) + cool fill + warm rim */
  sc.add(this.hemi = new T.HemisphereLight(0xe4ecff, 0x3a3f4a, 0.8));
  var key = this.key = new T.DirectionalLight(0xffffff, 1.05); key.position.set(50, -70, 110); key.castShadow = true; sc.add(key); sc.add(key.target);
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.03; key.shadow.radius = 4;
  var fill = new T.DirectionalLight(0xbfd0ff, 0.35); fill.position.set(-80, 30, 40); sc.add(fill);
  var rim = new T.DirectionalLight(0xdfe8ff, 0.75); rim.position.set(-30, 90, 30); sc.add(rim);
  /* world + helpers */
  this.world = new T.Group(); sc.add(this.world);
  this.ground = new T.Mesh(new T.PlaneGeometry(1, 1), new T.ShadowMaterial({ opacity: 0.32 })); this.ground.receiveShadow = true; this.ground.renderOrder = -1; sc.add(this.ground);
  this.grid = new T.GridHelper(1, 10, 0x888888, 0x888888); this.grid.rotation.x = Math.PI / 2; this.grid.material.transparent = true; this.grid.material.opacity = 0.16; this.grid.visible = false; sc.add(this.grid);
  this.overlay = new T.Group(); sc.add(this.overlay);
  this.clipPlane = new T.Plane(new T.Vector3(0, 0, -1), 0); this.clipHelper = new T.PlaneHelper(this.clipPlane, 60, 0xff9a2e); this.clipHelper.visible = false; this.clipHelper.material.transparent = true; this.clipHelper.material.opacity = 0.6; sc.add(this.clipHelper);
  /* controls */
  var ctl = this.controls = new T.OrbitControls(cam, r.domElement);
  ctl.enableDamping = true; ctl.dampingFactor = 0.12; ctl.rotateSpeed = 0.8; ctl.screenSpacePanning = true; ctl.minPolarAngle = 0; ctl.maxPolarAngle = Math.PI;
  ctl.addEventListener('change', function () { self.dirty = true; self.wake(900); });
  ctl.addEventListener('start', function () { self.cancelCam(); self.interacting = true; self.wake(1200); });
  ctl.addEventListener('end', function () { self.interacting = false; self.wake(1200); });
  /* stage overlays */
  stage.appendChild(this.tip = el('div', 'v3-tip')); this.tip.hidden = true;
  stage.appendChild(this.readout = el('div', 'v3-readout'));
  stage.appendChild(this.msgEl = el('div', 'v3-msg')); this.msgEl.hidden = true;
  stage.appendChild(this.labels = el('div', 'v3-labels'));
  /* build model + UI */
  cfg.setup(this);
  this.buildBar();
  this.buildSide();
  this.initInput();
  /* resize, visibility */
  this.ro = (window.ResizeObserver ? new ResizeObserver(function () { self.resize(); }) : null); if (this.ro) this.ro.observe(stage);
  window.addEventListener('resize', function () { self.resize(); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) self.wake(500); });
  if (window.IntersectionObserver) { this.io = new IntersectionObserver(function (es) { self.visibleOnScreen = es[0].isIntersecting; if (self.visibleOnScreen) self.wake(500); }, { threshold: 0.01 }); this.io.observe(stage); }
  document.addEventListener('fullscreenchange', function () { root.classList.toggle('v3-fs', document.fullscreenElement === root); self.resize(); });
  this.applyQuality(); this.resize(); this.applyVis(); this.curView = 'iso'; this.syncViewBtns(); this.fit(false, 'iso'); this.setExplode(this.explodeVal);
  this.wake(800);
  this.setReadout();
};

Viewer3D.prototype.msg = function (t) { this.msgEl.hidden = !t; this.msgEl.textContent = t || ''; };

/* ----- render loop (on demand; sleeps when hidden / off-screen) */
Viewer3D.prototype.active = function () { return !document.hidden && this.visibleOnScreen && this.stage.clientWidth > 0 && !this.dead; };
Viewer3D.prototype.wake = function (ms) { this.live = Math.max(this.live, performance.now() + (ms || 0)); this.dirty = true; this.schedule(); };
Viewer3D.prototype.invalidate = function (shadow) { this.dirty = true; if (shadow !== false) this.shadowDirty = true; this.schedule(); };
Viewer3D.prototype.schedule = function () { if (this.raf || this.dead) return; var self = this; this.raf = requestAnimationFrame(function (t) { self.raf = 0; self.tick(t); }); };
Viewer3D.prototype.tick = function (t) {
  if (!this.active()) return;                 /* sleeping: wake() re-schedules */
  var now = performance.now(), busy = this.stepAnims(now);
  if (this.controls.enableDamping) this.controls.update();
  if (this.pickPending) { this.pickPending = false; this.doPick(); }
  if (this.dirty || busy) { this.render(); this.dirty = false; this.perf(now); }
  if (busy || now < this.live || this.dirty) this.schedule(); else this.lastFrame = 0;
};
Viewer3D.prototype.perf = function (now) {   /* adaptive resolution: step the quality down when frames are persistently slow */
  if (this.lastFrame) {
    var dt = now - this.lastFrame; this.fAvg = this.fAvg ? this.fAvg * 0.9 + dt * 0.1 : dt;
    if (this.fAvg > 55 && dt < 400 && this.quality !== 'Low' && !this.qLocked && (this.interacting || this.anims.length || this.playState)) {
      this.fSlow = (this.fSlow || 0) + 1;
      if (this.fSlow > 25) { this.fSlow = 0; this.fAvg = 0; this.setQuality(this.quality === 'High' ? 'Medium' : 'Low', true); }
    }
  }
  this.lastFrame = now;
};
Viewer3D.prototype.render = function () {
  var r = this.renderer; if (this.shadowDirty && this.shadowOn) { r.shadowMap.needsUpdate = true; this.shadowDirty = false; }
  this.updateOverlays();
  r.render(this.scene, this.camera);
};

Viewer3D.prototype.resize = function () {
  var w = this.stage.clientWidth, h = this.stage.clientHeight; if (!w || !h) return;
  var scale = { Low: 0.6, Medium: 1, High: 1 }[this.quality], dpr = Math.min(window.devicePixelRatio || 1, this.quality === 'High' ? 2 : 1.25) * scale;
  this.renderer.setPixelRatio(dpr); this.renderer.setSize(w, h, false);
  this.renderer.domElement.style.width = w + 'px'; this.renderer.domElement.style.height = h + 'px';
  this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.invalidate(false);
};
Viewer3D.prototype.applyQuality = function () {
  this.shadowOn = this.quality !== 'Low';
  var ms = this.quality === 'High' ? 2048 : 1024;
  if (this.key.shadow.mapSize.x !== ms) { this.key.shadow.mapSize.set(ms, ms); if (this.key.shadow.map) { this.key.shadow.map.dispose(); this.key.shadow.map = null; } }
  this.key.castShadow = this.shadowOn; this.ground.visible = this.shadowOn;
  this.meshes.forEach(function (m) { m.castShadow = true; m.receiveShadow = true; });
  this.shadowDirty = true;
  if (this.qSel) this.qSel.value = this.quality;
};
Viewer3D.prototype.setQuality = function (q, auto) {
  this.quality = q; if (!auto) { this.qLocked = true; store('v3q', q); } else this.msg('Slow GPU detected: quality lowered to ' + q + '.');
  if (auto) { var s = this; setTimeout(function () { s.msg(''); }, 3500); }
  this.applyQuality(); this.resize();
  this.meshes.forEach(function (m) { if (m.material) m.material.needsUpdate = true; });
  this.invalidate();
};

/* ----- animation helpers */
Viewer3D.prototype.addAnim = function (fn) { this.anims.push(fn); this.schedule(); };
Viewer3D.prototype.stepAnims = function (now) {
  var keep = [], i, any = false;
  for (i = 0; i < this.anims.length; i++) { var a = this.anims[i]; if (a(now)) keep.push(a); }
  this.anims = keep;
  if (this.playState) { this.stepPlay(now); any = true; }
  if (keep.length || any) this.dirty = true;
  return keep.length > 0 || any;
};
Viewer3D.prototype.cancelCam = function () { if (this.camAnim) { this.anims = this.anims.filter(function (a) { return a !== this.camAnim; }, this); this.camAnim = null; } };
Viewer3D.prototype.camTo = function (pos, target, ms, done) {
  var self = this, cam = this.camera, ctl = this.controls; this.cancelCam();
  var p0 = cam.position.clone(), t0 = ctl.target.clone(), off0 = p0.clone().sub(t0), off1 = pos.clone().sub(target), d0 = off0.length(), d1 = off1.length();
  var q = new T.Quaternion().setFromUnitVectors(off0.clone().normalize(), off1.clone().normalize()), qi = new T.Quaternion(), start = performance.now(), dur = ms == null ? 700 : ms;
  if (!dur) { cam.position.copy(pos); ctl.target.copy(target); ctl.update(); this.invalidate(false); return; }
  var a = this.camAnim = function (now) {
    var k = ease((now - start) / dur); qi.identity().slerp(q, k);
    var o = off0.clone().normalize().applyQuaternion(qi).multiplyScalar(d0 + (d1 - d0) * k);
    ctl.target.lerpVectors(t0, target, k); cam.position.copy(ctl.target).add(o); ctl.update();
    if (k >= 1) { self.camAnim = null; if (done) done(); return false; } return true;
  };
  this.addAnim(a);
};
Viewer3D.prototype.animate = function (from, to, ms, fn, done) {   /* generic eased value animation */
  var start = performance.now(), self = this;
  this.addAnim(function (now) { var k = ease((now - start) / ms); fn(from + (to - from) * k); if (k >= 1) { if (done) done(); return false; } return true; });
};

/* ----- bounds / fit / presets */
Viewer3D.prototype.visibleBox = function (filter) {
  var b = new T.Box3(), t = new T.Box3(), any = false;
  this.world.updateMatrixWorld(true);
  this.meshes.forEach(function (m) { if (!m.visible || !m.parent || (filter && !filter(m))) return; if (!m.geometry.boundingBox) m.geometry.computeBoundingBox(); t.copy(m.geometry.boundingBox).applyMatrix4(m.matrixWorld); b.union(t); any = true; });
  return any ? b : null;
};
Viewer3D.prototype.fitInfo = function (box) {
  var c = box.getCenter(new T.Vector3()), r = box.getSize(new T.Vector3()).length() / 2 || 10, fov = this.camera.fov * Math.PI / 180, asp = this.camera.aspect;
  var d = r / Math.sin(Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * asp)) / 2) * 0.98;
  return { c: c, r: r, d: d };
};
Viewer3D.prototype.dirOf = function (name) {
  var d = { iso: [0.8, -1.05, 0.75], top: [0, -0.0004, 1], bottom: [0, -0.0004, -1], front: [0, -1, 0.0004], back: [0, 1, 0.0004], left: [-1, 0, 0.0004], right: [1, 0, 0.0004], isob: [0.7, -0.9, -0.85] }[name] || [0.8, -1.05, 0.75];
  return new T.Vector3(d[0], d[1], d[2]).normalize();
};
Viewer3D.prototype.fit = function (animate, dirName) {
  var box = this.visibleBox(); if (!box) return;
  var f = this.fitInfo(box), dir = dirName ? this.dirOf(dirName) : this.camera.position.clone().sub(this.controls.target).normalize();
  this.near(f.r);
  this.camTo(f.c.clone().add(dir.multiplyScalar(f.d)), f.c, animate === false ? 0 : 650);
};
Viewer3D.prototype.near = function (r) { this.camera.near = Math.max(r / 400, 0.02); this.camera.far = r * 60; this.camera.updateProjectionMatrix(); };
Viewer3D.prototype.view = function (name) { this.curView = name; this.fit(true, name); this.syncViewBtns(); };
Viewer3D.prototype.flyTo = function (box, dirHint) {
  var c = box.getCenter(new T.Vector3()), sz = box.getSize(new T.Vector3()), r = Math.max(sz.length() / 2, 1.2), dir = this.camera.position.clone().sub(this.controls.target).normalize();
  if (dirHint === 'bottom' && dir.z > -0.2) dir = this.dirOf('isob'); else if (dirHint === 'top' && dir.z < 0.2) dir = this.dirOf('iso');
  var fov = this.camera.fov * Math.PI / 180, d = Math.max(r * 4.5, 11) / Math.tan(fov / 2) * 0.5;
  this.camTo(c.clone().add(dir.multiplyScalar(d)), c, 800);
};

/* ----- visibility, explode, section */
Viewer3D.prototype.applyVis = function () {
  var vis = this.vis;
  this.meshes.forEach(function (m) { var u = m.userData, ok = !u.hidden; if (ok && u.tags) for (var i = 0; i < u.tags.length; i++) if (vis[u.tags[i]] === false) { ok = false; break; } m.visible = ok; });
  this.pickables = this.meshes.filter(function (m) { return m.visible && m.userData.pick !== false; });
  this.invalidate(); this.setReadout();
  if (this.cfg.onVis) this.cfg.onVis(this);
};
Viewer3D.prototype.setVis = function (key, on) { this.vis[key] = !!on; this.applyVis(); this.syncTree(); };
Viewer3D.prototype.setExplode = function (e) {
  this.explodeVal = Math.max(0, Math.min(1, e)); if (this.cfg.explode) this.cfg.explode(this, this.explodeVal);
  if (this.exSl) this.exSl.value = Math.round(this.explodeVal * 100);
  if (this.exVal) this.exVal.textContent = Math.round(this.explodeVal * 100) + '%';
  this.invalidate(); this.updateClip(); if (this.dimsOn) this.invalidate(false);
};
Viewer3D.prototype.explodeTo = function (to, ms) {
  this.stopPlay(); var from = this.explodeVal, self = this; this.animate(from, to, ms || 1100, function (v) { self.setExplode(v); }, function () { if (self.cfg.kind === 'housing') self.fit(true); });
};
Viewer3D.prototype.togglePlay = function () { if (this.playState) this.stopPlay(); else this.startPlay(); };
Viewer3D.prototype.startPlay = function () {
  var e = this.explodeVal; this.playState = { stage: e < 0.5 ? 0 : 2, t0: performance.now(), from: e, to: e < 0.5 ? 1 : 0 };
  if (this.playBtn) { this.playBtn.textContent = 'Pause'; this.playBtn.classList.add('on'); } this.schedule();
};
Viewer3D.prototype.stopPlay = function () { if (!this.playState) return; this.playState = null; if (this.playBtn) { this.playBtn.textContent = 'Play'; this.playBtn.classList.remove('on'); } };
Viewer3D.prototype.stepPlay = function (now) {   /* explode -> hold -> collapse -> hold, eased */
  var s = this.playState, t = (now - s.t0);
  if (s.stage === 0 || s.stage === 2) {         /* move */
    var k = ease(t / 1700); this.setExplode(s.from + (s.to - s.from) * k);
    if (k >= 1) { s.stage++; s.t0 = now; }
  } else if (t > 900) { s.stage = (s.stage + 1) % 4; s.t0 = now; s.from = this.explodeVal; s.to = s.stage === 0 ? 1 : 0; }
};
Viewer3D.prototype.updateClip = function () {
  var r = this.renderer;
  if (!this.clipOn) { r.clippingPlanes = []; this.clipHelper.visible = false; this.invalidate(); return; }
  var ax = this.clipAxis || 'z', box = this.clipBox || this.visibleBox(); if (!box) return;
  var n = new T.Vector3(ax === 'x' ? 1 : 0, ax === 'y' ? 1 : 0, ax === 'z' ? 1 : 0), lo = box.min[ax], hi = box.max[ax], pos = lo + (hi - lo) * this.clipT;
  if (this.clipFlip) n.negate();
  this.clipPlane.normal.copy(n); this.clipPlane.constant = -n.dot(new T.Vector3(ax === 'x' ? pos : 0, ax === 'y' ? pos : 0, ax === 'z' ? pos : 0));
  /* three clips the half-space where plane distance < 0 ; keep the side the normal points to */
  r.clippingPlanes = [this.clipPlane]; this.clipHelper.visible = true; this.clipHelper.size = box.getSize(new T.Vector3()).length() * 0.8;
  if (this.clipHelper.position) this.clipHelper.position.set(0, 0, 0);
  this.clipPos = pos; if (this.clipLbl) this.clipLbl.textContent = ax.toUpperCase() + ' = ' + fmt(pos, 1) + ' mm';
  this.invalidate();
};

/* ----- materials toggles */
Viewer3D.prototype.setWire = function (on) { this.wire = on; this.mats.forEach(function (m) { m.wireframe = on; }); this.invalidate(false); };
Viewer3D.prototype.setEdges = function (on) {
  this.edgesOn = on; var self = this;
  this.meshes.forEach(function (m) {
    if (!on) { if (m.userData.edges) m.userData.edges.visible = false; return; }
    if (!m.userData.edges) {
      var g = new T.EdgesGeometry(m.geometry, m.userData.edgeAngle || 28), l = new T.LineSegments(g, new T.LineBasicMaterial({ color: isDark() ? 0xdbe6ff : 0x10151c, transparent: true, opacity: 0.38 }));
      l.raycast = function () { }; l.userData.isEdge = true; m.add(l); m.userData.edges = l; m.userData.pick = m.userData.pick;
    }
    m.userData.edges.visible = true;
  });
  this.invalidate(false);
};

/* ------------------------------------------------------------------ selection / hover / picking */
Viewer3D.prototype.paint = function (p) {
  if (!p) return;
  var st = this.selected === p ? 2 : (this.hovered === p ? 1 : 0), net = this.netSet && this.netSet[p.id];
  p.mats.forEach(function (m) {
    if (!m.emissive) return;
    if (st === 2) { m.emissive.setHex(0x7a3d00); m.emissiveIntensity = 1; }
    else if (st === 1) { m.emissive.setHex(0x16406e); m.emissiveIntensity = 1; }
    else if (net) { m.emissive.setHex(0x00695a); m.emissiveIntensity = 1; }
    else { m.emissive.setHex(p.baseEmissive || 0x000000); m.emissiveIntensity = p.baseEmissive ? 1 : 0; }
  });
  p.meshes.forEach(function (m) { if (this.outline && m === this.outlineFor) { } }, this);
};
Viewer3D.prototype.setHover = function (p) {
  if (p === this.hovered) return; var old = this.hovered; this.hovered = p; this.paint(old); this.paint(p);
  this.stage.style.cursor = this.measure.on ? 'crosshair' : (p ? 'pointer' : ''); this.invalidate(false);
};
Viewer3D.prototype.select = function (p, opts) {
  opts = opts || {}; var old = this.selected; this.selected = p; this.paint(old); this.paint(p);
  if (this.outline) { this.outline.parent && this.outline.parent.remove(this.outline); this.outline = null; }
  if (p && p.meshes[0]) {
    var m = p.meshes[0], g = new T.EdgesGeometry(m.geometry, 18), l = new T.LineSegments(g, new T.LineBasicMaterial({ color: 0xffa21f, depthTest: false, transparent: true, opacity: 0.95 }));
    l.renderOrder = 10; l.raycast = function () { }; m.add(l); this.outline = l; this.outlineFor = m;
  }
  this.showInfo(p);
  if (opts.fly && p) this.flyTo(this.partBox(p), p.side === 'bottom' ? 'bottom' : 'top');
  if (!opts.noUrl && this.cfg.urlState) this.cfg.urlState(this);
  this.setReadout(); this.invalidate(false);
};
Viewer3D.prototype.partBox = function (p) { var b = new T.Box3(), t = new T.Box3(); this.world.updateMatrixWorld(true); p.meshes.forEach(function (m) { if (!m.geometry.boundingBox) m.geometry.computeBoundingBox(); t.copy(m.geometry.boundingBox).applyMatrix4(m.matrixWorld); b.union(t); }); return b; };
Viewer3D.prototype.pointerNdc = function (e) { var r = this.renderer.domElement.getBoundingClientRect(); return new T.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); };
Viewer3D.prototype.hit = function (e) {
  if (!this.pickables) return null;
  var rc = this.rc || (this.rc = new T.Raycaster()); rc.setFromCamera(this.pointerNdc(e), this.camera);
  var hits = rc.intersectObjects(this.pickables, false), pl = this.clipOn ? this.clipPlane : null;
  for (var i = 0; i < hits.length; i++) { if (pl && pl.distanceToPoint(hits[i].point) < 0) continue; return hits[i]; }
  return null;
};
Viewer3D.prototype.doPick = function () {
  var e = this.lastMove; if (!e || this.interacting || this.measure.on && 0) return;
  var h = this.hit(e), p = h ? h.object.userData.part : null;
  this.setHover(p && p.selectable !== false ? p : null);
  if (this.measure.on && h) this.measureHover(h); else if (this.snapDot) this.snapDot.visible = false;
  if (p && !this.measure.on) {
    var r = this.stage.getBoundingClientRect(); this.tip.hidden = false;
    this.tip.innerHTML = '<b>' + esc(p.title) + '</b>' + (p.sub ? '<span>' + esc(p.sub) + '</span>' : '');
    var x = e.clientX - r.left + 14, y = e.clientY - r.top + 14; if (x > r.width - 190) x -= 200; if (y > r.height - 50) y -= 60;
    this.tip.style.left = x + 'px'; this.tip.style.top = y + 'px';
  } else this.tip.hidden = true;
};

Viewer3D.prototype.initInput = function () {
  var self = this, cv = this.renderer.domElement, down = null;
  cv.addEventListener('pointerdown', function (e) { down = { x: e.clientX, y: e.clientY, t: performance.now(), b: e.button }; self.root.focus({ preventScroll: true }); self.tip.hidden = true; });
  cv.addEventListener('pointermove', function (e) {
    self.lastMove = e; if (e.pointerType === 'touch') return;
    if (!self.pickPending) { self.pickPending = true; self.schedule(); }
    if (self.measure.on || !(e.buttons)) { }
  });
  cv.addEventListener('pointerleave', function () { self.setHover(null); self.tip.hidden = true; });
  cv.addEventListener('pointerup', function (e) {
    if (!down) return; var moved = Math.hypot(e.clientX - down.x, e.clientY - down.y), dt = performance.now() - down.t, b = down.b; down = null;
    if (moved > 5 || dt > 600 || b !== 0) return;
    var h = self.hit(e);
    if (self.measure.on) { if (h) self.measureClick(h); return; }
    var p = h ? h.object.userData.part : null;
    if (p && p.selectable === false) p = null;
    var now = performance.now();
    if (p && self.lastClickPart === p && now - self.lastClickT < 380) { self.flyTo(self.partBox(p), p.side === 'bottom' ? 'bottom' : 'top'); }
    else if (!p && self.lastClickT && now - self.lastClickT < 380 && !self.selected) { self.fit(true); }
    self.lastClickPart = p; self.lastClickT = now;
    self.select(p);
  });
  cv.addEventListener('dblclick', function (e) { e.preventDefault(); });
  this.root.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return; var t = e.target; if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA')) { if (e.key === 'Escape') t.blur(); return; }
    var k = e.key, views = ['iso', 'top', 'bottom', 'front', 'back', 'left', 'right'], handled = true;
    if (k >= '1' && k <= '7') self.view(views[+k - 1]);
    else if (k === 'f' || k === 'F') self.fit(true);
    else if (k === 'e' || k === 'E') { if (self.cfg.explode) self.explodeTo(self.explodeVal > 0.5 ? 0 : 1); }
    else if (k === ' ') { if (self.cfg.explode) self.togglePlay(); }
    else if (k === 'm' || k === 'M') self.setMeasure(!self.measure.on);
    else if (k === 'w' || k === 'W') { var c = self.q('wire'); if (c) { c.checked = !c.checked; self.setWire(c.checked); } }
    else if (k === 'Escape') { if (self.measure.pts.length) self.clearMeasure(); else if (self.measure.on) self.setMeasure(false); else if (self.selected) { self.select(null); self.setNet(null); } else if (self.root.classList.contains('v3-fs') && document.exitFullscreen) { } }
    else if (k === 'Delete' || k === 'h' || k === 'H') { if (self.selected) self.hidePart(self.selected); }
    else handled = false;
    if (handled) e.preventDefault();
  });
};
Viewer3D.prototype.q = function (name) { return this.root.querySelector('[data-c="' + name + '"]'); };

/* ------------------------------------------------------------------ toolbar / side panel */
Viewer3D.prototype.buildBar = function () {
  var self = this, bar = this.bar, cfg = this.cfg;
  function grp(label) { var g = el('div', 'v3-grp'); if (label) g.appendChild(el('span', 'v3-lbl', label)); bar.appendChild(g); return g; }
  function btn(g, txt, title, fn, c) { var b = el('button', 'v3-b', txt); b.type = 'button'; b.title = title || ''; b.onclick = fn; if (c) b.setAttribute('data-c', c); g.appendChild(b); return b; }
  function chk(g, txt, title, c, fn, on) { var l = el('label', 'v3-chk'); l.title = title || ''; var i = el('input'); i.type = 'checkbox'; i.checked = !!on; i.setAttribute('data-c', c); i.onchange = function () { fn(i.checked); }; l.appendChild(i); l.appendChild(document.createTextNode(' ' + txt)); g.appendChild(l); return i; }
  var g = grp('View'); this.viewBtns = {};
  [['iso', 'Iso'], ['top', 'Top'], ['bottom', 'Bottom'], ['front', 'Front'], ['back', 'Back'], ['left', 'Left'], ['right', 'Right']].forEach(function (v, i) { self.viewBtns[v[0]] = btn(g, v[1], v[1] + ' view (key ' + (i + 1) + ')', function () { self.view(v[0]); }); });
  btn(g, 'Fit', 'Fit model to view (F)', function () { self.curView = null; self.syncViewBtns(); self.fit(true); });
  if (cfg.explode) {
    g = grp(cfg.explodeLabel || 'Explode');
    var sl = this.exSl = el('input'); sl.type = 'range'; sl.min = 0; sl.max = 100; sl.value = 0; sl.title = 'Explode amount'; sl.className = 'v3-range';
    sl.oninput = function () { self.stopPlay(); self.setExplode(sl.value / 100); }; g.appendChild(sl);
    this.exVal = el('span', 'v3-val', '0%'); g.appendChild(this.exVal);
    btn(g, 'Explode', 'Animate to exploded (E)', function () { self.explodeTo(1); }); btn(g, 'Collapse', 'Animate back', function () { self.explodeTo(0); });
    this.playBtn = btn(g, 'Play', 'Loop explode / collapse (Space)', function () { self.togglePlay(); });
  }
  g = grp('Section');
  chk(g, 'cut', 'Clipping plane', 'clip', function (on) { self.clipOn = on; self.clipBox = on ? self.visibleBox() : null; self.updateClip(); self.secWrap.hidden = !on; });
  var sw = this.secWrap = el('span', 'v3-sec'); sw.hidden = true; g.appendChild(sw);
  var ax = el('select', 'v3-sel'); ['z', 'x', 'y'].forEach(function (a) { var o = el('option', null, a.toUpperCase()); o.value = a; ax.appendChild(o); }); ax.title = 'Cut axis';
  ax.onchange = function () { self.clipAxis = ax.value; self.updateClip(); }; sw.appendChild(ax); this.clipAxis = 'z'; this.clipT = 0.5;
  var cs = el('input'); cs.type = 'range'; cs.min = 0; cs.max = 1000; cs.value = 500; cs.className = 'v3-range'; cs.title = 'Cut position'; cs.oninput = function () { self.clipT = cs.value / 1000; self.updateClip(); }; sw.appendChild(cs);
  var fl = el('button', 'v3-b', 'flip'); fl.type = 'button'; fl.title = 'Flip which side is kept'; fl.onclick = function () { self.clipFlip = !self.clipFlip; self.updateClip(); }; sw.appendChild(fl);
  this.clipLbl = el('span', 'v3-val', ''); sw.appendChild(this.clipLbl);
  g = grp('Show');
  chk(g, 'wire', 'Wireframe (W)', 'wire', function (on) { self.setWire(on); });
  chk(g, 'edges', 'Edge overlay', 'edges', function (on) { self.setEdges(on); });
  chk(g, 'dims', 'Bounding-box dimensions', 'dims', function (on) { self.setDims(on); });
  chk(g, 'grid', 'Ground grid', 'grid', function (on) { self.grid.visible = on; self.invalidate(false); });
  if (cfg.traces) chk(g, 'traces', 'Routed copper traces, mask, gold pads and silkscreen on the board faces (texture from the .kicad_pcb)', 'traces', function (on) { cfg.traces(self, on); }, true);
  if (cfg.shellOpacity) {
    var o = el('label', 'v3-chk', 'shell opacity '); var os = el('input'); os.type = 'range'; os.min = 8; os.max = 100; os.value = 100; os.className = 'v3-range v3-short'; os.title = 'Housing opacity'; os.setAttribute('data-c', 'opacity');
    os.oninput = function () { cfg.shellOpacity(self, os.value / 100); }; o.appendChild(os); g.appendChild(o);
  }
  g = grp('Tools');
  this.measBtn = btn(g, 'Measure', 'Point-to-point distance: click two points (M)', function () { self.setMeasure(!self.measure.on); });
  btn(g, 'Screenshot', 'Download a PNG of the current view', function () { self.screenshot(); });
  btn(g, 'Fullscreen', 'Toggle fullscreen', function () { self.fullscreen(); });
  var qs = this.qSel = el('select', 'v3-sel'); STYLE_KEYS.forEach(function (k) { var o = el('option', null, k); o.value = k; qs.appendChild(o); }); qs.title = 'Render quality: Low = 0.6x resolution, no shadows (for weak GPUs)'; qs.value = this.quality;
  qs.onchange = function () { self.setQuality(qs.value); }; var ql = el('label', 'v3-chk', 'quality '); ql.appendChild(qs); g.appendChild(ql);
  btn(g, '?', 'Show / hide the control hint', function () { self.hintEl.hidden = !self.hintEl.hidden; });
};
Viewer3D.prototype.syncViewBtns = function () { for (var k in this.viewBtns) this.viewBtns[k].classList.toggle('on', k === this.curView); };

Viewer3D.prototype.buildSide = function () {
  var self = this, side = this.side, cfg = this.cfg;
  if (cfg.hasSearch) {
    var sb = el('div', 'v3-search'); var inp = el('input'); inp.type = 'search'; inp.placeholder = 'find part: ref (U1, C12), value, footprint or net'; inp.autocomplete = 'off'; inp.setAttribute('aria-label', 'find part');
    var res = el('div', 'v3-results'); res.hidden = true; sb.appendChild(inp); sb.appendChild(res); side.appendChild(sb);
    var sel = -1, items = [];
    function run() {
      var q = inp.value.trim().toLowerCase(); res.innerHTML = ''; items = []; sel = -1; if (!q) { res.hidden = true; return; }
      var seen = {};
      self.parts.forEach(function (p) { if (!p.ref) return; var s = (p.ref + ' ' + p.val + ' ' + p.fp + ' ' + (p.note || '')).toLowerCase(); var sc = p.ref.toLowerCase() === q ? 0 : p.ref.toLowerCase().indexOf(q) === 0 ? 1 : s.indexOf(q) >= 0 ? 2 : -1; if (sc >= 0) { items.push({ sc: sc, p: p }); seen[p.ref] = 1; } });
      var info = self.info; if (info) {
        Object.keys(info.refs).forEach(function (r) { if (seen[r]) return; var d = info.refs[r], s = (r + ' ' + d.val + ' ' + d.fp).toLowerCase(); if (s.indexOf(q) >= 0) items.push({ sc: r.toLowerCase().indexOf(q) === 0 ? 1 : 3, ref: r, d: d }); });
        Object.keys(info.nets).forEach(function (n) { if (n.toLowerCase().indexOf(q) >= 0) items.push({ sc: n.toLowerCase() === q ? 0 : 4, net: n }); });
      }
      items.sort(function (a, b) { return a.sc - b.sc; }); items = items.slice(0, 14);
      items.forEach(function (it, i) {
        var r = el('div', 'v3-res');
        if (it.net) r.innerHTML = '<b>' + esc(it.net) + '</b><span>net, ' + info.nets[it.net].length + ' pins</span>';
        else if (it.p) r.innerHTML = '<b>' + esc(it.p.ref) + '</b><span>' + esc(it.p.val) + ' &middot; ' + esc(it.p.fp) + ' &middot; ' + esc(it.p.side) + '</span>';
        else r.innerHTML = '<b>' + esc(it.ref) + '</b><span>' + esc(it.d.val) + ' &middot; ' + esc(it.d.fp) + ' &middot; ' + esc(it.d.side) + ' (no 3D body)</span>';
        r.onmousedown = function (ev) { ev.preventDefault(); go(it); }; res.appendChild(r);
      });
      res.hidden = !items.length; if (!items.length) { res.hidden = false; res.innerHTML = '<div class="v3-res muted">no match</div>'; }
    }
    function go(it) { res.hidden = true; if (it.net) { self.setNet(it.net); inp.value = it.net; return; } var p = it.p || self.partByRef(it.ref); if (p) { self.select(p, { fly: true }); inp.value = p.ref; } else if (it.ref) self.selectGhost(it.ref); inp.blur(); }
    inp.addEventListener('input', run); inp.addEventListener('focus', run);
    inp.addEventListener('blur', function () { setTimeout(function () { res.hidden = true; }, 120); });
    inp.addEventListener('keydown', function (e) {
      var rs = res.querySelectorAll('.v3-res');
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rs.length) % Math.max(rs.length, 1); for (var i = 0; i < rs.length; i++) rs[i].classList.toggle('on', i === sel); }
      else if (e.key === 'Enter') { e.preventDefault(); if (!items.length) run(); if (items.length) go(items[Math.max(sel, 0)]); }
      else if (e.key === 'Escape') { res.hidden = true; }
      e.stopPropagation();
    });
    this.searchInp = inp;
  }
  this.treeEl = el('div', 'v3-tree'); side.appendChild(this.treeEl);
  this.infoEl = el('div', 'v3-info'); side.appendChild(this.infoEl);
  this.buildTree(); this.showInfo(null);
};
Viewer3D.prototype.buildTree = function () {
  var self = this, t = this.treeEl, rows = this.cfg.tree(this);
  t.innerHTML = '<div class="v3-h">Parts <span class="v3-links"><a href="#" data-a="all">all</a> <a href="#" data-a="none">none</a> <a href="#" data-a="restore" hidden>restore hidden</a></span></div>';
  this.treeRows = {};
  rows.forEach(function (r) {
    var l = el('label', 'v3-trow' + (r.indent ? ' ind' : '')); var i = el('input'); i.type = 'checkbox'; i.checked = self.vis[r.key] !== false;
    var sw = el('span', 'v3-sw'); sw.style.background = r.color || 'transparent'; if (!r.color) sw.style.visibility = 'hidden';
    l.appendChild(i); l.appendChild(sw); l.appendChild(el('span', 'v3-tl', esc(r.label))); if (r.n != null) l.appendChild(el('em', null, String(r.n)));
    i.onchange = function () { self.vis[r.key] = i.checked; self.applyVis(); };
    l.onclick = function (e) { if (e.shiftKey && e.target !== i) { e.preventDefault(); self.solo(r.key); } };
    l.title = r.title || (r.label + ' (shift-click: show only this)');
    t.appendChild(l); self.treeRows[r.key] = i;
  });
  t.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-a]'); if (!a) return; e.preventDefault(); var act = a.getAttribute('data-a');
    if (act === 'restore') { self.restoreHidden(); return; }
    rows.forEach(function (r) { self.vis[r.key] = act === 'all'; }); self.syncTree(); self.applyVis();
  });
};
Viewer3D.prototype.syncTree = function () { for (var k in this.treeRows) this.treeRows[k].checked = this.vis[k] !== false; };
Viewer3D.prototype.solo = function (key) {
  var self = this; Object.keys(this.treeRows).forEach(function (k) { self.vis[k] = (k === key); });
  if (this.treeRows.pcb && ['front', 'back', 'pcb'].indexOf(key) < 0) this.vis.pcb = true;
  if (/^(cat_|lens$)/.test(key)) { this.vis.side_top = true; this.vis.side_bottom = true; }
  this.syncTree(); this.applyVis();
};
Viewer3D.prototype.hidePart = function (p) {
  p.meshes.forEach(function (m) { m.userData.hidden = true; }); this.hiddenParts.push(p); if (this.selected === p) this.select(null);
  var a = this.treeEl.querySelector('a[data-a="restore"]'); if (a) a.hidden = false; this.applyVis();
};
Viewer3D.prototype.restoreHidden = function () {
  this.hiddenParts.forEach(function (p) { p.meshes.forEach(function (m) { m.userData.hidden = false; }); }); this.hiddenParts = [];
  var a = this.treeEl.querySelector('a[data-a="restore"]'); if (a) a.hidden = true; this.applyVis();
};

/* ----- part registry */
Viewer3D.prototype.addPart = function (o) {   /* o: {id, ref, title, sub, meshes, tags, side, cat, ...} */
  var p = o; p.id = p.id || ('p' + this.parts.length); p.mats = []; var self = this;
  p.meshes.forEach(function (m) {
    m.userData.part = p; m.userData.tags = p.tags || []; self.meshes.push(m);
    if (m.material && p.mats.indexOf(m.material) < 0) p.mats.push(m.material);
    if (self.mats.indexOf(m.material) < 0) self.mats.push(m.material);
  });
  this.parts.push(p); (this.partMap || (this.partMap = {}))[p.id] = p; if (p.ref) (this.refMap || (this.refMap = {}))[p.ref] = p; return p;
};
Viewer3D.prototype.partByRef = function (r) { return this.refMap && this.refMap[r]; };

/* ----- info panel */
Viewer3D.prototype.showInfo = function (p) {
  var box = this.infoEl, self = this; if (!box) return;
  if (!p) { box.innerHTML = '<div class="v3-h">Selection</div><div class="muted v3-empty">' + (this.cfg.hasSearch ? 'Click a component, or search for one, to see its picture, buy link, placement and pin nets.' : 'Click a part to inspect it.') + '</div>'; return; }
  var d = (this.info && p.ref && this.info.refs[p.ref]) || null, h = '<div class="v3-h">Selection <span class="v3-links"><a href="#" data-a="fly">fly to</a> <a href="#" data-a="hide">hide</a> <a href="#" data-a="clear">clear</a></span></div>';
  /* thumbnail card + secondary facts (assets/partthumbs.js); falls back to the plain heading if that script is absent */
  if (window.PartThumbs) h += PartThumbs.panelHead(p, d, p.ref); else h += '<div class="v3-ref">' + esc(p.ref || p.title) + (d ? ' <small>' + esc(d.val) + '</small>' : '') + '</div>';
  var rows = [], more = [];
  if (d) {
    rows.push(['footprint', '<code>' + esc(d.fp) + '</code>'], ['side', esc(d.side) + (d.side === 'bottom' ? ' (away from lens)' : ' (lens side)')],
      ['position', 'x ' + fmt(d.x, 2) + ', y ' + fmt(d.y, 2) + ' mm, rot ' + fmt(d.rot || 0, 0) + '&deg;']);
    if (d.note) more.push(['role', esc(d.note)]);
  } else { rows.push(['solid', '<code>' + esc(p.name || p.title) + '</code>']); if (p.sub) more.push(['info', esc(p.sub)]); }
  var b = this.partBox(p), sz = b.getSize(new T.Vector3());
  rows.push(['body size', fmt(sz.x, 2) + ' &times; ' + fmt(sz.y, 2) + ' &times; ' + fmt(sz.z, 2) + ' mm']);
  var kv = function (a) { return '<table class="v3-kv">' + a.map(function (r) { return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>'; }).join('') + '</table>'; };
  h += '<div class="v3-sec">Placement</div>' + kv(rows) + (more.length ? '<details class="v3-det"><summary>More about this part</summary>' + kv(more) + '</details>' : '');
  if (d && d.pins) {
    var pins = Object.keys(d.pins).sort(function (a, b) { var na = parseInt(a.replace(/\D/g, '')), nb = parseInt(b.replace(/\D/g, '')); return (isNaN(na) || isNaN(nb) || na === nb) ? (a < b ? -1 : 1) : na - nb; });
    h += '<div class="v3-h2 v3-sec">Pins and nets (' + pins.length + ')' + (pins.length > 12 ? ' <input type="search" class="v3-pf" placeholder="filter pin / net"' + '>' : '') + '</div><div class="v3-pins"><table class="v3-kv">' +
      pins.map(function (pn) { var n = d.pins[pn]; return '<tr data-s="' + esc((pn + ' ' + n).toLowerCase()) + '"><th>' + esc(pn) + '</th><td><a href="#" class="v3-net' + (self.net === n ? ' on' : '') + '" data-net="' + esc(n) + '" title="highlight every part on this net">' + esc(n) + '</a> <em>' + (self.info.nets[n] ? self.info.nets[n].length : '') + '</em></td></tr>'; }).join('') + '</table></div>';
  }
  box.innerHTML = h;
  box.onclick = function (e) {
    var a = e.target.closest && e.target.closest('a'); if (!a) return;
    var act = a.getAttribute('data-a'), net = a.getAttribute('data-net');
    if (net != null) { e.preventDefault(); self.setNet(self.net === net ? null : net); self.showInfo(self.selected); return; }
    if (!act) return; e.preventDefault();
    if (act === 'fly') self.flyTo(self.partBox(p), p.side === 'bottom' ? 'bottom' : 'top'); else if (act === 'hide') self.hidePart(p); else if (act === 'clear') { self.select(null); self.setNet(null); }
  };
  var pf = box.querySelector('.v3-pf'); if (pf) pf.oninput = function () { var q = pf.value.toLowerCase(); [].forEach.call(box.querySelectorAll('.v3-pins tr'), function (tr) { tr.style.display = tr.getAttribute('data-s').indexOf(q) >= 0 ? '' : 'none'; }); };
};
Viewer3D.prototype.selectGhost = function (ref) {   /* component without a 3D body (test points, mounting holes): fly to its location and show data */
  var d = this.info.refs[ref]; if (!d || d.x == null) return;
  var z = d.side === 'bottom' ? -0.3 : 1.8, v = new T.Vector3(d.x, d.y, z); if (this.cfg.pcbToWorld) v = this.cfg.pcbToWorld(this, v);
  this.select(null); this.showGhost(ref, d, v);
  var dir = this.camera.position.clone().sub(this.controls.target).normalize(); if (d.side === 'bottom' && dir.z > -0.2) dir = this.dirOf('isob'); else if (d.side !== 'bottom' && dir.z < 0.2) dir = this.dirOf('iso');
  this.camTo(v.clone().add(dir.multiplyScalar(14)), v, 800);
};
Viewer3D.prototype.showGhost = function (ref, d, v) {
  var fake = { ref: ref, title: ref, meshes: [], side: d.side, name: d.fp }; var save = this.partBox; this.partBox = function () { return new T.Box3(v.clone(), v.clone()); };
  this.showInfo(fake); this.partBox = save;
  if (!this.ghost) { this.ghost = new T.Mesh(new T.SphereGeometry(0.5, 16, 12), new T.MeshBasicMaterial({ color: 0xffa21f, depthTest: false })); this.ghost.renderOrder = 11; this.overlay.add(this.ghost); }
  this.ghost.position.copy(v); this.ghost.visible = true; this.ghost.scale.setScalar(Math.max(this.camera.position.distanceTo(v), 10) * 0.04); this.invalidate(false);
};

/* ----- nets */
Viewer3D.prototype.setNet = function (name) {
  var old = this.netSet, self = this; this.net = name; this.netSet = null;
  if (this.netLines) { this.overlay.remove(this.netLines); this.netLines.geometry.dispose(); this.netLines = null; }
  if (name && this.info && this.info.nets[name]) {
    var set = {}, members = [];
    this.info.nets[name].forEach(function (pp) { var r = pp.substring(0, pp.lastIndexOf('.')), p = self.partByRef(r); if (p) { set[p.id] = 1; if (members.indexOf(p) < 0) members.push(p); } });
    this.netSet = set; this.netMembers = members;
    this.netLines = new T.LineSegments(new T.BufferGeometry(), new T.LineBasicMaterial({ color: 0x19e0c4, depthTest: false, transparent: true, opacity: 0.85 })); this.netLines.renderOrder = 9; this.netLines.frustumCulled = false; this.overlay.add(this.netLines);
    this.readoutNet = name + ': ' + this.info.nets[name].length + ' pins on ' + members.length + ' parts';
  } else this.readoutNet = '';
  [old, this.netSet].forEach(function (s) { if (s) for (var id in s) self.paint(self.partMap[id]); });
  this.setReadout(); if (this.cfg.urlState) this.cfg.urlState(this); this.invalidate(false);
};
Viewer3D.prototype.updateNetLines = function () {
  if (!this.netLines || !this.netMembers) return;
  var hub = this.selected || this.netMembers[0], hc = this.partBox(hub).getCenter(new T.Vector3()), pts = [], self = this;
  this.netMembers.forEach(function (p) { if (p === hub || !p.meshes[0].visible) return; var c = self.partBox(p).getCenter(new T.Vector3()); pts.push(hc.x, hc.y, hc.z, c.x, c.y, c.z); });
  this.netLines.geometry.setAttribute('position', new T.BufferAttribute(new Float32Array(pts), 3));
};

/* ----- readout, dims, measure, overlays */
Viewer3D.prototype.setReadout = function () {
  var parts = [], box = this.visibleBox(); if (this.cfg.readout) parts = this.cfg.readout(this, box);
  else if (box) { var s = box.getSize(new T.Vector3()); parts.push('visible extent ' + fmt(s.x) + ' &times; ' + fmt(s.y) + ' &times; ' + fmt(s.z) + ' mm'); }
  if (this.readoutNet) parts.push('net ' + esc(this.readoutNet));
  if (this.selected) parts.push('selected ' + esc(this.selected.ref || this.selected.title));
  this.readout.innerHTML = parts.join(' <i>|</i> ');
};
Viewer3D.prototype.setDims = function (on) {
  this.dimsOn = on; this.labels.querySelectorAll('.v3-dim').forEach(function (n) { n.remove(); });
  if (this.dimBox) { this.overlay.remove(this.dimBox); this.dimBox = null; }
  if (on) {
    this.dimBox = new T.LineSegments(new T.BufferGeometry(), new T.LineBasicMaterial({ color: 0xffd25a, depthTest: false, transparent: true, opacity: 0.8 })); this.dimBox.frustumCulled = false; this.dimBox.renderOrder = 8; this.overlay.add(this.dimBox);
    this.dimLbl = ['x', 'y', 'z'].map(function (a) { var d = el('div', 'v3-dim'); this.labels.appendChild(d); return d; }, this);
  }
  this.invalidate(false);
};
Viewer3D.prototype.updateOverlays = function () {
  var self = this, w = this.stage.clientWidth, h = this.stage.clientHeight, v = new T.Vector3();
  function proj(p) { v.copy(p).project(self.camera); return [(v.x * .5 + .5) * w, (-v.y * .5 + .5) * h, v.z < 1]; }
  if (this.netLines) this.updateNetLines();
  if (this.dimsOn && this.dimBox) {
    var b = (this.selected ? this.partBox(this.selected) : this.visibleBox(this.cfg.dimFilter)) || this.visibleBox();
    if (b) {
      var mn = b.min, mx = b.max, c = [[mn.x, mn.y, mn.z], [mx.x, mn.y, mn.z], [mx.x, mx.y, mn.z], [mn.x, mx.y, mn.z], [mn.x, mn.y, mx.z], [mx.x, mn.y, mx.z], [mx.x, mx.y, mx.z], [mn.x, mx.y, mx.z]], e = [0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4, 0, 4, 1, 5, 2, 6, 3, 7], arr = [];
      e.forEach(function (i) { arr.push(c[i][0], c[i][1], c[i][2]); });
      this.dimBox.geometry.setAttribute('position', new T.BufferAttribute(new Float32Array(arr), 3));
      var sz = b.getSize(new T.Vector3()), mids = [new T.Vector3((mn.x + mx.x) / 2, mn.y, mn.z), new T.Vector3(mx.x, (mn.y + mx.y) / 2, mn.z), new T.Vector3(mn.x, mn.y, (mn.z + mx.z) / 2)], vals = [sz.x, sz.y, sz.z], nm = ['X', 'Y', 'Z'];
      this.dimLbl.forEach(function (d, i) { var p = proj(mids[i]); d.style.display = p[2] ? '' : 'none'; d.style.left = p[0] + 'px'; d.style.top = p[1] + 'px'; d.textContent = nm[i] + ' ' + fmt(vals[i], vals[i] < 10 ? 2 : 1) + ' mm'; });
    }
  }
  if (this.measure.pts.length) this.updateMeasureViz(proj);
  if (this.ghost && this.ghost.visible) this.ghost.scale.setScalar(Math.max(this.camera.position.distanceTo(this.ghost.position), 8) * 0.012);
};

/* measure */
Viewer3D.prototype.setMeasure = function (on) {
  this.measure.on = on; if (this.measBtn) this.measBtn.classList.toggle('on', on); this.stage.style.cursor = on ? 'crosshair' : '';
  if (on) { this.msg('Measure: click two points on the model (snaps to nearby vertices). Esc clears.'); var s = this; clearTimeout(this._mt); this._mt = setTimeout(function () { if (s.msgEl.textContent.indexOf('Measure') === 0) s.msg(''); }, 4500); }
  else { this.clearMeasure(); this.msg(''); }
};
Viewer3D.prototype.snapPoint = function (h) {
  var m = h.object, g = m.geometry, pa = g.attributes.position, f = h.face, local = m.worldToLocal(h.point.clone()), best = null, bd = 1e9;
  [f.a, f.b, f.c].forEach(function (i) { var vtx = new T.Vector3(pa.getX(i), pa.getY(i), pa.getZ(i)), d = vtx.distanceTo(local); if (d < bd) { bd = d; best = vtx; } });
  var tol = Math.max(0.6, this.camera.position.distanceTo(h.point) * 0.012);
  return { obj: m, local: bd < tol ? best : local, snapped: bd < tol };
};
Viewer3D.prototype.measureHover = function (h) {
  var s = this.snapPoint(h); if (!this.snapDot) { this.snapDot = new T.Mesh(new T.SphereGeometry(1, 12, 8), new T.MeshBasicMaterial({ color: 0xffffff, depthTest: false })); this.snapDot.renderOrder = 12; this.overlay.add(this.snapDot); }
  var wp = s.obj.localToWorld(s.local.clone()); this.snapDot.position.copy(wp); this.snapDot.visible = true; this.snapDot.material.color.setHex(s.snapped ? 0x19e0c4 : 0xffffff);
  this.snapDot.scale.setScalar(this.camera.position.distanceTo(wp) * 0.008); this.invalidate(false);
};
Viewer3D.prototype.measureClick = function (h) {
  if (this.measure.pts.length >= 2) this.clearMeasure(true);
  this.measure.pts.push(this.snapPoint(h));
  if (!this.measure.objs.length) {
    var line = new T.Line(new T.BufferGeometry().setFromPoints([new T.Vector3(), new T.Vector3()]), new T.LineBasicMaterial({ color: 0xffd25a, depthTest: false })); line.renderOrder = 12; line.frustumCulled = false;
    this.overlay.add(line); this.measure.objs.push(line);
    for (var i = 0; i < 2; i++) { var s = new T.Mesh(new T.SphereGeometry(1, 12, 8), new T.MeshBasicMaterial({ color: 0xffd25a, depthTest: false })); s.renderOrder = 13; this.overlay.add(s); this.measure.objs.push(s); }
    this.measure.lbl = el('div', 'v3-dim v3-mlbl'); this.labels.appendChild(this.measure.lbl);
  }
  this.invalidate(false);
};
Viewer3D.prototype.clearMeasure = function (keepOn) {
  this.measure.pts = []; var s = this; this.measure.objs.forEach(function (o) { s.overlay.remove(o); }); this.measure.objs = [];
  if (this.measure.lbl) { this.measure.lbl.remove(); this.measure.lbl = null; } if (this.snapDot) this.snapDot.visible = false; this.invalidate(false);
};
Viewer3D.prototype.updateMeasureViz = function (proj) {
  var pts = this.measure.pts, o = this.measure.objs; if (!o.length) return;
  var w = pts.map(function (p) { return p.obj.localToWorld(p.local.clone()); }), cam = this.camera;
  o[1].position.copy(w[0]); o[1].scale.setScalar(cam.position.distanceTo(w[0]) * 0.007); o[1].visible = true;
  if (w[1]) { o[2].position.copy(w[1]); o[2].scale.setScalar(cam.position.distanceTo(w[1]) * 0.007); o[2].visible = true; o[0].geometry.setFromPoints([w[0], w[1]]); o[0].visible = true;
    var d = w[0].distanceTo(w[1]), dv = w[1].clone().sub(w[0]), mid = w[0].clone().add(w[1]).multiplyScalar(.5), p = proj(mid);
    this.measure.lbl.style.display = ''; this.measure.lbl.style.left = p[0] + 'px'; this.measure.lbl.style.top = p[1] + 'px';
    this.measure.lbl.innerHTML = '<b>' + fmt(d, 2) + ' mm</b> <small>dx ' + fmt(Math.abs(dv.x), 2) + ' dy ' + fmt(Math.abs(dv.y), 2) + ' dz ' + fmt(Math.abs(dv.z), 2) + '</small>';
  } else { o[2].visible = false; o[0].visible = false; this.measure.lbl.style.display = 'none'; }
};

/* screenshot / fullscreen */
Viewer3D.prototype.screenshot = function () {
  var self = this; this.dirty = true; this.shadowDirty = true; this.render();
  var cv = this.renderer.domElement;
  function save(blob) {
    if (!blob) { self.msg('Screenshot failed (the browser blocked canvas export).'); return; }
    var a = document.createElement('a'), url = URL.createObjectURL(blob); a.href = url; a.download = 'apriltag-cam-' + self.cfg.kind + (self.selected && self.selected.ref ? '-' + self.selected.ref : '') + '.png'; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 800); self.msg('Saved ' + a.download + ' (' + cv.width + '×' + cv.height + ')'); setTimeout(function () { self.msg(''); }, 2500);
  }
  if (cv.toBlob) cv.toBlob(save, 'image/png'); else save(null);
};
Viewer3D.prototype.fullscreen = function () {
  var r = this.root;
  if (document.fullscreenElement === r) { document.exitFullscreen(); return; }
  if (r.requestFullscreen) { var p = r.requestFullscreen(); if (p && p.catch) p.catch(function () { r.classList.toggle('v3-fs'); }); }
  else r.classList.toggle('v3-fs');
  var s = this; setTimeout(function () { s.resize(); }, 120);
};
Viewer3D.prototype.theme = function () {
  var d = isDark(); this.root.classList.toggle('v3-light', !d); this.ground.material.opacity = d ? 0.38 : 0.2;
  if (this.edgesOn) this.meshes.forEach(function (m) { if (m.userData.edges) m.userData.edges.material.color.setHex(d ? 0xdbe6ff : 0x10151c); });
  this.invalidate(false);
};
Viewer3D.prototype.finishModel = function () {
  /* ground + shadow camera sized to the model; call after the model is built */
  var box = this.visibleBox(); if (!box) return; var s = box.getSize(new T.Vector3()), c = box.getCenter(new T.Vector3()), R = s.length() * 0.9 + 20, ex = this.cfg.shadowExtent || 1.4;
  this.ground.scale.set(R * 3, R * 3, 1); this.ground.position.set(c.x, c.y, box.min.z - 0.05);
  this.grid.scale.setScalar(R * 2.4); this.grid.position.set(c.x, c.y, box.min.z - 0.04);
  var sh = this.key.shadow.camera; var rr = R * ex; sh.left = -rr; sh.right = rr; sh.top = rr; sh.bottom = -rr; sh.near = 1; sh.far = R * 8; sh.updateProjectionMatrix();
  this.key.position.set(c.x + R * 0.5, c.y - R * 0.7, c.z + R * 1.3); this.key.target.position.copy(c); this.key.target.updateMatrixWorld();
  this.theme();
};

/* ------------------------------------------------------------------ model building */
var CATS = [['cap', 'Capacitors', '#c4a068'], ['res', 'Resistors', '#2b2b2e'], ['ind', 'Inductors / ferrites', '#6b6b72'], ['led', 'LEDs', '#d23c32'], ['ic', 'ICs', '#3a3a40'], ['conn', 'Connectors / switches', '#bac0c8'], ['xtal', 'Crystal / oscillator', '#9aa'], ['tp', 'Test points', '#d6b25a'], ['other', 'Other', '#707078']];
function catOf(ref, name, info) {
  if (ref && info && info.refs[ref]) { var k = info.refs[ref].k; if (k === 'mech') return 'other'; return k; }
  if (/^C_/.test(name)) return 'cap'; if (/^R_/.test(name)) return 'res'; if (/^(L_|FB)/.test(name)) return 'ind'; if (/^LED/.test(name)) return 'led';
  if (/USB|Pin|SW|Header/i.test(name)) return 'conn'; if (/Crystal|Oscillator/i.test(name)) return 'xtal'; if (/TestPoint/i.test(name)) return 'tp'; return 'ic';
}
function matFor(cat, c) {
  var col = lin((c[0] << 16) | (c[1] << 8) | c[2]), o = { color: col, roughness: 0.55, metalness: 0.05 };
  if (cat === 'conn') { o.metalness = 0.9; o.roughness = 0.28; }
  else if (cat === 'ic') { o.roughness = 0.38; o.clearcoat = 0.35; o.clearcoatRoughness = 0.4; }
  else if (cat === 'cap') { o.roughness = 0.65; o.metalness = 0.05; }
  else if (cat === 'res') { o.roughness = 0.45; }
  else if (cat === 'ind') { o.roughness = 0.4; o.metalness = 0.35; }
  else if (cat === 'led') { o.roughness = 0.2; o.emissive = lin(0x5a0f0a); o.emissiveIntensity = 0.6; }
  else if (cat === 'xtal') { o.metalness = 0.8; o.roughness = 0.3; }
  o.side = T.DoubleSide; o.envMapIntensity = 0.85;
  return new T.MeshPhysicalMaterial(o);
}

/* PCB assembly: returns {group, board, tops, bottoms, lens} and registers parts on the viewer */
function buildPcb(v, M, pcbRoot) {
  var P = M.pcb, info = P.info || null, g = {}, parts = P.parts;
  v.info = info;
  if (!parts) {   /* legacy data without per-solid ranges: one pseudo part per group */
    parts = []; for (var k in P.groups) parts.push({ g: k, ref: null, name: k + ' group', v: 0, vn: -1, i: 0, in: -1, c: k === 'board' ? [12, 110, 62] : [90, 90, 96] });
  }
  for (var k2 in P.groups) { var G = P.groups[k2]; g[k2] = { pos: b64buf(G.pos, Float32Array), idx: b64buf(G.idx, Uint32Array) }; }
  var ctr = { top: new T.Group(), bottom: new T.Group(), board: new T.Group() }; ctr.top.name = 'topParts'; ctr.bottom.name = 'bottomParts';
  pcbRoot.add(ctr.board, ctr.top, ctr.bottom);
  var boardColor = lin(0x0b5d33), counts = { board: 0, top: 0, bottom: 0 }, cc = {};
  /* one viewer part per reference designator; the colour groups of a model (body, leads, balls, glass ...) are separate meshes of the same part */
  var byRef = {}, order = [];
  parts.forEach(function (pt) {
    var G = g[pt.g]; if (!G) return;
    var n = pt.in < 0 ? G.idx.length : pt.in, geo = flatGeom(G.pos, G.idx, pt.i, n), isBoard = pt.g === 'board', mat, cat;
    if (isBoard) {
      mat = new T.MeshPhysicalMaterial({ color: boardColor, roughness: 0.42, metalness: 0.0, clearcoat: 0.7, clearcoatRoughness: 0.28, side: T.DoubleSide, envMapIntensity: 0.9 }); cat = 'board';
    } else { cat = pt.ref === 'LH1' ? 'lens' : catOf(pt.ref, pt.name, info); mat = matFor(cat, pt.c); }
    var m = new T.Mesh(geo, mat); m.castShadow = true; m.receiveShadow = true; if (!isBoard) m.userData.edgeAngle = 30;
    (isBoard ? ctr.board : ctr[pt.g]).add(m);
    var key = isBoard ? '__board' : (pt.ref || pt.name), e = byRef[key];
    if (!e) { e = byRef[key] = { pt: pt, cat: cat, isBoard: isBoard, meshes: [] }; order.push(key); }
    e.meshes.push(m);
  });
  order.forEach(function (key) {
    var e = byRef[key], pt = e.pt, isBoard = e.isBoard, cat = e.cat, d = info && pt.ref ? info.refs[pt.ref] : null, side = isBoard ? 'both' : pt.g;
    var tags = isBoard ? ['pcb', 'board'] : ['pcb', 'side_' + pt.g, 'cat_' + cat];
    if (cat === 'lens') tags = ['pcb', 'side_top', 'lens'];
    var o = { ref: pt.ref || null, name: pt.name, title: isBoard ? 'PCB (4-layer, 48 x 48 mm)' : (cat === 'lens' ? 'M12 lens module (LH1)' : (pt.ref || pt.name)),
      sub: d ? (d.val + ' · ' + d.fp + ' · ' + d.side) : (isBoard ? 'FR-4 board body (copper is the texture layer)' : pt.name),
      meshes: e.meshes, tags: tags, side: side, cat: cat, val: d ? d.val : '', fp: d ? d.fp : (pt.name || ''), note: d && d.note, selectable: true, kind: isBoard ? 'board' : 'component' };
    if (cat === 'lens') { o.id = 'lens'; o.sub = '20 mm S-mount holder, M12x0.5 barrel with hex lock nut and 6-element glass stack; axis at sensor U10'; }
    v.addPart(o);
    counts[pt.g]++; cc[cat] = (cc[cat] || 0) + 1;
  });
  var topZ = P.board_z[1], botZ = P.board_z[0];
  if (window.PCB3D) PCB3D.attach(v, ctr.board, topZ, botZ);
  return { groups: ctr, counts: counts, cc: cc, topZ: topZ, botZ: botZ };
}

function treeRows(v, extra, pc) {
  var rows = extra || [];
  rows.push({ key: 'board', label: 'PCB board body', color: '#0b5d33', n: 1 }, { key: 'lens', label: 'M12 lens module', color: '#8a8f98' });
  rows.push({ key: 'side_top', label: 'Top side (lens side)', n: pc.counts.top, group: 1 }, { key: 'side_bottom', label: 'Bottom side', n: pc.counts.bottom, group: 1 });
  CATS.forEach(function (c) { if (pc.cc[c[0]]) rows.push({ key: 'cat_' + c[0], label: c[1], color: c[2], n: pc.cc[c[0]], indent: 1 }); });
  return rows;
}

/* ----- housing viewer */
function setupHousing(v) {
  var M = window.MODELS, H = M.housing, Z = M.housing_z || { split: 8, pcb_bottom: 6.4 };
  var shell = function (b64, hex, name) {
    var geo = creasedGeom(b64buf(b64, Float32Array), 42);
    var mat = new T.MeshPhysicalMaterial({ color: lin(hex), roughness: 0.7, metalness: 0.0, clearcoat: 0.0, side: T.DoubleSide, envMapIntensity: 0.85 });
    var m = new T.Mesh(geo, mat); m.castShadow = true; m.receiveShadow = true; m.userData.edgeAngle = 35; m.name = name; return m;
  };
  var front = H.front && shell(H.front.pos, 0x060607, 'front'), back = H.back && shell(H.back.pos, 0x070708, 'back');
  v.shells = [];
  var frontG = new T.Group(), pcbG = new T.Group(); frontG.position.z = Z.split; pcbG.position.z = Z.pcb_bottom; v.world.add(back || new T.Group(), frontG, pcbG);
  if (front) { frontG.add(front); v.addPart({ id: 'front', title: 'Front cover', sub: 'front.stl, 3D-printed, snaps over the back shell with a lap joint', name: 'front.stl', meshes: [front], tags: ['front'], side: 'top', cat: 'shell', kind: 'housing' }); v.shells.push(front); }
  if (back) { v.addPart({ id: 'back', title: 'Back shell', sub: 'back.stl, 3D-printed, holds the PCB on four M2 posts, USB-C opening in the left wall', name: 'back.stl', meshes: [back], tags: ['back'], side: 'bottom', cat: 'shell', kind: 'housing' }); v.shells.push(back); }
  var pc = null;
  if (M.pcb) pc = buildPcb(v, M, pcbG);
  v.pcbG = pcbG; v.frontG = frontG; v.pc = pc;
  v.cfg.tree = function (vv) {
    var rows = [{ key: 'front', label: 'Front cover', color: '#1a1a1d' }, { key: 'back', label: 'Back shell', color: '#232326' }];
    if (!pc) return rows; rows.push({ key: 'pcb', label: 'PCB assembly', group: 1 }); return treeRows(vv, rows, pc).map(function (r) { if (r.key !== 'pcb' && r.key !== 'front' && r.key !== 'back') r.indent = 1; return r; });
  };
  v.cfg.soloKeep = pc ? ['pcb'] : [];
  v.cfg.shellOpacity = function (vv, o) {
    vv.shells.forEach(function (m) { var t = o < 0.99; m.material.transparent = t; m.material.opacity = o; m.material.depthWrite = !t || o > 0.6; m.material.needsUpdate = true; m.renderOrder = t ? 2 : 0; });
    vv.invalidate();
  };
  v.cfg.explode = function (vv, e) { frontG.position.z = Z.split + e * 52; pcbG.position.z = Z.pcb_bottom + e * 14; if (vv.guides) { vv.guides.material.opacity = Math.min(1, e * 2) * 0.7; vv.guides.visible = e > 0.02; } };
  /* dashed screw guides through the four M2 positions */
  var gp = []; [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(function (s) { gp.push(s[0] * 20.5, s[1] * 20.5, 2, s[0] * 20.5, s[1] * 20.5, 70); });
  var gg = new T.BufferGeometry(); gg.setAttribute('position', new T.BufferAttribute(new Float32Array(gp), 3));
  v.guides = new T.LineSegments(gg, new T.LineDashedMaterial({ color: 0xc8d4ee, dashSize: 1.6, gapSize: 1.4, transparent: true, opacity: 0 })); v.guides.computeLineDistances(); v.guides.visible = false; v.scene.add(v.guides);
  v.cfg.readout = function (vv) {
    var out = [], hb = vv.visibleBox(function (m) { return m.userData.part && m.userData.part.kind === 'housing'; });
    var asm = vv.assembledHousing || (vv.assembledHousing = (function () { var pf = frontG.position.z, pp = pcbG.position.z; frontG.position.z = Z.split; pcbG.position.z = Z.pcb_bottom; var b = vv.visibleBox(function (m) { return m.userData.part && m.userData.part.kind === 'housing'; }); var b2 = vv.visibleBox(function (m) { return m.userData.part && m.userData.part.kind !== 'housing'; }); frontG.position.z = pf; pcbG.position.z = pp; return [b, b2]; })());
    if (asm[0]) { var s = asm[0].getSize(new T.Vector3()); out.push('housing (assembled) <b>' + fmt(s.x) + ' &times; ' + fmt(s.y) + ' &times; ' + fmt(s.z) + ' mm</b>'); }
    if (asm[1]) { var s2 = asm[1].getSize(new T.Vector3()); out.push('PCB + lens <b>' + fmt(Math.min(s2.x, 48.0)) + ' &times; ' + fmt(Math.min(s2.y, 48.0)) + ' mm</b> board, ' + fmt(s2.z) + ' mm tall'); }
    return out;
  };
  v.cfg.dimFilter = null;
  v.cfg.pcbToWorld = function (vv, p) { return p.clone().add(new T.Vector3(0, 0, pcbG.position.z)); };
  v.cfg.urlState = function (vv) { urlSet('h', vv); };
  v.finishModel();
}

/* ----- PCB viewer */
function setupPcb(v) {
  var M = window.MODELS, root = new T.Group(); v.world.add(root);
  var pc = buildPcb(v, M, root); v.pc = pc;
  v.cfg.tree = function (vv) { return treeRows(vv, [], pc); };
  v.cfg.explode = function (vv, e) { pc.groups.top.position.z = e * 9; pc.groups.bottom.position.z = -e * 9; };
  v.cfg.explodeLabel = 'Layers';
  v.cfg.readout = function (vv) {
    var b = vv.visibleBox(function (m) { return m.userData.part && m.userData.part.kind === 'board'; }), out = [];
    if (b) { var s = b.getSize(new T.Vector3()); out.push('board <b>' + fmt(s.x) + ' &times; ' + fmt(s.y) + ' &times; ' + fmt(s.z, 2) + ' mm</b>'); }
    var a = vv.visibleBox(); if (a) out.push('with parts ' + fmt(a.getSize(new T.Vector3()).z) + ' mm thick');
    out.push(vv.parts.filter(function (p) { return p.ref && p.meshes[0].visible; }).length + ' components shown');
    return out;
  };
  v.cfg.pcbToWorld = function (vv, p) { return p; };
  v.cfg.urlState = function (vv) { urlSet('p', vv); };
  v.finishModel();
}

/* ----- url state (history.replaceState: never triggers the router) */
function urlSet(tab, v) {
  try {
    var h = location.hash.replace(/\?.*$/, ''), q = ['tab=' + tab];
    if (v.selected && v.selected.ref) q.push('ref=' + encodeURIComponent(v.selected.ref));
    if (v.net) q.push('net=' + encodeURIComponent(v.net));
    history.replaceState(null, '', location.pathname + location.search + h + '?' + q.join('&'));
  } catch (e) { }
}
function urlGet() { var m = location.hash.match(/\?(.*)$/), q = {}; if (m) m[1].split('&').forEach(function (x) { var s = x.split('='); q[s[0]] = decodeURIComponent(s[1] || ''); }); return q; }

/* ------------------------------------------------------------------ public init */
var hv = null, pv = null;
function bomMap() {
  if (window.__v3bom || !window.BOM) return;
  var m = {}; BOM.items.forEach(function (it) { String(it.designators || '').split(/[\s,]+/).forEach(function (d) { if (d) m[d] = it; }); }); window.__v3bom = m;
}
function init() {
  var M = window.MODELS; if (!M) return;
  bomMap();
  var q = urlGet();
  var hostH = document.getElementById('v-housing'), hostP = document.getElementById('v-pcb');
  if (!hv && hostH) {
    hv = new Viewer3D(hostH, { kind: 'housing', traces: function (v, on) { if (v.pcbTex) v.pcbTex.setVisible(on); }, explode: true, explodeLabel: 'Explode', hasSearch: !!M.pcb, setup: setupHousing });
    if (!hv.dead) {
      if (q.ex) hv.setExplode(q.ex / 100);
      if (q.trans) { var o = hv.q('opacity'); if (o) { o.value = 30; o.oninput(); } }
      if (q.view) hv.view(q.view);
      if (q.tab !== 'p' && q.ref) afterRef(hv, q);
      hv.theme();
    }
  }
  var padP = document.querySelector('.tabpane[data-pane="m-p"]');
  if (!pv && hostP && padP && !padP.hidden) {
    if (!M.pcb) hostP.innerHTML = '<div class="vmsg">PCB 3D model not available (STEP conversion failed at build time)</div>';
    else {
      pv = new Viewer3D(hostP, { kind: 'pcb', traces: function (v, on) { if (v.pcbTex) v.pcbTex.setVisible(on); }, explode: true, hasSearch: true, setup: setupPcb });
      if (!pv.dead) { if (q.flip) pv.view('bottom'); else if (q.view) pv.view(q.view); if (q.tab === 'p') afterRef(pv, q); pv.theme(); }
    }
  }
  [hv, pv].forEach(function (v) { if (v && !v.dead) v.wake(300); });
}
function afterRef(v, q) {
  if (q.net) v.setNet(q.net);
  if (q.ref) { var p = v.partByRef(q.ref); if (p) v.select(p, { fly: true, noUrl: true }); }
}
window.__resize3d = function () { all.forEach(function (v) { if (!v.dead) { v.resize(); v.wake(300); } }); };
window.__rerender3d = function () { all.forEach(function (v) { if (!v.dead) v.theme(); }); };
window.Viewers3D = { init: init, all: all, urlGet: urlGet, get housing() { return hv; }, get pcb() { return pv; } };
})();
