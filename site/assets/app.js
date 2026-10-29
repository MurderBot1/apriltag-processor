(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){}return null}

/* ---------- theme ---------- */
function isDark(){var t=document.documentElement.getAttribute('data-theme');if(t)return t==='dark';return window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches}
$('#themetoggle').onclick=function(){var t=isDark()?'light':'dark';document.documentElement.setAttribute('data-theme',t);store('theme',t);if(window.__rerender3d)window.__rerender3d()};
$('#navtoggle').onclick=function(){document.body.classList.toggle('navopen')};

/* ---------- routing ---------- */
var pages=$$('.page'),ids=pages.map(function(p){return p.id.slice(5)});
var inited={};
function route(){
  var h=location.hash.replace(/\?.*$/,'').replace(/^#\/?/,'')||'home',parts=h.split('/'),id=parts[0];
  if(ids.indexOf(id)<0)id='home';
  pages.forEach(function(p){p.hidden=(p.id!=='page-'+id)});
  $$('.navlink').forEach(function(a){a.classList.toggle('on',a.getAttribute('data-id')===id)});
  document.body.classList.remove('navopen');
  window.scrollTo(0,0);
  if(id==='models')initModels();
  if(id==='gallery')initGallery();
  if(id==='bom'&&window.initBom)initBom();
  if(id==='wave'&&window.initWave)initWave();
  if(id==='pipeline'&&window.initPipe)initPipe();
  if(id==='rtl'){initRtl();if(parts[1])openRtl(decodeURIComponent(parts[1]))}
  if(id==='models'&&window.__resize3d)setTimeout(window.__resize3d,30);
}
window.addEventListener('hashchange',route);

/* ---------- nav search ---------- */
$('#navsearch').addEventListener('input',function(){
  var q=this.value.trim().toLowerCase(),any=false;
  $$('#navlinks .navlink').forEach(function(a){
    var id=a.getAttribute('data-id'),ok=!q||a.textContent.toLowerCase().indexOf(q)>=0||(id&&window.SEARCH&&SEARCH[id]&&SEARCH[id].indexOf(q)>=0);
    a.style.display=ok?'':'none';if(ok)any=true});
  $$('#navlinks .navgroup').forEach(function(g){var n=g.nextElementSibling,vis=false;while(n&&!n.classList.contains('navgroup')){if(n.style.display!=='none')vis=true;n=n.nextElementSibling}g.style.display=vis?'':'none'});
  $('#navempty').hidden=any;
});

/* ---------- tabs ---------- */
$$('.tabs').forEach(function(t){var key=t.getAttribute('data-tabs');
  $$('button',t).forEach(function(b){b.onclick=function(){
    $$('button',t).forEach(function(x){x.classList.toggle('on',x===b)});
    $$('.tabpane[data-pane^="'+key+'-"]').forEach(function(p){p.hidden=(p.getAttribute('data-pane')!==key+'-'+b.getAttribute('data-t'))});
    if(key==='m')setTimeout(function(){initModels();if(window.__resize3d)window.__resize3d()},20)}})});

/* ---------- table filters ---------- */
$$('input.filter').forEach(function(inp){inp.addEventListener('input',function(){applyFilter(inp.getAttribute('data-target'))})});
$$('input.pwr').forEach(function(c){c.addEventListener('change',function(){applyFilter(c.getAttribute('data-target'))})});
function applyFilter(tid){var t=document.getElementById(tid),inp=$('input.filter[data-target="'+tid+'"]'),pw=$('input.pwr[data-target="'+tid+'"]'),q=inp?inp.value.trim().toLowerCase():'';
  $$('tbody tr',t).forEach(function(r){var ok=!q||r.textContent.toLowerCase().indexOf(q)>=0;if(pw&&!pw.checked&&r.getAttribute('data-k')==='power')ok=false;r.style.display=ok?'':'none'})}

/* ---------- 3D ---------- */
function b64buf(s,Type){var bin=atob(s),n=bin.length,u=new Uint8Array(n);for(var i=0;i<n;i++)u[i]=bin.charCodeAt(i);return new Type(u.buffer)}
function Viewer(el){
  var self=this;this.el=el;
  try{this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true})}catch(e){el.innerHTML='<div class="vmsg">WebGL is not available in this browser.</div>';this.dead=true;return}
  el.innerHTML='';el.appendChild(this.renderer.domElement);
  this.scene=new THREE.Scene();
  this.camera=new THREE.PerspectiveCamera(35,1,0.5,2000);this.camera.up.set(0,0,1);
  this.scene.add(new THREE.HemisphereLight(0xffffff,0x404860,0.9));
  var d=new THREE.DirectionalLight(0xffffff,0.8);d.position.set(60,-80,120);this.scene.add(d);
  var d2=new THREE.DirectionalLight(0xffffff,0.35);d2.position.set(-80,60,-60);this.scene.add(d2);
  this.controls=new THREE.OrbitControls(this.camera,this.renderer.domElement);
  this.controls.addEventListener('change',function(){self.render()});
  this.render=function(){self.renderer.render(self.scene,self.camera)};
  this.resize=function(){var w=el.clientWidth,h=el.clientHeight;if(!w||!h)return;self.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));self.renderer.setSize(w,h,false);self.renderer.domElement.style.width=w+'px';self.renderer.domElement.style.height=h+'px';self.camera.aspect=w/h;self.camera.updateProjectionMatrix();self.render()};
  window.addEventListener('resize',this.resize);
}
Viewer.prototype.view=function(center,dist,dir){this.controls.target.set(center[0],center[1],center[2]);var n=Math.hypot(dir[0],dir[1],dir[2]);this.camera.position.set(center[0]+dir[0]/n*dist,center[1]+dir[1]/n*dist,center[2]+dir[2]/n*dist);this.controls.update();this.render()};
var viewers=window.__viewers={};
function stlMesh(b64,color,opts){var g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(b64buf(b64,Float32Array),3));g.computeVertexNormals();
  var m=new THREE.MeshStandardMaterial(Object.assign({color:color,metalness:0.05,roughness:0.65,side:THREE.DoubleSide},opts||{}));return new THREE.Mesh(g,m)}
