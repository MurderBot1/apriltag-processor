/* Chip simulation pages: waveform viewer, frame pipeline visualiser.  No external libraries; data from simout/*.js (loaded as scripts, file:// safe). */
(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()||'#888'}
function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){}return null}
function hashParams(){var m=location.hash.match(/\?(.*)$/),q={};if(m)m[1].split('&').forEach(function(x){var s=x.split('=');q[s[0]]=decodeURIComponent(s[1]||'')});return q}
function fmtT(t){var a=Math.abs(t);if(a>=1e6)return (t/1e6).toFixed(3)+' ms';if(a>=1e3)return (t/1e3).toFixed(a>=1e5?1:3)+' us';return (Math.round(t*100)/100)+' ns'}

/* =========================================================== waveform viewer */
var WV=null;
window.initWave=function(){
  if(WV){WV.resize();var q0=hashParams();if(q0.s&&WV.sc.id!==q0.s)WV.select(q0.s);return}
  if(!window.WAVES||!WAVES.length){$('#wv-root').innerHTML='<p class="warn">No waveform data (run <code>py -3.12 site/sim/gen_sim.py</code>).</p>';return}
  WV=makeWave();var q=hashParams();WV.select(q.s||store('wv_scen')||WAVES[0].id);
};
function makeWave(){
  var ROW=26,RUL=30,NAMEW=0;
  var root=$('#wv-root'),cv=$('#wv-cv'),ctx=cv.getContext('2d'),names=$('#wv-names'),tip=$('#wv-tip'),wrap=$('#wv-wrap');
  var S={sc:null,vis:[],t0:0,scale:1,cur:null,hov:null,mode:'auto',w:800,h:200,drag:null,ci:{}};
  var sel=$('#wv-scen');
  var groups={};WAVES.forEach(function(s){(groups[s.group]=groups[s.group]||[]).push(s)});
  sel.innerHTML=Object.keys(groups).map(function(g){return '<optgroup label="'+esc(g)+'">'+groups[g].map(function(s){return '<option value="'+s.id+'">'+esc(s.title)+'</option>'}).join('')+'</optgroup>'}).join('');
  sel.onchange=function(){S.select(sel.value)};
  function val(sg,t){var ch=sg.ch,lo=0,hi=ch.length/2-1,r=-2;if(hi<0||t<ch[0])return null;
    while(lo<=hi){var m=(lo+hi)>>1;if(ch[2*m]<=t){r=m;lo=m+1}else hi=m-1}return ch[2*r+1]}
  function fmtV(sg,v,mode){
    if(v==null)return '-';if(v<0)return 'x';mode=mode||S.mode;
    if(sg.w===1&&mode==='auto')return String(v);
    if(mode==='auto'){if(sg.names&&sg.names[v]!==undefined)return sg.names[v];mode=sg.fmt==='b'?'bin':sg.fmt==='d'?'dec':'hex'}
    if(sg.names&&sg.names[v]!==undefined&&mode!=='hex'&&mode!=='dec'&&mode!=='sdec'&&mode!=='bin')return sg.names[v];
    if(mode==='hex')return (sg.w>1?'0x':'')+v.toString(16).toUpperCase();
    if(mode==='dec')return String(v);
    if(mode==='sdec'){var h=Math.pow(2,sg.w-1);return String(sg.w>1&&v>=h?v-2*h:v)}
    if(mode==='bin')return v.toString(2).padStart(sg.w,'0');return String(v)}
  function tipVal(sg,v){if(v==null)return '-';if(v<0)return 'x (unknown)';var s=fmtV(sg,v,'hex')+'  =  '+v+(sg.w>1?'  =  0b'+v.toString(2).padStart(sg.w,'0'):'');if(sg.names&&sg.names[v])s=sg.names[v]+'   ('+s+')';return s}
  function x2t(x){return S.t0+x/S.scale}function t2x(t){return (t-S.t0)*S.scale}
  function clampView(){var T=S.sc.tmax,minS=(S.w-8)/(T*1.04||1);if(S.scale<minS)S.scale=minS;if(S.scale>400)S.scale=400;
    var span=S.w/S.scale;if(S.t0<-T*0.02)S.t0=-T*0.02;if(S.t0>T*1.02-span)S.t0=Math.max(-T*0.02,T*1.02-span)}
  S.resize=function(){var w=wrap.clientWidth;if(!w)return;var dpr=window.devicePixelRatio||1;S.w=w;S.h=RUL+Math.max(S.vis.length,1)*ROW+4;
    cv.width=w*dpr;cv.height=S.h*dpr;cv.style.width=w+'px';cv.style.height=S.h+'px';ctx.setTransform(dpr,0,0,dpr,0,0);clampView();draw()};
  S.fit=function(){S.scale=(S.w-8)/(S.sc.tmax*1.04||1);S.t0=-S.sc.tmax*0.02;draw()};
  S.select=function(id){
    var sc=WAVES.filter(function(s){return s.id===id})[0]||WAVES[0];S.sc=sc;$('#wv-find').value='';sel.value=sc.id;store('wv_scen',sc.id);S.cur=null;S.hov=null;
    var d=sc.desc.split('\n');
    $('#wv-title').textContent=sc.title;
    $('#wv-desc').textContent=d[0];var pre=$('#wv-pre');if(d.length>1){pre.hidden=false;pre.textContent=d.slice(1).join('\n')}else pre.hidden=true;
    $('#wv-steps').innerHTML=sc.steps.map(function(x){return '<li>'+esc(x)+'</li>'}).join('');
    $('#wv-src').innerHTML='RTL: <a href="#/rtl/'+sc.module+'"><code>rtl/'+sc.module+'</code></a> &middot; testbench: <code>'+esc(sc.tb)+'</code> &middot; VCD '+(sc.vcd_bytes/1024).toFixed(0)+' KB &rarr; '+sc.signals.reduce(function(a,s){return a+s.ch.length/2},0)+' value changes, '+sc.signals.length+' signals available';
    S.vis=[];sc.signals.forEach(function(s,i){if(s.on)S.vis.push(i)});
    $('#wv-marks').innerHTML=sc.marks.map(function(m,i){return '<button class="chip" data-i="'+i+'" title="jump to '+fmtT(m[0])+'">'+esc(m[1])+' @ '+fmtT(m[0])+'</button>'}).join('')||'<span class="muted">none</span>';
    buildPicker();buildNames();S.resize();S.fit();updVals()};
  /* signal picker */
  function buildPicker(){
    var q=$('#wv-find').value.trim().toLowerCase(),g={},order=[];
    S.sc.signals.forEach(function(s,i){if(q&&(s.name+' '+s.group+' '+(s.desc||'')).toLowerCase().indexOf(q)<0)return;if(!g[s.group]){g[s.group]=[];order.push(s.group)}g[s.group].push(i)});
    $('#wv-pick').innerHTML=order.map(function(k){return '<details open><summary>'+esc(k)+' <span class="muted">('+g[k].length+')</span></summary>'+g[k].map(function(i){var s=S.sc.signals[i];
      return '<label class="chk pk" title="'+esc(s.desc||'')+'"><input type="checkbox" data-i="'+i+'"'+(S.vis.indexOf(i)>=0?' checked':'')+'> '+esc(s.name)+(s.w>1?' <span class="muted">['+s.w+']</span>':'')+'</label>'}).join('')+'</details>'}).join('')||'<span class="muted">no signal matches</span>'}
  $('#wv-find').addEventListener('input',buildPicker);
  $('#wv-pick').addEventListener('change',function(e){var i=+e.target.getAttribute('data-i');if(isNaN(i))return;var k=S.vis.indexOf(i);
    if(e.target.checked&&k<0){S.vis.push(i);S.vis.sort(function(a,b){return a-b})}else if(!e.target.checked&&k>=0)S.vis.splice(k,1);buildNames();S.resize();updVals()});
  $('#wv-all').onclick=function(){S.vis=S.sc.signals.map(function(s,i){return i});buildPicker();buildNames();S.resize();updVals()};
  $('#wv-none').onclick=function(){S.vis=[];buildPicker();buildNames();S.resize();updVals()};
  $('#wv-def').onclick=function(){S.vis=[];S.sc.signals.forEach(function(s,i){if(s.on)S.vis.push(i)});buildPicker();buildNames();S.resize();updVals()};
  function buildNames(){
    names.innerHTML='<div class="wn-rul"></div>'+S.vis.map(function(i){var s=S.sc.signals[i];
      return '<div class="wn" data-i="'+i+'" title="'+esc(s.name+(s.desc?' - '+s.desc:''))+'"><button class="x" title="remove from view">&times;</button><span class="nm">'+esc(s.name)+(s.w>1?'<i>['+s.w+']</i>':'')+'</span><button class="e" data-d="-1" title="previous change">&#9664;</button><button class="e" data-d="1" title="next change">&#9654;</button><span class="vv"></span></div>'}).join('')||'<div class="wn muted">no signals selected</div>'}
  names.addEventListener('click',function(e){var row=e.target.closest('.wn');if(!row)return;var i=+row.getAttribute('data-i');if(isNaN(i))return;
    if(e.target.classList.contains('x')){var k=S.vis.indexOf(i);if(k>=0)S.vis.splice(k,1);buildPicker();buildNames();S.resize();updVals()}
    else if(e.target.classList.contains('e')){jumpEdge(i,+e.target.getAttribute('data-d'))}});
  function jumpEdge(i,dir){var ch=S.sc.signals[i].ch,from=S.cur!=null?S.cur:(S.t0+S.w/S.scale/2),best=null;
    for(var k=0;k<ch.length;k+=2){var t=ch[k];if(dir>0&&t>from+1e-6){best=t;break}if(dir<0&&t<from-1e-6)best=t}
    if(best!=null)setCursor(best,true)}
  $('#wv-marks').addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var m=S.sc.marks[+b.getAttribute('data-i')];
    var span=Math.min(S.sc.tmax*1.04,Math.max(60,S.w/S.scale));S.scale=S.w/span;S.t0=m[0]-span/2;clampView();setCursor(m[0],false)});
  function setCursor(t,center){S.cur=t;if(center){var x=t2x(t);if(x<20||x>S.w-20){S.t0=t-S.w/S.scale/2;clampView()}}draw();updVals()}
  function updVals(){var t=S.cur!=null?S.cur:null;$$('.wn',names).forEach(function(r){var i=+r.getAttribute('data-i');if(isNaN(i))return;var s=S.sc.signals[i];
      r.querySelector('.vv').textContent=t==null?'':fmtV(s,val(s,t))});
    $('#wv-status').textContent=(S.cur!=null?'cursor '+fmtT(S.cur):'click the waveform to place the cursor')+(S.hov!=null&&S.cur!=null?'   hover '+fmtT(S.hov)+'   delta '+fmtT(S.hov-S.cur):'')}
  /* drawing */
  function nice(px){var raw=px/S.scale,p=Math.pow(10,Math.floor(Math.log(raw)/Math.LN10)),m=raw/p;return (m<=1?1:m<=2?2:m<=5?5:10)*p}
  function draw(){
    if(!S.sc)return;var C={bg:css('--card'),fg:css('--fg'),mu:css('--muted'),ln:css('--line'),c1:css('--c1'),c2:css('--c2'),c3:css('--c3'),ok:css('--ok'),code:css('--code')};
    ctx.clearRect(0,0,S.w,S.h);ctx.fillStyle=C.bg;ctx.fillRect(0,0,S.w,S.h);ctx.font='11px system-ui,sans-serif';ctx.textBaseline='middle';
    var tL=S.t0,tR=S.t0+S.w/S.scale;
    /* ruler + grid */
    var step=nice(90),t=Math.ceil(tL/step)*step;ctx.strokeStyle=C.ln;ctx.fillStyle=C.mu;ctx.lineWidth=1;ctx.textAlign='left';
    for(;t<tR;t+=step){var x=Math.round(t2x(t))+.5;ctx.beginPath();ctx.moveTo(x,RUL-6);ctx.lineTo(x,S.h);ctx.globalAlpha=.5;ctx.stroke();ctx.globalAlpha=1;ctx.fillText(fmtT(Math.round(t/step*1e6)/1e6*step),x+3,10)}
    /* rows */
    S.vis.forEach(function(i,r){var s=S.sc.signals[i],y0=RUL+r*ROW,yc=y0+ROW/2;
      if(r%2){ctx.fillStyle=C.code;ctx.globalAlpha=.35;ctx.fillRect(0,y0,S.w,ROW);ctx.globalAlpha=1}
      var ch=s.ch,n=ch.length/2,lo=0,hi=n-1,k0=-1;while(lo<=hi){var m=(lo+hi)>>1;if(ch[2*m]<=tL){k0=m;lo=m+1}else hi=m-1}
      if(k0<0)k0=0;
      if(s.w===1){
        ctx.lineWidth=1.5;ctx.strokeStyle=C.ok;ctx.beginPath();var started=false,py=0;var hiY=y0+5,loY=y0+ROW-6;
        for(var k=k0;k<n;k++){var tt=ch[2*k],v=ch[2*k+1],x0=Math.max(t2x(tt),-2);if(tt>tR)break;
          var yy=v<0?yc:(v?hiY:loY);
          if(!started){ctx.moveTo(x0,yy);started=true}else{ctx.lineTo(x0,py);ctx.lineTo(x0,yy)}py=yy;
          var nx=k+1<n?t2x(ch[2*k+2]):S.w+2;
          if(v<0){ctx.stroke();ctx.fillStyle=C.c3;ctx.globalAlpha=.35;ctx.fillRect(x0,y0+4,nx-x0,ROW-8);ctx.globalAlpha=1;ctx.beginPath();ctx.moveTo(nx,yy)}else ctx.lineTo(Math.min(nx,S.w+2),yy)}
        ctx.strokeStyle=C.ok;ctx.stroke();
      }else{
        var textFit=S.mode;
        for(var k=k0;k<n;k++){var tt=ch[2*k];if(tt>tR)break;var v=ch[2*k+1],xa=t2x(tt),xb=k+1<n?t2x(ch[2*k+2]):t2x(S.sc.tmax)+8;
          if(xb<0)continue;var ya=y0+4,yb=y0+ROW-5,xs=Math.max(xa,-4),xe=Math.min(xb,S.w+4);
          ctx.beginPath();ctx.moveTo(xs+(xa>=-4?2:0),yc);if(xa>=-4)ctx.lineTo(xs+2,ya);ctx.lineTo(xe-2,ya);ctx.lineTo(xe,yc);ctx.lineTo(xe-2,yb);ctx.lineTo(xs+2,yb);if(xa>=-4)ctx.lineTo(xs,yc);ctx.closePath();
          var named=s.names&&s.names[v]!==undefined&&v>=0;
          ctx.fillStyle=v<0?C.c3:(named?C.c2:C.c1);ctx.globalAlpha=v<0?.4:.18;ctx.fill();ctx.globalAlpha=1;ctx.lineWidth=1.2;ctx.strokeStyle=v<0?C.c3:(named?C.c2:C.c1);ctx.stroke();
          var wpx=xe-xs-8;if(wpx>14){var lab=fmtV(s,v);var tw=ctx.measureText(lab).width;
            if(tw>wpx){var kk=lab.length;while(kk>1&&ctx.measureText(lab.slice(0,kk)+'..').width>wpx)kk--;lab=kk>1?lab.slice(0,kk)+'..':''}
            ctx.fillStyle=C.fg;ctx.textAlign='center';ctx.fillText(lab,(Math.max(xs,0)+Math.min(xe,S.w))/2,yc);ctx.textAlign='left'}}
      }
    });
    /* gaps */
    ctx.save();(S.sc.breaks||[]).forEach(function(b){var xa=t2x(b[0]),xb=t2x(b[0]+40);if(xb<0||xa>S.w)return;
      ctx.fillStyle=C.mu;ctx.globalAlpha=.16;ctx.fillRect(xa,RUL-6,xb-xa,S.h);ctx.globalAlpha=.5;ctx.strokeStyle=C.mu;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(xa,RUL-6);ctx.lineTo(xa,S.h);ctx.moveTo(xb,RUL-6);ctx.lineTo(xb,S.h);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
      if(xb-xa>30){ctx.fillStyle=C.mu;ctx.textAlign='center';ctx.save();ctx.translate((xa+xb)/2,RUL+6);ctx.fillText('~'+fmtT(b[1])+' skipped',0,0);ctx.restore();ctx.textAlign='left'}});ctx.restore();
    /* marks */
    ctx.fillStyle=C.c2;S.sc.marks.forEach(function(m){var x=t2x(m[0]);if(x<-4||x>S.w+4)return;ctx.beginPath();ctx.moveTo(x-4,RUL-14);ctx.lineTo(x+4,RUL-14);ctx.lineTo(x,RUL-6);ctx.closePath();ctx.fill()});
    /* cursors */
    if(S.hov!=null){var xh=Math.round(t2x(S.hov))+.5;ctx.strokeStyle=C.mu;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(xh,RUL-6);ctx.lineTo(xh,S.h);ctx.stroke();ctx.setLineDash([])}
    if(S.cur!=null){var xc=Math.round(t2x(S.cur))+.5;ctx.strokeStyle=C.c3;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(xc,0);ctx.lineTo(xc,S.h);ctx.stroke();ctx.fillStyle=C.c3;ctx.fillRect(xc-1,0,2,2)}
  }
  S.draw=draw;
  /* interaction */
  function px(e){var r=cv.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top}}
  cv.addEventListener('wheel',function(e){e.preventDefault();var p=px(e);
    if(e.shiftKey||Math.abs(e.deltaX)>Math.abs(e.deltaY)){S.t0+=(e.deltaX||e.deltaY)/S.scale;clampView();draw();return}
    var f=Math.exp(-e.deltaY*0.0015),tm=x2t(p.x);S.scale*=f;clampView();S.t0=tm-p.x/S.scale;clampView();draw()},{passive:false});
  cv.addEventListener('pointerdown',function(e){var p=px(e);S.drag={x:p.x,t0:S.t0,moved:false};try{cv.setPointerCapture(e.pointerId)}catch(x){}});
  cv.addEventListener('pointermove',function(e){var p=px(e);
    if(S.drag){var dx=p.x-S.drag.x;if(Math.abs(dx)>3)S.drag.moved=true;if(S.drag.moved){S.t0=S.drag.t0-dx/S.scale;clampView()}}
    S.hov=x2t(p.x);draw();updVals();showTip(e,p)});
  cv.addEventListener('pointerup',function(e){var p=px(e);if(S.drag&&!S.drag.moved)setCursor(x2t(p.x),false);S.drag=null});
  cv.addEventListener('pointerleave',function(){S.hov=null;tip.hidden=true;draw();updVals()});
  cv.addEventListener('dblclick',function(){S.fit()});
  function showTip(e,p){var r=Math.floor((p.y-RUL)/ROW);if(S.drag&&S.drag.moved||r<0||r>=S.vis.length){tip.hidden=true;return}
    var s=S.sc.signals[S.vis[r]],v=val(s,S.hov);tip.hidden=false;tip.innerHTML='<b>'+esc(s.name)+'</b> @ '+fmtT(S.hov)+'<br>'+esc(tipVal(s,v))+(s.desc?'<br><span class="muted">'+esc(s.desc)+'</span>':'');
    var wr=wrap.getBoundingClientRect();tip.style.left=Math.min(p.x+14,wr.width-260)+'px';tip.style.top=(RUL+(r+1)*ROW+6)+'px'}
  $('#wv-zin').onclick=function(){zoomC(1.6)};$('#wv-zout').onclick=function(){zoomC(1/1.6)};$('#wv-fit').onclick=function(){S.fit()};
  function zoomC(f){var tm=S.cur!=null&&t2x(S.cur)>=0&&t2x(S.cur)<=S.w?S.cur:x2t(S.w/2),xm=t2x(tm);S.scale*=f;clampView();S.t0=tm-xm/S.scale;clampView();draw()}
  $$('#wv-radix button').forEach(function(b){b.onclick=function(){S.mode=b.getAttribute('data-m');$$('#wv-radix button').forEach(function(x){x.classList.toggle('on',x===b)});draw();updVals()}});
  window.addEventListener('resize',function(){if(!$('#page-wave').hidden)S.resize()});
  if(window.ResizeObserver){var lw=0;new ResizeObserver(function(){var w=wrap.clientWidth;if(w&&w!==lw){lw=w;if(S.sc&&!$('#page-wave').hidden){var keep=S.sc;S.resize()}}}).observe(wrap)}
  var o=window.__rerender3d;window.__rerender3d=function(){if(o)o();if(S.sc)draw()};
  document.getElementById('themetoggle').addEventListener('click',function(){setTimeout(draw,30)});
  return S;
}