function pcbGroup(grp){var g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(b64buf(grp.pos,Float32Array),3));
  var c=b64buf(grp.col,Uint8Array);g.setAttribute('color',new THREE.BufferAttribute(c,3,true));g.setIndex(new THREE.BufferAttribute(b64buf(grp.idx,Uint32Array),1));g.computeVertexNormals();
  return new THREE.Mesh(g,new THREE.MeshStandardMaterial({vertexColors:true,flatShading:true,metalness:0.2,roughness:0.55,side:THREE.DoubleSide}))}
function initModels(){
  if(window.Viewers3D){window.Viewers3D.init();return}
  if(inited.models)return;var M=window.MODELS;if(!M)return;inited.models=true;
  var hv=new Viewer($('#v-housing')),pv=new Viewer($('#v-pcb'));viewers.h=hv;viewers.p=pv;
  if(!hv.dead){
    var front=M.housing.front&&stlMesh(M.housing.front.pos,0x4a7fb5,{transparent:true,opacity:1}),back=M.housing.back&&stlMesh(M.housing.back.pos,0xe08a30);
    var pcb=new THREE.Group();if(M.pcb)for(var k in M.pcb.groups){var o=pcbGroup(M.pcb.groups[k]);o.userData.g=k;pcb.add(o)}
    var Z=M.housing_z;if(front)hv.scene.add(front);if(back)hv.scene.add(back);hv.scene.add(pcb);
    var ex=$('#h-explode');
    function layout(){var e=ex.value/100;if(front)front.position.z=Z.split+e*34;pcb.position.z=Z.pcb_bottom+e*15;hv.render()}
    ex.addEventListener('input',layout);
    $('#h-front').onchange=function(){if(front)front.visible=this.checked;hv.render()};
    $('#h-back').onchange=function(){if(back)back.visible=this.checked;hv.render()};
    $('#h-pcb').onchange=function(){pcb.visible=this.checked;hv.render()};
    $('#h-wire').onchange=function(){var w=this.checked;[front,back].forEach(function(m){if(m)m.material.wireframe=w});hv.render()};
    $('#h-trans').onchange=function(){var t=this.checked;[front,back].forEach(function(m){if(m){m.material.transparent=t;m.material.opacity=t?0.35:1;m.material.depthWrite=!t;m.material.needsUpdate=true}});hv.render()};
    var reset=function(){hv.view([0,0,10],190,[1,-1.3,0.9])};$('#h-reset').onclick=reset;
    hv.resize();reset();layout();
  }
  if(!pv.dead){
    if(!M.pcb){pv.el.innerHTML='<div class="vmsg">PCB 3D model not available (STEP conversion failed at build time)</div>'}
    else{var grp={};for(var k in M.pcb.groups){var o=pcbGroup(M.pcb.groups[k]);grp[k]=o;pv.scene.add(o)}
      ['board','top','bottom'].forEach(function(k){$('#p-'+k).onchange=function(){if(grp[k])grp[k].visible=this.checked;pv.render()}});
      var flipped=false;
      var reset=function(){pv.view([0,0,0],120,flipped?[0.3,0.3,-1]:[0.3,-0.5,1])};
      $('#p-reset').onclick=reset;$('#p-flip').onclick=function(){flipped=!flipped;reset()};
      pv.resize();reset()}
  }
  window.__resize3d=function(){[hv,pv].forEach(function(v){if(v&&!v.dead&&v.resize)v.resize()})};
  window.__rerender3d=function(){[hv,pv].forEach(function(v){if(v&&!v.dead&&v.render)v.render()})};
}