/* =========================================================== frame pipeline visualiser */
var PV=null;
window.initPipe=function(){
  if(PV){var q1=hashParams();if(q1.i&&(!PV.img||PV.img.name!==q1.i))PV.pick(q1.i,q1.st!=null?+q1.st:PV.st);else if(q1.st!=null&&+q1.st!==PV.st)PV.stage(+q1.st);PV.resize();return}
  if(!window.PIPE){$('#pv-root').innerHTML='<p class="warn">No pipeline data (run <code>py -3.12 site/sim/gen_pipeline.py</code>).</p>';return}
  PV=makePipe();var q=hashParams();PV.pick(q.i||PIPE.images[0].name,q.st!=null?+q.st:0)
};
function makePipe(){
  var P=PIPE,S={img:null,st:0,z:1,x:0,y:0,w:800,h:500,side:false,ovl:{gt:true,chip:true,ids:true,bb:true,ext:true},imgs:{},drag:null};
  var cv=$('#pv-cv'),ctx=cv.getContext('2d'),wrap=$('#pv-wrap');
  $('#pv-img').innerHTML=P.images.map(function(i){return '<option value="'+i.name+'">'+esc(i.label)+'</option>'}).join('');
  $('#pv-img').onchange=function(){S.pick($('#pv-img').value,S.st)};
  $('#pv-stages').innerHTML=P.stages.map(function(s,k){return '<button data-k="'+k+'"><span class="sn">'+(k+1)+'</span> '+esc(s.short)+'</button>'}).join('');
  $('#pv-stages').onclick=function(e){var b=e.target.closest('button');if(b)S.stage(+b.getAttribute('data-k'))};
  $('#pv-slider').max=P.stages.length-1;$('#pv-slider').oninput=function(){S.stage(+this.value)};
  $$('#pv-ovl input').forEach(function(c){c.onchange=function(){S.ovl[c.getAttribute('data-o')]=c.checked;draw()}});
  $('#pv-side').onchange=function(){S.side=this.checked;S.resize()};
  $('#pv-reset').onclick=function(){fit();draw()};
  $('#pv-tags').onclick=function(){var im=S.img,x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;im.tags.forEach(function(t){(t.vis&&t.gt?t.gt:[]).forEach(function(p){x0=Math.min(x0,p[0]);y0=Math.min(y0,p[1]);x1=Math.max(x1,p[0]);y1=Math.max(y1,p[1])})});if(x1<x0)return;
    var pw=panelW(),m=40,z=Math.min(pw/(x1-x0+2*m),S.h/(y1-y0+2*m));S.z=z;S.x=pw/2-z*(x0+x1)/2;S.y=S.h/2-z*(y0+y1)/2;draw()};
  S.pick=function(name,st){S.img=P.images.filter(function(i){return i.name===name})[0]||P.images[0];$('#pv-img').value=S.img.name;S.loadAll(function(){S.stage(st||0);fit();draw()});info()};
  S.loadAll=function(cb){var im=S.img,need=0;P.stages.forEach(function(s,k){if(!s.file)return;var key=im.name+':'+k;if(S.imgs[key])return;need++;var el=new Image();S.imgs[key]=el;el.onload=function(){if(--need===0)cb()};el.onerror=function(){if(--need===0)cb()};el.src=P.dir+'/'+im.name+'_'+s.file});if(!need)cb()};
  S.stage=function(k){S.st=k;$('#pv-slider').value=k;$$('#pv-stages button').forEach(function(b,i){b.classList.toggle('on',i===k)});var s=P.stages[k];
    $('#pv-cap').innerHTML='<h3>'+(k+1)+'. '+esc(s.title)+'</h3><p>'+esc(s.caption)+'</p><p class="muted">RTL block: '+s.rtl.map(function(r){return '<a href="#/rtl/'+r+'"><code>rtl/'+r+'</code></a>'}).join(', ')+(s.golden?' &middot; model: <code>'+esc(s.golden)+'</code>':'')+'</p>'+(S.img&&S.img.notes&&S.img.notes[k]?'<p class="stnote">'+S.img.notes[k]+'</p>':'');
    draw()};
  function info(){var i=S.img;$('#pv-info').innerHTML=i.info}
  function fit(){var iw=P.w,ih=P.h,n=S.side?2:1,pw=(S.w-(n-1)*6)/n;S.z=Math.min(pw/iw,S.h/ih);S.x=0;S.y=0}
  S.resize=function(){var w=wrap.clientWidth;if(!w)return;var dpr=window.devicePixelRatio||1;S.w=w;S.h=Math.round(Math.min(Math.max(w*(S.side?0.32:0.62),300),720));cv.width=w*dpr;cv.height=S.h*dpr;cv.style.width=w+'px';cv.style.height=S.h+'px';ctx.setTransform(dpr,0,0,dpr,0,0);fit();draw()};
  function panelW(){return S.side?(S.w-6)/2:S.w}
  function drawStage(k,ox,pw){
    var s=P.stages[k],im=S.img,el=S.imgs[im.name+':'+k];ctx.save();ctx.beginPath();ctx.rect(ox,0,pw,S.h);ctx.clip();ctx.translate(ox+S.x,S.y);ctx.scale(S.z,S.z);
    ctx.imageSmoothingEnabled=S.z<1;if(s.file&&el&&el.complete&&el.naturalWidth){ctx.drawImage(el,0,0,P.w,P.h)}else{ctx.fillStyle='#222';ctx.fillRect(0,0,P.w,P.h)}
    var lw=1.6/S.z;
    if(s.ov==='ccl'){im.ccl.forEach(function(c){
      if(S.ovl.bb){ctx.strokeStyle=c.tag?'#ffd400':'#ff4d4d';ctx.lineWidth=lw;ctx.strokeRect(c.x0-.5,c.y0-.5,c.x1-c.x0+1,c.y1-c.y0+1)}
      if(S.ovl.ext){ctx.fillStyle='#00e5ff';c.ext.forEach(function(p){ctx.beginPath();ctx.arc(p[0],p[1],Math.max(2.2/S.z,1.2),0,7);ctx.fill()})}
      if(S.ovl.ids){ctx.fillStyle='#ffd400';ctx.font=(12/S.z)+'px sans-serif';ctx.fillText('#'+c.l+' a='+c.a,c.x0,c.y0-3/S.z)}})}
    if(s.ov==='tpu'||s.ov==='pose'){
      var quad=function(p,col,dash,txt,off){ctx.beginPath();p.forEach(function(q,j){j?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath();ctx.strokeStyle=col;ctx.lineWidth=lw*1.2;ctx.setLineDash(dash?[4/S.z,3/S.z]:[]);ctx.stroke();ctx.setLineDash([]);
        ctx.fillStyle=col;ctx.beginPath();ctx.arc(p[0][0],p[0][1],3.2/S.z,0,7);ctx.fill();
        if(txt&&S.ovl.ids){var cx=(p[0][0]+p[2][0])/2,cy=(p[0][1]+p[2][1])/2+off/S.z;ctx.font='bold '+(13/S.z)+'px sans-serif';ctx.lineWidth=3/S.z;ctx.strokeStyle='rgba(0,0,0,.75)';ctx.strokeText(txt,cx-8/S.z,cy);ctx.fillStyle=col;ctx.fillText(txt,cx-8/S.z,cy)}};
      im.tags.forEach(function(t){if(t.gt&&S.ovl.gt&&t.vis)quad(t.gt,'#3ddc84',false,'',0);if(t.chip&&S.ovl.chip)quad(t.chip,'#4aa3ff',false,'id '+t.id,10)});
      if(s.ov==='pose'&&im.reproj&&S.ovl.chip){im.reproj.forEach(function(p){quad(p,'#ff9f43',true,'',0)})}}
    ctx.restore();ctx.font='12px system-ui,sans-serif';ctx.textBaseline='middle';var ttl=(k+1)+'. '+s.title;ctx.fillStyle='rgba(0,0,0,.65)';ctx.fillRect(ox+6,6,Math.min(pw-12,ctx.measureText(ttl).width+14),22);ctx.fillStyle='#fff';ctx.fillText((k+1)+'. '+s.title,ox+12,17)}
  function draw(){if(!S.img)return;ctx.fillStyle='#111';ctx.fillRect(0,0,S.w,S.h);var pw=panelW();
    if(S.side&&S.st>0){drawStage(S.st-1,0,pw);drawStage(S.st,pw+6,pw)}else if(S.side){drawStage(S.st,0,pw);drawStage(S.st,pw+6,pw)}else drawStage(S.st,0,pw)}
  S.draw=draw;
  cv.addEventListener('wheel',function(e){e.preventDefault();var r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,pw=panelW(),ox=(S.side&&mx>pw+6)?pw+6:0;
    var f=Math.exp(-e.deltaY*0.0016),z2=Math.max(0.05,Math.min(40,S.z*f)),lx=(mx-ox-S.x)/S.z,ly=(my-S.y)/S.z;S.z=z2;S.x=mx-ox-lx*z2;S.y=my-ly*z2;draw()},{passive:false});
  cv.addEventListener('pointerdown',function(e){S.drag={x:e.clientX,y:e.clientY,ox:S.x,oy:S.y};try{cv.setPointerCapture(e.pointerId)}catch(x){}});
  cv.addEventListener('pointermove',function(e){if(!S.drag)return;S.x=S.drag.ox+e.clientX-S.drag.x;S.y=S.drag.oy+e.clientY-S.drag.y;draw()});
  cv.addEventListener('pointerup',function(){S.drag=null});cv.addEventListener('dblclick',function(){fit();draw()});
  window.addEventListener('resize',function(){if(!$('#page-pipeline').hidden)S.resize()});
  if(window.ResizeObserver){var lw2=0;new ResizeObserver(function(){var w=wrap.clientWidth;if(w&&w!==lw2){lw2=w;if(S.img&&!$('#page-pipeline').hidden)S.resize()}}).observe(wrap)}
  document.getElementById('themetoggle').addEventListener('click',function(){setTimeout(draw,30)});
  (function(){var f=function(b,t){return b?'<span class="good">'+t+'</span>':'<span class="bad">'+t+'</span>'};
    $('#pv-sum').innerHTML='<table><thead><tr><th>frame</th><th>threshold: RTL vs golden</th><th>despeckle: RTL vs golden</th><th>CCL candidates: RTL / golden</th><th>pose error (mm / deg)</th></tr></thead><tbody>'+P.images.map(function(i){var c=i.checks||{};
      return '<tr><td>'+esc(i.label)+'</td><td>'+(c.thr_diff===0?f(1,'identical'):f(0,c.thr_diff+' px differ (row '+(c.thr_rows||[]).join(', ')+')'))+'</td><td>'+(c.desp_diff===0?f(1,'identical'):f(0,c.desp_diff+' px differ'))+'</td><td>'+c.ccl_n_rtl+' / '+c.ccl_n_gold+' '+(c.ccl_match?f(1,'match'):f(0,'differ'))+'</td><td>'+(i.pose&&i.pose.n?i.pose.terr+' / '+i.pose.rerr:'no pose')+'</td></tr>'}).join('')+'</tbody></table>'})();
  S.resize();return S;
}
})();