/* ---------- gallery ---------- */
var cur=null,list=[];
function medOf(a){return a.length?a.slice().sort(function(x,y){return x-y})[a.length>>1]:null}
function initGallery(){
  if(window.Gallery){window.Gallery.init();return}
  if(inited.gallery||!window.GALLERY)return;inited.gallery=true;
  var G=GALLERY,grid=$('#g-grid');
  function sortKey(a,b){var s=$('#g-sort').value;
    if(s==='name')return a.name<b.name?-1:1;
    if(s==='err')return ((b.pose&&b.pose.t_mm)||0)-((a.pose&&a.pose.t_mm)||0);
    if(s==='miss')return (b.vis-b.found)-(a.vis-a.found);
    return a.cat<b.cat?-1:a.cat>b.cat?1:(a.name<b.name?-1:1)}
  function draw(){
    var q=$('#g-search').value.trim().toLowerCase(),c=$('#g-cat').value;
    list=G.images.filter(function(i){return (!q||i.name.toLowerCase().indexOf(q)>=0)&&(!c||i.cat===c)}).sort(sortKey);
    $('#g-count').textContent=list.length+' images';
    grid.innerHTML=list.map(function(i,k){var miss=i.vis-i.found;
      return '<div class="gitem" data-k="'+k+'"><img loading="lazy" src="thumbs/'+i.name+'.jpg" alt="'+i.name+'"><div><b>'+i.name+'</b><br>'+i.found+'/'+i.vis+' tags <span class="'+(miss>0?'bad':'good')+'">'+(miss>0?'('+miss+' missed)':'ok')+'</span><br>'+(i.pose?'pos err '+i.pose.t_mm.toFixed(1)+' mm':'no pose')+'</div></div>'}).join('')}
  grid.addEventListener('click',function(e){var it=e.target.closest('.gitem');if(it)openImg(+it.getAttribute('data-k'))});
  ['g-search','g-cat','g-sort'].forEach(function(id){$('#'+id).addEventListener('input',draw)});
  $('#m-close').onclick=function(){$('#g-modal').hidden=true;document.body.style.overflow=''};
  $('#m-prev').onclick=function(){openImg((cur+list.length-1)%list.length)};
  $('#m-next').onclick=function(){openImg((cur+1)%list.length)};
  ['m-gt','m-chip','m-invis','m-ids'].forEach(function(id){$('#'+id).onchange=drawOv});
  $('#m-img').addEventListener('load',drawOv);window.addEventListener('resize',drawOv);
  document.addEventListener('keydown',function(e){if($('#g-modal').hidden)return;if(e.key==='Escape')$('#m-close').onclick();if(e.key==='ArrowLeft')$('#m-prev').onclick();if(e.key==='ArrowRight')$('#m-next').onclick()});
  draw();
}
function openImg(k){
  cur=k;var i=list[k],G=GALLERY;$('#g-modal').hidden=false;document.body.style.overflow='hidden';
  $('#m-title').textContent=i.name+'  ['+i.cat+']';
  $('#m-img').src='frames/'+i.name+'.jpg';$('#m-full').href='frames/'+i.name+'.jpg';$('#m-full').textContent='open 1024x640 frame';
  var f=function(x,p){return x==null?'-':Number(x).toFixed(p)};
  var h='<table><tr><th colspan=2>Ground truth camera pose (camera to world)</th></tr><tr><td>position (m)</td><td>'+i.gt_t.join(', ')+'</td></tr><tr><td>R_wc</td><td><code>'+i.gt_R.map(function(r){return r.map(function(x){return x.toFixed(3)}).join(' ')}).join('<br>')+'</code></td></tr>'+
    (i.light?'<tr><td>light scale / shift</td><td>'+i.light.scale+' / '+i.light.shift+'</td></tr>':'')+'</table>';
  h+='<table><tr><th></th><th>chip + MCU solver</th><th>reference</th></tr>'+
    '<tr><td>tags detected / visible</td><td>'+i.found+' / '+i.vis+'</td><td>'+(i.ref&&i.ref.det!=null?i.ref.det:'-')+' / '+i.vis+'</td></tr>'+
    '<tr><td>false / unseen-tag detections</td><td>'+i.false+' / '+i.unseen+'</td><td>'+(i.ref&&i.ref.false!=null?i.ref.false:'-')+'</td></tr>'+
    '<tr><td>position error (mm)</td><td>'+(i.pose?f(i.pose.t_mm,2):'-')+'</td><td>'+(i.ref?f(i.ref.t_mm,2):'-')+'</td></tr>'+
    '<tr><td>orientation error (deg)</td><td>'+(i.pose?f(i.pose.rot_deg,3):'-')+'</td><td>'+(i.ref?f(i.ref.rot_deg,3):'-')+'</td></tr>'+
    '<tr><td>reprojection rms (px)</td><td>'+(i.pose?f(i.pose.rms_px,2)+' ('+i.pose.n+' tags)':'-')+'</td><td>'+(i.ref?f(i.ref.rms_px,2):'-')+'</td></tr></table>';
  var rows=Object.keys(i.tags).sort(function(a,b){return a-b}).map(function(id){var t=i.tags[id],st;
    if(t.chip&&t.vis)st='<span class="tag-ok">found</span>';else if(t.chip)st='<span class="tag-miss">detected, GT not visible</span>';else if(t.vis)st='<span class="tag-miss">missed</span>';else st='<span class="muted">not visible</span>';
    return '<tr><td>'+id+'</td><td>'+(t.px!=null?t.px:'-')+'</td><td>'+st+'</td><td>'+(t.err!=null?t.err:'-')+'</td></tr>'}).join('');
  h+='<table><tr><th>tag</th><th>GT width px</th><th>chip</th><th>max corner err px</th></tr>'+rows+'</table>';
  var s=i.stats;h+='<table><tr><th colspan=2>Chip status registers (simulation)</th></tr>'+Object.keys(s).map(function(k){return '<tr><td>'+k+'</td><td><code>'+esc(s[k])+'</code></td></tr>'}).join('')+'<tr><td>sim wall time</td><td>'+i.sim_s+' s</td></tr></table>';
  $('#m-info').innerHTML=h;
}
function drawOv(){
  if(cur==null)return;var i=list[cur],img=$('#m-img'),cv=$('#m-cv'),w=img.clientWidth,h=img.clientHeight;if(!w)return;
  var dpr=window.devicePixelRatio||1;cv.width=w*dpr;cv.height=h*dpr;var c=cv.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,w,h);
  var sx=w/GALLERY.w,sy=h/GALLERY.h;
  function quad(p,col,dash,id,off){c.beginPath();p.forEach(function(q,k){var x=q[0]*sx,y=q[1]*sy;k?c.lineTo(x,y):c.moveTo(x,y)});c.closePath();c.strokeStyle=col;c.lineWidth=1.6;c.setLineDash(dash||[]);c.stroke();
    c.setLineDash([]);c.fillStyle=col;c.beginPath();c.arc(p[0][0]*sx,p[0][1]*sy,3,0,7);c.fill();
    if($('#m-ids').checked){var cx=(p[0][0]+p[2][0])/2*sx,cy=(p[0][1]+p[2][1])/2*sy+(off||0);c.font='bold 12px sans-serif';c.lineWidth=3;c.strokeStyle='rgba(0,0,0,.7)';c.strokeText(id,cx-6,cy);c.fillStyle=col;c.fillText(id,cx-6,cy)}}
  Object.keys(i.tags).forEach(function(id){var t=i.tags[id];
    if(t.gt&&$('#m-gt').checked&&t.vis)quad(t.gt,'#3ddc84',[],id,-8);
    if(t.gt&&$('#m-invis').checked&&!t.vis)quad(t.gt,'#999',[4,3],id,0);
    if(t.chip&&$('#m-chip').checked)quad(t.chip,'#4aa3ff',[],id,8)})
}

/* ---------- RTL ---------- */
function initRtl(){
  if(inited.rtl||!window.RTL)return;inited.rtl=true;
  $$('.rtlrow').forEach(function(r){r.onclick=function(e){if(e.target.tagName==='A')return;location.hash='#/rtl/'+encodeURIComponent(RTL.mods[+r.getAttribute('data-i')].file)}});
  $('#rtl-find').addEventListener('input',function(){var q=this.value.toLowerCase();$$('#rtl-src .ln').forEach(function(l){l.classList.toggle('hit',!!q&&l.textContent.toLowerCase().indexOf(q)>=0)});var f=$('#rtl-src .ln.hit');if(f)f.scrollIntoView({block:'center'})});
}
function openRtl(file){
  var m=RTL.mods.filter(function(x){return x.file===file})[0];if(!m)return;
  $('#rtl-view').hidden=false;$('#rtl-name').textContent='rtl/'+m.file;
  $('#rtl-meta').textContent=m.lines+' lines, '+m.bytes+' bytes';
  $('#rtl-uses').innerHTML=(m.modules.length?'defines: <code>'+m.modules.join(', ')+'</code>':'')+(m.uses.length?' &middot; instantiates: <code>'+m.uses.join(', ')+'</code>':'');
  $('#rtl-src').innerHTML=m.html.replace(/\n$/,'').split('\n').map(function(l){return '<span class="ln">'+l+'</span>'}).join('');
  $('#rtl-find').value='';$('#rtl-view').scrollIntoView();
}

route();
/* test hook: #/models?tab=p&ex=100&trans=1 */
(function(){var m=location.hash.match(/\?(.*)$/);if(!m)return;var q={};m[1].split('&').forEach(function(x){var s=x.split('=');q[s[0]]=s[1]});
 if(q.tab){var b=$('.tabs[data-tabs="m"] button[data-t="'+q.tab+'"]');if(b)b.click()}
 setTimeout(function(){if(window.Viewers3D)return;if(q.ex){$('#h-explode').value=q.ex;$('#h-explode').dispatchEvent(new Event('input'))}
 if(q.trans){$('#h-trans').checked=true;$('#h-trans').onchange()}if(q.flip)$('#p-flip').onclick()},100)})();
})();
