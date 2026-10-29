/* ui.js - generic UX layer on top of app.js. Vanilla, offline, file:// safe. Everything is feature-detected so
   it keeps working for pages added later (tables, headings and nav are discovered from the DOM). */
(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function pref(k,v){try{if(v===undefined)return localStorage.getItem('ui.'+k);if(v===null)localStorage.removeItem('ui.'+k);else localStorage.setItem('ui.'+k,v)}catch(e){}return null}
function el(tag,attrs,html){var e=document.createElement(tag);if(attrs)for(var k in attrs){if(k==='class')e.className=attrs[k];else e.setAttribute(k,attrs[k])}if(html!=null)e.innerHTML=html;return e}
function typing(t){return t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)&&!/^(checkbox|radio|button)$/.test(t.type||''))}
var toastT;
function toast(msg){var t=$('#toast');if(!t){t=el('div',{id:'toast',role:'status'});document.body.appendChild(t)}t.textContent=msg;t.classList.add('on');clearTimeout(toastT);toastT=setTimeout(function(){t.classList.remove('on')},1800)}
function copyText(s,msg){
  function done(){toast(msg||'copied')}
  function fb(){try{var ta=el('textarea');ta.value=s;ta.style.cssText='position:fixed;opacity:0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();done()}catch(e){toast('copy failed')}}
  try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(done,fb);return}}catch(e){}
  fb()}
function download(name,text,type){try{var b=new Blob([text],{type:type||'text/csv'}),a=el('a',{download:name,href:URL.createObjectURL(b)});document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},500)}catch(e){toast('download failed')}}

/* ---------- page info ---------- */
var pages=$$('section.page'),info={};
(function(){var g='';$$('#navlinks > *').forEach(function(n){if(n.classList.contains('navgroup')){g=n.textContent;n.setAttribute('data-g',g)}else if(n.classList.contains('navlink')){n.setAttribute('data-g',g);info[n.getAttribute('data-id')]={title:n.textContent,group:g}}})})();
function curId(){var h=parseHash().id;return info[h]?h:'home'}
function parseHash(){
  var raw=location.hash.replace(/^#\/?/,''),qi=raw.indexOf('?'),path=qi<0?raw:raw.slice(0,qi),qs=qi<0?'':raw.slice(qi+1),q={};
  qs.split('&').forEach(function(x){if(!x)return;var s=x.split('=');try{q[s[0]]=decodeURIComponent((s[1]||'').replace(/\+/g,' '))}catch(e){q[s[0]]=s[1]||''}});
  var parts=path.split('/');return {id:parts[0]||'home',parts:parts,q:q}}
function setQuery(obj){var h=parseHash(),qs=Object.keys(obj).filter(function(k){return obj[k]!==''&&obj[k]!=null}).map(function(k){return k+'='+encodeURIComponent(obj[k])}).join('&');
  var base='#/'+h.parts.join('/');try{history.replaceState(null,'',base+(qs?'?'+qs:''))}catch(e){}}

/* ---------- header, drawer, theme ---------- */
(function(){
  var top=$('header.top');if(!top)return;
  var tt=$('#themetoggle'),nt=$('#navtoggle');
  var sk=el('a',{class:'skip',href:'#main'},'Skip to content');sk.onclick=function(e){e.preventDefault();var m=$('#main');m.setAttribute('tabindex','-1');m.focus()};document.body.insertBefore(sk,document.body.firstChild);
  var pb=el('button',{id:'palbtn',class:'kbd-btn',title:'Search everything (Ctrl+K or /)','aria-label':'Search'},'<span aria-hidden="true">&#8981;</span><span class="lbl">Search</span><kbd>Ctrl K</kbd>');
  var hb=el('button',{id:'helpbtn',title:'Keyboard shortcuts (?)','aria-label':'Keyboard shortcuts'},'?');
  top.insertBefore(pb,tt);top.insertBefore(hb,tt);
  pb.onclick=function(){openPal('')};hb.onclick=function(){keyHelp(true)};
  function isDark(){var t=document.documentElement.getAttribute('data-theme');return t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches}
  function lab(){tt.innerHTML=isDark()?'&#9790; Dark':'&#9788; Light';tt.setAttribute('aria-label','Theme: '+(isDark()?'dark':'light')+'. Click to switch.')}
  lab();tt.addEventListener('click',function(){setTimeout(lab,0)});
  window.__uiTheme=function(){tt.click()};
  var sc=el('div',{id:'navscrim'});document.body.appendChild(sc);sc.onclick=function(){document.body.classList.remove('navopen');sync()};
  function sync(){nt.setAttribute('aria-expanded',document.body.classList.contains('navopen'))}
  nt.setAttribute('aria-controls','nav');nt.setAttribute('aria-label','Menu');nt.addEventListener('click',sync);
  window.addEventListener('hashchange',sync);
})();

/* ---------- nav groups ---------- */
(function(){
  var closed=[];try{closed=JSON.parse(pref('navclosed')||'[]')}catch(e){}
  function apply(){$$('#navlinks .navgroup').forEach(function(g){var n=g.getAttribute('data-g'),c=closed.indexOf(n)>=0;g.classList.toggle('closed',c);g.setAttribute('aria-expanded',!c);
    $$('#navlinks .navlink[data-g="'+n.replace(/"/g,'\\"')+'"]').forEach(function(a){a.classList.toggle('nav-collapsed',c)})})}
  $$('#navlinks .navgroup').forEach(function(g){g.setAttribute('role','button');g.tabIndex=0;
    function tog(){var n=g.getAttribute('data-g'),i=closed.indexOf(n);if(i>=0)closed.splice(i,1);else closed.push(n);pref('navclosed',JSON.stringify(closed));apply()}
    g.addEventListener('click',tog);g.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();tog()}})});
  window.__navOpenGroup=function(id){var i=info[id];if(!i)return;var k=closed.indexOf(i.group);if(k>=0){closed.splice(k,1);pref('navclosed',JSON.stringify(closed));apply()}};
  var ns=$('#navsearch');if(ns){ns.setAttribute('aria-label','Filter pages');ns.addEventListener('input',function(){$('#nav').classList.toggle('searching',!!ns.value.trim())})}
  apply();
})();

/* ---------- headings: ids, copy-link anchors ---------- */
var heads={};   // pid -> [{el,id,text,lvl}]
pages.forEach(function(sec){
  var pid=sec.id.slice(5),used={},arr=[];
  $$('h2,h3',sec).forEach(function(h){
    if(h.closest('.modal')||h.id)return;
    var t=h.textContent.replace(/\s+/g,' ').trim();if(!t)return;
    var s=t.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,50)||'section',b=s,n=2;while(used[s])s=b+'-'+n++;used[s]=1;
    h.id=pid+'--'+s;arr.push({el:h,id:s,text:t,lvl:h.tagName==='H2'?2:3});
    if(pid!=='rtl'){var a=el('button',{class:'hanchor',type:'button',title:'Copy link to this section','aria-label':'Copy link to '+t},'#');
      a.onclick=function(e){e.preventDefault();var u='#/'+pid+'/'+s;try{history.replaceState(null,'',u)}catch(x){}copyText(location.href.split('#')[0]+u,'link copied');a.classList.add('ok');setTimeout(function(){a.classList.remove('ok')},1200)};
      h.appendChild(a)}
  });heads[pid]=arr});

/* ---------- breadcrumbs + toc + scroll spy ---------- */
var crumbs=el('nav',{id:'crumbs','aria-label':'Breadcrumb'});$('#main').insertBefore(crumbs,$('#main').firstChild);
var tocMq=window.matchMedia?matchMedia('(min-width:1400px)'):{matches:false};
function tocSync(){$$('details.toc').forEach(function(d){d.open=tocMq.matches})}
if(tocMq.addEventListener)tocMq.addEventListener('change',tocSync);
var spy=null;
function buildToc(pid){
  var sec=$('#page-'+pid);if(!sec||sec.__toc||pid==='rtl'||pid==='home')return;sec.__toc=1;
  var hs=(heads[pid]||[]).filter(function(h){return !h.el.closest('.tabpane[hidden]')});if(hs.length<3)return;
  var d=el('details',{class:'toc'},'<summary>On this page</summary><ol>'+hs.map(function(h){return '<li class="l'+h.lvl+'"><a href="#/'+pid+'/'+h.id+'" data-h="'+h.el.id+'">'+esc(h.text)+'</a></li>'}).join('')+'</ol>');
  var h1=$('h1',sec);if(h1&&h1.nextSibling)h1.parentNode.insertBefore(d,h1.nextSibling);else sec.insertBefore(d,sec.firstChild);
  d.open=tocMq.matches;
  d.addEventListener('click',function(e){var a=e.target.closest('a');if(!a)return;e.preventDefault();var t=document.getElementById(a.getAttribute('data-h'));if(t){try{history.replaceState(null,'',a.getAttribute('href'))}catch(x){}t.scrollIntoView();if(!tocMq.matches)d.open=false}});
}
function startSpy(pid){
  var links=$$('.toc a',$('#page-'+pid));spy=null;if(!links.length)return;
  var els=links.map(function(a){return document.getElementById(a.getAttribute('data-h'))}),tick=false;
  function run(){tick=false;var cur=0;for(var i=0;i<els.length;i++){if(els[i]&&els[i].getBoundingClientRect().top<=100)cur=i}
    links.forEach(function(a,i){var on=i===cur;if(a.classList.contains('on')!==on)a.classList.toggle('on',on);if(on)a.setAttribute('aria-current','true');else a.removeAttribute('aria-current')})}
  spy=function(){if(!tick){tick=true;requestAnimationFrame(run)}};spy();
}
window.addEventListener('scroll',function(){if(spy)spy()},{passive:true});

/* ---------- tables ---------- */
function cellText(c){return (c.textContent||'').replace(/\s+/g,' ').trim()}
function numOf(s){var m=s.replace(/[\s,$%]/g,'');return /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(m)?parseFloat(m):null}
function csvCell(s){return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}
function visibleRows(t){var tb=t.tBodies[0];return tb?Array.prototype.filter.call(tb.rows,function(r){return r.style.display!=='none'&&!r.classList.contains('ui-hide')&&!r.classList.contains('grp')}):[]}
function enhanceTable(t,pid){
  if(t.__ui||t.closest('.v3')||t.closest('.modal')||t.closest('#keyhelp')||t.closest('.chart'))return;t.__ui=1;
  var tb=t.tBodies[0];if(!tb)return;
  if(!t.closest('.tablewrap')){var w=el('div',{class:'tablewrap'});t.parentNode.insertBefore(w,t);w.appendChild(t)}
  var wrap=t.closest('.tablewrap'),total=tb.rows.length;
  var hr=t.tHead&&t.tHead.rows.length===1?t.tHead.rows[0]:null;
  var ths=hr?Array.prototype.slice.call(hr.cells):[];
  var own=!!t.id&&!!$('input.filter[data-target="'+t.id+'"]')||t.id==='bom-table';
  var bar=el('div',{class:'tbar'}),cnt=el('span',{class:'cnt','aria-live':'polite'});
  var inp=null,sel=null;
  if(!own&&total>=6){
    inp=el('input',{type:'search',placeholder:'filter rows...','aria-label':'Filter table rows'});bar.appendChild(inp);
    if(ths.length>2){sel=el('select',{'aria-label':'Column to filter'},'<option value="-1">all columns</option>'+ths.map(function(h,i){return '<option value="'+i+'">'+esc(cellText(h))+'</option>'}).join(''));bar.appendChild(sel)}
  }
  bar.appendChild(cnt);bar.appendChild(el('span',{class:'grow'}));
  var csv=el('button',{type:'button',class:'sm',title:'Download the visible rows as CSV'},'CSV');bar.appendChild(csv);
  if(total<2&&!own){/* tiny table: no toolbar */}else wrap.parentNode.insertBefore(bar,wrap);
  function head(){var h=t.tHead?t.tHead.rows[t.tHead.rows.length-1]:null;return h?Array.prototype.map.call(h.cells,cellText):[]}
  function count(){var v=visibleRows(t).length,n=0;Array.prototype.forEach.call(tb.rows,function(r){if(!r.classList.contains('grp'))n++});
    cnt.textContent=v===n?n+' rows':v+' of '+n+' rows';cnt.classList.toggle('none',v===0);if(v===0)cnt.textContent='no matching rows'}
  var pend=false,mo=new MutationObserver(function(){if(!pend){pend=true;requestAnimationFrame(function(){pend=false;count()})}});
  mo.observe(tb,{childList:true,subtree:true,attributes:true,attributeFilter:['style','class']});count();
  function filt(){var q=inp.value.trim().toLowerCase(),c=sel?+sel.value:-1;
    Array.prototype.forEach.call(tb.rows,function(r){var ok=!q;if(!ok){var txt=c>=0&&r.cells[c]?r.cells[c].textContent:r.textContent;ok=txt.toLowerCase().indexOf(q)>=0}r.classList.toggle('ui-hide',!ok)})}
  if(inp){inp.addEventListener('input',filt);if(sel)sel.addEventListener('change',filt)}
  csv.onclick=function(){var rows=[head()].concat(visibleRows(t).map(function(r){return Array.prototype.map.call(r.cells,cellText)}));
    download((pid||'table')+(t.id?'-'+t.id:'')+'.csv',rows.map(function(r){return r.map(csvCell).join(',')}).join('\r\n')+'\r\n');toast('CSV: '+(rows.length-1)+' rows')};
  /* sorting (bom-table sorts itself; skip grouped / spanning tables) */
  var spans=ths.some(function(h){return h.colSpan>1})||Array.prototype.some.call(tb.rows,function(r){return r.classList.contains('grp')||Array.prototype.some.call(r.cells,function(c){return c.colSpan>1||c.rowSpan>1})});
  if(hr&&!spans&&total>1&&t.id!=='bom-table'){
    Array.prototype.forEach.call(tb.rows,function(r,i){r.__i=i});
    ths.forEach(function(th,ci){th.classList.add('ui-sort');th.tabIndex=0;th.setAttribute('role','columnheader');
      function go(){var dir=th.getAttribute('aria-sort')==='ascending'?-1:1;ths.forEach(function(x){x.removeAttribute('aria-sort')});th.setAttribute('aria-sort',dir>0?'ascending':'descending');
        var rs=Array.prototype.slice.call(tb.rows),keys=rs.map(function(r){var s=r.cells[ci]?cellText(r.cells[ci]):'';return {r:r,s:s,n:numOf(s)}});
        var numeric=keys.every(function(k){return k.n!==null||k.s===''||k.s==='-'});
        keys.sort(function(a,b){var c;if(numeric){var x=a.n===null?(dir>0?Infinity:-Infinity):a.n,y=b.n===null?(dir>0?Infinity:-Infinity):b.n;c=x===y?0:x<y?-1:1}else c=a.s.localeCompare(b.s,undefined,{numeric:true,sensitivity:'base'});return c*dir||a.r.__i-b.r.__i});
        var f=document.createDocumentFragment();keys.forEach(function(k){f.appendChild(k.r)});tb.appendChild(f)}
      th.addEventListener('click',go);th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})})}
}
function enhancePage(pid){var sec=$('#page-'+pid);if(!sec)return;$$('table',sec).forEach(function(t){enhanceTable(t,pid)})}

/* ---------- command palette ---------- */
var palIdx=null,palEl,palIn,palUl,palSel=0,palRes=[];
function buildIndex(){
  var I=[];
  Object.keys(info).forEach(function(id){I.push({t:info[id].title,k:'page',s:info[id].group,h:'#/'+id,w:0})});
  Object.keys(heads).forEach(function(pid){if(pid==='rtl'||!info[pid])return;heads[pid].forEach(function(h){I.push({t:h.text,k:'section',s:info[pid].title,h:'#/'+pid+'/'+h.id,w:1})})});
  if(window.RTL&&RTL.mods)RTL.mods.forEach(function(m){I.push({t:m.file,k:'rtl',s:m.modules.join(', ')||'file',h:'#/rtl/'+encodeURIComponent(m.file),w:2});
    m.modules.forEach(function(n){I.push({t:n,k:'module',s:m.file,h:'#/rtl/'+encodeURIComponent(m.file),w:2})})});
  if(window.BOM&&BOM.items)BOM.items.forEach(function(x){var d=String(x.designators||''),first=(d.split(/[\s,]+/)[0]||'');
    I.push({t:(d.length>40?d.slice(0,40)+'...':d)+'  '+(x.value||''),k:'part',s:[x.mpn,x.mfr].filter(Boolean).join(' / '),h:'#/bom?q='+encodeURIComponent(x.mpn||first||x.value||''),w:3,x:[x.mpn,x.mfr,x.category,x.value,d].join(' ')})});
  $$('#nettable tbody tr').forEach(function(r){var n=r.cells[0]&&cellText(r.cells[0]);if(n)I.push({t:n,k:'net',s:(r.cells[1]?cellText(r.cells[1]):'')+' pins',h:'#/netlist?q='+encodeURIComponent(n),w:3});(r.cells[2]?cellText(r.cells[2]).split(' '):[]).forEach(function(pn){if(pn)I.push({t:pn,k:'pin',s:'net '+n,h:'#/netlist?q='+encodeURIComponent(pn),w:4})})});
  if(window.GALLERY&&GALLERY.images)GALLERY.images.forEach(function(i){I.push({t:i.name,k:'image',s:i.cat+' - '+i.found+'/'+i.vis+' tags',h:'#/gallery?img='+encodeURIComponent(i.name),w:3})});
  I.forEach(function(i){i.l=(i.t+' '+(i.x||'')+' '+i.s).toLowerCase()});
  return I}
function hl(t,toks){var s=esc(t),lo=t.toLowerCase();for(var i=0;i<toks.length;i++){var p=lo.indexOf(toks[i]);if(p>=0&&toks[i]){return esc(t.slice(0,p))+'<mark>'+esc(t.slice(p,p+toks[i].length))+'</mark>'+esc(t.slice(p+toks[i].length))}}return s}
function palSearch(q){
  q=q.trim().toLowerCase();var toks=q.split(/\s+/).filter(Boolean),out=[];
  if(!toks.length){return palIdx.filter(function(i){return i.k==='page'}).map(function(i){return i})}
  palIdx.forEach(function(i){var ok=toks.every(function(t){return i.l.indexOf(t)>=0});if(!ok)return;var tl=i.t.toLowerCase(),sc=i.w*10;
    sc+=tl===q?-30:tl.indexOf(q)===0?-15:tl.indexOf(q)>=0?-5:5;out.push({i:i,sc:sc})});
  out.sort(function(a,b){return a.sc-b.sc||a.i.t.length-b.i.t.length});
  var res=out.slice(0,60).map(function(x){return x.i});
  if(res.length<8&&q.length>=3&&window.SEARCH)Object.keys(info).forEach(function(id){var S=SEARCH[id];if(S&&S.indexOf(q)>=0)res.push({t:'"'+q+'" in '+info[id].title,k:'text',s:'full-text match',h:'#/'+id+'?find='+encodeURIComponent(q),w:9,toks:toks})});
  return res}
function palDraw(){
  var toks=palIn.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  palUl.innerHTML=palRes.length?palRes.map(function(r,i){return '<li role="option" id="pal-'+i+'" data-i="'+i+'" aria-selected="'+(i===palSel)+'"><span class="k">'+r.k+'</span><span class="t">'+hl(r.t,toks)+'</span><span class="s">'+esc(r.s)+'</span></li>'}).join(''):'<li class="none" style="display:block;cursor:default">No results. Try a page name, RTL module, part number, net or test image.</li>';
  palIn.setAttribute('aria-activedescendant',palRes.length?'pal-'+palSel:'');
  var s=$('li[aria-selected=true]',palUl);if(s&&s.scrollIntoView)s.scrollIntoView({block:'nearest'})}
function palGo(r){if(!r)return;closePal();var h=r.h,cur=location.hash;if(h===cur){window.dispatchEvent(new Event('hashchange'))}else location.hash=h}
function openPal(q){
  if(!palEl){
    palIdx=buildIndex();
    palEl=el('div',{id:'pal',hidden:'hidden',role:'dialog','aria-modal':'true','aria-label':'Quick switcher'},'<div class="box"><input type="search" id="pal-in" placeholder="Search pages, sections, RTL modules, parts, nets, test images..." autocomplete="off" role="combobox" aria-expanded="true" aria-controls="pal-list" spellcheck="false"><ul id="pal-list" role="listbox"></ul><div class="foot"><span><kbd>&uarr;</kbd><kbd>&darr;</kbd> select</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span><span><kbd>?</kbd> all shortcuts</span></div></div>');
    document.body.appendChild(palEl);palIn=$('#pal-in');palUl=$('#pal-list');
    palEl.addEventListener('mousedown',function(e){if(e.target===palEl)closePal()});
    palUl.addEventListener('click',function(e){var li=e.target.closest('li[data-i]');if(li)palGo(palRes[+li.getAttribute('data-i')])});
    palUl.addEventListener('mousemove',function(e){var li=e.target.closest('li[data-i]');if(li&&+li.getAttribute('data-i')!==palSel){var o=$('li[aria-selected=true]',palUl);if(o)o.setAttribute('aria-selected','false');palSel=+li.getAttribute('data-i');li.setAttribute('aria-selected','true')}});
    palIn.addEventListener('input',function(){palSel=0;palRes=palSearch(palIn.value);palDraw()});
    palIn.addEventListener('keydown',function(e){
      if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palRes.length-1,palSel+1);palDraw()}
      else if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(0,palSel-1);palDraw()}
      else if(e.key==='Enter'){e.preventDefault();palGo(palRes[palSel])}
      else if(e.key==='Escape'){e.preventDefault();closePal()}
      else if(e.key==='Tab'){e.preventDefault()}});
  }
  palEl.hidden=false;palIn.value=q||'';palSel=0;palRes=palSearch(palIn.value);palDraw();palIn.focus();palIn.select()}
function closePal(){if(palEl)palEl.hidden=true}
var kh;
function keyHelp(show){
  if(!kh){kh=el('div',{id:'keyhelp',hidden:'hidden',role:'dialog','aria-modal':'true','aria-label':'Keyboard shortcuts'},'<div class="box"><h2 style="margin-top:0;border:0">Keyboard shortcuts</h2><table><tbody>'+
   [['Ctrl K &nbsp;or&nbsp; /','Quick switcher: pages, sections, RTL, parts, nets, images'],['?','This help'],['t','Toggle light / dark theme'],['[ &nbsp; ]','Previous / next page'],['Esc','Close dialog, palette or drawer'],
    ['Gallery modal','&larr; &rarr; browse, Esc close, + - 0 zoom, c compare, 1-4 overlays, o all overlays'],['RTL file','Enter / Shift+Enter in the find box: next / previous match; click a line number to link to it'],['Headings','hover and click # to copy a deep link']].map(function(r){return '<tr><td><kbd>'+r[0]+'</kbd></td><td>'+r[1]+'</td></tr>'}).join('')+'</tbody></table><p class="hint">Click anywhere or press Esc to close.</p></div>');
   document.body.appendChild(kh);kh.addEventListener('click',function(){kh.hidden=true})}
  kh.hidden=!show}
document.addEventListener('keydown',function(e){
  var k=e.key;
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&k.toLowerCase()==='k'){e.preventDefault();if(palEl&&!palEl.hidden)closePal();else openPal('');return}
  if(k==='Escape'){if(kh&&!kh.hidden){kh.hidden=true;return}if(document.body.classList.contains('navopen')){document.body.classList.remove('navopen');return}}
  if(e.ctrlKey||e.metaKey||e.altKey||typing(e.target))return;
  var modal=$('#g-modal');if(modal&&!modal.hidden)return;
  if(palEl&&!palEl.hidden)return;
  if(k==='/'){e.preventDefault();openPal('')}
  else if(k==='?'){keyHelp(kh?kh.hidden:true)}
  else if(k==='t'){window.__uiTheme()}
  else if(k==='['||k===']'){var ids=Object.keys(info),i=ids.indexOf(curId());if(i>=0){var n=ids[(i+(k===']'?1:ids.length-1))%ids.length];location.hash='#/'+n}}
});

/* ---------- home dashboard ---------- */
function cardOf(pid,re){var r=null;$$('#page-'+pid+' .card').forEach(function(c){var s=c.querySelector('span'),b=c.querySelector('b');if(!r&&s&&b&&re.test(s.textContent))r={v:b.textContent.trim(),l:s.textContent.trim()}});return r}
function rowOf(pid,re){var r=null;$$('#page-'+pid+' table tr').forEach(function(tr){if(!r&&tr.cells.length>1&&re.test(cellText(tr.cells[0])))r=Array.prototype.map.call(tr.cells,cellText)});return r}
function buildDash(){
  var home=$('#page-home');if(!home||home.__dash)return;home.__dash=1;
  var cards=[];
  function add(c){cards.push(c)}
  try{var t=cardOf('results',/pytest/);if(t)add({l:'Tests',v:t.v,s:t.l+'. Open results for the per-suite breakdown.',h:'#/results'})}catch(e){}
  try{var f=cardOf('results',/fps/);if(!f){var fm0=(($('#page-results')||{}).textContent||'').match(/(\d+\.\d+)\s*fps/);if(fm0)f={v:fm0[1],l:'sustained frame rate, from the whole-chip timing test'}}if(f){var fv=parseFloat(f.v);add({l:'Frame rate',v:f.v.replace(/\s*fps/,'')+' fps',s:f.l.replace(/^fps\s*/,''),h:'#/results',c:fv>=120?'good':fv>=60?'':'warn'})}}catch(e){}
  try{var a=cardOf('results',/found by chip/);if(a){var m=a.v.match(/(\d+)\s*\/\s*(\d+)/),p=m?Math.round(100*m[1]/m[2]):null,e1=cardOf('results',/median camera position/);
    add({l:'Detection accuracy',v:a.v,s:a.l+(e1?'. Median position error '+e1.v+'.':''),h:'#/results',p:p,c:p>=95?'good':p>=85?'':'warn'})}}catch(e){}
  try{var lu=rowOf('results',/^LUT4/),br=rowOf('results',/block RAM/),ff=rowOf('results',/flip-flops/);
    if(lu){var pc=parseFloat(lu[lu.length-1]),bp=br?parseFloat(br[br.length-1]):null;add({l:'FPGA utilisation',v:pc+'% LUT4',s:(br?'block RAM '+bp+'%':'')+(ff?', flip-flops '+parseFloat(ff[ff.length-1])+'%':'')+' (ECP5-85F)',h:'#/fpga',p:pc,c:bp>=90?'warn':''})}}catch(e){}
  try{if(window.BOM&&BOM.items){var tot=0,un=0;BOM.items.forEach(function(x){if(x.status==='verified'&&x.unit_price!=null&&x.link)tot+=x.qty*x.unit_price;else un++});
    add({l:'BOM total',v:'$'+tot.toFixed(2),s:'verified lines, 1 board'+(un?'; '+un+' unverified lines not included':''),h:'#/bom',c:un?'warn':'good'})}}catch(e){}
  try{var txt=($('#page-board')||{}).textContent||'',dm=txt.match(/(\d+) violations,\s*(\d+) unconnected/),cm=txt.match(/Components placed\s*(\d+)/);
    if(dm)add({l:'PCB routing / DRC',v:dm[1]+' violations',s:dm[2]+' unconnected items in the latest routing trial'+(cm?'; '+cm[1]+' components placed':''),h:'#/board',c:+dm[2]>0||+dm[1]>0?'warn':'good'})}catch(e){}
  if(window.GALLERY&&GALLERY.images)add({l:'Test images',v:String(GALLERY.images.length),s:'frames with ground truth and detections',h:'#/gallery'});
  if(window.RTL&&RTL.mods)add({l:'RTL sources',v:String(RTL.mods.length),s:'files, with an in-browser source viewer',h:'#/rtl'});
  var h='<div class="dash"><h2>At a glance</h2><div class="dgrid">'+cards.map(function(c){return '<a class="dcard '+(c.c||'')+'" href="'+c.h+'"><span class="dl">'+esc(c.l)+'</span><b>'+esc(c.v)+'</b><span class="ds">'+esc(c.s)+'</span>'+(c.p!=null?'<i class="bar"><u style="width:'+Math.max(2,Math.min(100,c.p))+'%"></u></i>':'')+'</a>'}).join('')+'</div></div>';
  var guide=[['readme','Read the overview'],['architecture','See how the chip, FPGA and MCU fit together'],['results','Check the verification numbers'],['gallery','Browse the test images and detections'],['models','Spin the 3D housing and PCB'],['rtl','Read the Verilog source'],['bom','Price the board']].filter(function(g){return info[g[0]]});
  h+='<div class="start"><h2 style="margin:0;border:0;font-size:1.05em">Start here</h2><ol>'+guide.map(function(g){return '<li><a href="#/'+g[0]+'">'+esc(info[g[0]].title)+'</a> - '+g[1]+'</li>'}).join('')+'</ol><p class="hint" style="margin:8px 0 0">Tip: press <kbd>Ctrl</kbd> <kbd>K</kbd> or <kbd>/</kbd> to jump to any page, RTL module, part, net or test image. Press <kbd>?</kbd> for all shortcuts.</p></div>';
  var h1=$('h1',home),lead=$('.lead',home),anchor=lead||h1,box=el('div',null,h);
  if(anchor&&anchor.parentNode)anchor.parentNode.insertBefore(box,anchor.nextSibling);else home.insertBefore(box,home.firstChild);
}

/* ---------- gallery ---------- */
var gal={done:false,byName:{}};
function galErrOK(i,m){
  var e=i.pose?i.pose.t_mm:null;
  switch(m){case 'miss':return i.vis-i.found>0;case 'false':return (i.false||0)+(i.unseen||0)>0;case 'e2':return e!=null&&e>2;case 'e5':return e!=null&&e>5;case 'nopose':return !i.pose;case 'perfect':return i.vis===i.found&&!(i.false||0)&&!(i.unseen||0);default:return true}}
function galApply(){
  var grid=$('#g-grid'),sel=$('#ui-gerr');if(!grid||!sel)return;var m=sel.value,shown=0,n=0;
  $$('.gitem',grid).forEach(function(it){n++;var im=gal.byName[it.querySelector('img').getAttribute('alt')],ok=!im||galErrOK(im,m);it.classList.toggle('ui-hide',!ok);if(ok)shown++;
    if(!it.hasAttribute('tabindex')){it.tabIndex=0;it.setAttribute('role','button')}});
  var cnt=$('#g-count');if(cnt)cnt.textContent=(m?shown+' of '+n:n)+' images';
  var em=$('.gempty',grid);if(n&&!shown){if(!em)grid.appendChild(el('div',{class:'gempty'},'No images match these filters. <button type="button" id="ui-greset" class="sm">Reset filters</button>'))}else if(em)em.remove();
}
function galUrl(){if(curId()!=='gallery')return;var m=$('#g-modal'),title=$('#m-title').textContent.split('  [')[0];
  setQuery({q:$('#g-search').value.trim(),cat:$('#g-cat').value,sort:$('#g-sort').value==='cat'?'':$('#g-sort').value,err:$('#ui-gerr').value,img:m&&!m.hidden?title:''})}
var zs={s:1,x:0,y:0};
function zApply(){var w=$('.zoomclip');if(!w)return;var W=w.clientWidth,H=w.clientHeight;zs.s=Math.max(1,Math.min(10,zs.s));
  zs.x=Math.min(0,Math.max(W*(1-zs.s),zs.x));zs.y=Math.min(0,Math.max(H*(1-zs.s),zs.y));
  var t='translate('+zs.x+'px,'+zs.y+'px) scale('+zs.s+')';$$('.imgwrap,.cmpwrap',$('#g-modal')).forEach(function(n){n.style.transform=zs.s===1?'':t});
  var zl=$('#ui-zl');if(zl)zl.textContent=Math.round(zs.s*100)+'%'}
function zReset(){zs={s:1,x:0,y:0};zApply()}
function zAt(f,mx,my){var ns=Math.max(1,Math.min(10,zs.s*f)),r=ns/zs.s;zs.x=mx-(mx-zs.x)*r;zs.y=my-(my-zs.y)*r;zs.s=ns;zApply()}
function galInit(){
  if(window.Gallery)return;   /* assets/gallery.js provides the frame viewer (own modal DOM) */
  if(gal.done||!window.GALLERY||!$('#g-grid')||!$('#g-modal'))return;gal.done=true;
  GALLERY.images.forEach(function(i){gal.byName[i.name]=i});
  /* error filter */
  var sort=$('#g-sort'),es=el('select',{id:'ui-gerr','aria-label':'Filter by detection result'},'<option value="">all results</option><option value="miss">missed tags</option><option value="false">false / unseen detections</option><option value="e2">position error &gt; 2 mm</option><option value="e5">position error &gt; 5 mm</option><option value="nopose">no pose</option><option value="perfect">all tags found, no false</option>');
  sort.parentNode.insertBefore(es,sort.nextSibling);
  var rs=el('button',{type:'button',class:'sm'},'reset');sort.parentNode.insertBefore(rs,es.nextSibling);
  function reset(){$('#g-search').value='';$('#g-cat').value='';sort.value='cat';es.value='';['g-search','g-cat','g-sort'].forEach(function(id){$('#'+id).dispatchEvent(new Event('input'))});galApply();galUrl()}
  rs.onclick=reset;
  es.addEventListener('change',function(){galApply();galUrl()});
  ['g-search','g-cat','g-sort'].forEach(function(id){$('#'+id).addEventListener('input',function(){setTimeout(galUrl,0)})});
  var grid=$('#g-grid');new MutationObserver(galApply).observe(grid,{childList:true});
  grid.addEventListener('click',function(e){if(e.target.id==='ui-greset')reset()});
  grid.addEventListener('keydown',function(e){if((e.key==='Enter'||e.key===' ')&&e.target.classList.contains('gitem')){e.preventDefault();e.target.click()}});
  /* modal: zoom/pan clip + compare */
  var iw=$('.imgwrap',$('#g-modal')),parent=iw.parentNode;
  var row=el('div',{class:'cmprow'}),c1=el('div',{class:'cmpcol'}),clip=el('div',{class:'zoomclip'}),c2=el('div',{class:'cmpcol',hidden:'hidden'}),clip2=el('div',{class:'zoomclip'});
  parent.insertBefore(row,iw);row.appendChild(c1);c1.appendChild(clip);clip.appendChild(iw);row.appendChild(c2);
  var cw=el('div',{class:'cmpwrap',style:'line-height:0'},'<img id="ui-cmpimg" alt="comparison frame" style="width:100%;display:block;background:#000">');clip2.appendChild(cw);
  c2.appendChild(el('figcaption',{id:'ui-cmpcap'}));c2.appendChild(clip2);
  var zb=el('div',{class:'zbar'},'<b>Zoom</b><button type="button" id="ui-zo" class="sm" aria-label="Zoom out">-</button><span id="ui-zl" style="min-width:3em;text-align:center">100%</span><button type="button" id="ui-zi" class="sm" aria-label="Zoom in">+</button><button type="button" id="ui-zr" class="sm">reset</button><span class="hint">wheel / pinch zoom, drag to pan, double-click resets</span><span class="grow"></span><label>Compare with <select id="ui-cmp"><option value="">(none)</option>'+GALLERY.images.map(function(i){return '<option>'+esc(i.name)+'</option>'}).join('')+'</select></label>');
  var vctl=$('.vctl',$('#g-modal'));vctl.parentNode.insertBefore(zb,vctl);
  $('#ui-zi').onclick=function(){var w=clip.clientWidth,h=clip.clientHeight;zAt(1.4,w/2,h/2)};$('#ui-zo').onclick=function(){var w=clip.clientWidth,h=clip.clientHeight;zAt(1/1.4,w/2,h/2)};$('#ui-zr').onclick=zReset;
  var dragging=null;
  function bindClip(c){
    c.addEventListener('wheel',function(e){e.preventDefault();var r=c.getBoundingClientRect();zAt(e.deltaY<0?1.15:1/1.15,e.clientX-r.left,e.clientY-r.top)},{passive:false});
    c.addEventListener('pointerdown',function(e){if(e.button!==0)return;dragging={x:e.clientX,y:e.clientY,ox:zs.x,oy:zs.y};c.classList.add('pan');try{c.setPointerCapture(e.pointerId)}catch(x){}});
    c.addEventListener('pointermove',function(e){if(!dragging)return;zs.x=dragging.ox+e.clientX-dragging.x;zs.y=dragging.oy+e.clientY-dragging.y;zApply()});
    function up(){dragging=null;c.classList.remove('pan')}c.addEventListener('pointerup',up);c.addEventListener('pointercancel',up);
    c.addEventListener('dblclick',zReset)}
  bindClip(clip);bindClip(clip2);
  function cmpUpdate(){var n=$('#ui-cmp').value,on=!!n;c2.hidden=!on;row.classList.toggle('on',on);
    if(on){var i=gal.byName[n];$('#ui-cmpimg').src='frames/'+n+'.jpg';$('#ui-cmpcap').innerHTML='<b>'+esc(n)+'</b> ['+esc(i.cat)+'] '+i.found+'/'+i.vis+' tags, '+(i.pose?'pos err '+i.pose.t_mm.toFixed(1)+' mm':'no pose')}
    zReset();setTimeout(function(){window.dispatchEvent(new Event('resize'));zApply()},30)}
  $('#ui-cmp').addEventListener('change',cmpUpdate);
  /* title change = new image; hidden change = open/close */
  var lastT='';
  new MutationObserver(function(){var t=$('#m-title').textContent;if(t!==lastT){lastT=t;zReset();var n=$('#ui-cmp').value;if(n)cmpUpdate();galUrl()}}).observe($('#m-title'),{childList:true,characterData:true,subtree:true});
  new MutationObserver(function(){if($('#g-modal').hidden){galUrl()}else{galUrl();setTimeout(function(){$('#m-close').focus&&$('#m-close').focus()},0)}}).observe($('#g-modal'),{attributes:true,attributeFilter:['hidden']});
  /* keys */
  document.addEventListener('keydown',function(e){var m=$('#g-modal');if(!m||m.hidden||typing(e.target)||e.ctrlKey||e.metaKey||e.altKey)return;var k=e.key;
    if(k==='+'||k==='='){$('#ui-zi').click()}else if(k==='-'||k==='_'){$('#ui-zo').click()}else if(k==='0'){zReset()}
    else if(k==='c'){var s=$('#ui-cmp');if(s.value)s.value='';else{var nm=$('#m-title').textContent.split('  [')[0],ims=GALLERY.images,ix=0;ims.forEach(function(i,j){if(i.name===nm)ix=j});s.value=ims[(ix+1)%ims.length].name}cmpUpdate()}
    else if(k>='1'&&k<='4'){var b=$('#'+['m-gt','m-chip','m-invis','m-ids'][+k-1]);b.checked=!b.checked;b.onchange&&b.onchange()}
    else if(k==='o'){var bs=['m-gt','m-chip','m-invis'].map(function(i){return $('#'+i)}),anyOn=bs.some(function(b){return b.checked});bs.forEach(function(b){b.checked=!anyOn;b.onchange&&b.onchange()})}
    else return;e.preventDefault()});
  /* backdrop click closes */
  $('#g-modal').addEventListener('mousedown',function(e){if(e.target===this)$('#m-close').click()});
  window.addEventListener('resize',function(){zApply()});
  galApply();
}
function galRoute(q){
  galInit();if(!gal.done)return;
  var any=false;
  if(q.q!=null||q.cat||q.sort||q.err){
    $('#g-search').value=q.q||'';$('#g-cat').value=q.cat||'';$('#g-sort').value=q.sort||'cat';$('#ui-gerr').value=q.err||'';
    ['g-search','g-cat','g-sort'].forEach(function(id){$('#'+id).dispatchEvent(new Event('input'))});galApply();any=true}
  if(q.img){var it=$$('#g-grid .gitem').filter(function(x){return x.querySelector('img').getAttribute('alt')===q.img})[0];
    if(!it){$('#g-search').value='';$('#g-cat').value='';$('#ui-gerr').value='';['g-search','g-cat'].forEach(function(id){$('#'+id).dispatchEvent(new Event('input'))});galApply();
      it=$$('#g-grid .gitem').filter(function(x){return x.querySelector('img').getAttribute('alt')===q.img})[0]}
    if(it)it.click()}
}

/* ---------- 3D viewers ---------- */
var VP={h:{c:[0,0,10],d:190,v:{iso:[1,-1.3,.9],top:[0,.001,1],bottom:[0,.001,-1],front:[0,-1,.06],side:[1,0,.06],back:[0,1,.06]}},
        p:{c:[0,0,0],d:120,v:{iso:[.3,-.5,1],top:[0,.001,1],bottom:[0,.001,-1],front:[0,-1,.08],side:[1,0,.08],back:[0,1,.08]}}};
function viewerInit(){
  $$('.viewer-wrap').forEach(function(w){
    if(w.__ui)return;var v=$('.viewer',w);if(!v)return;w.__ui=1;
    var key=v.id==='v-housing'?'h':v.id==='v-pcb'?'p':null;
    var box=el('div',{class:'vbox',style:'position:relative'});v.parentNode.insertBefore(box,v);box.appendChild(v);
    var hint=el('div',{class:'vhint'},'drag: rotate &middot; wheel: zoom &middot; right-drag: pan');box.appendChild(hint);
    var fade=function(){hint.classList.add('fade')};setTimeout(fade,9000);v.addEventListener('pointerdown',fade);v.addEventListener('wheel',fade,{passive:true});
    $$('.vmsg',v).forEach(function(m){m.classList.add('load')});
    var tools=el('div',{class:'vtools'},'<span class="lbl">View</span>'+['iso','top','bottom','front','side','back'].map(function(n){return '<button type="button" class="sm" data-pv="'+n+'">'+n+'</button>'}).join('')+'<span class="grow" style="flex:1"></span><button type="button" class="sm" data-act="parts" aria-pressed="true">parts list</button><button type="button" class="sm" data-act="fs">fullscreen</button>');
    box.parentNode.insertBefore(tools,box.nextSibling);
    tools.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
      if(b.getAttribute('data-pv')){var V=window.__viewers&&window.__viewers[key];if(!V||V.dead){toast(V?'3D unavailable':'viewer is still loading');return}var P=VP[key];V.view(P.c,P.d,P.v[b.getAttribute('data-pv')])}
      else if(b.getAttribute('data-act')==='parts'){var c=$('.vctl',w);if(c){var hid=c.classList.toggle('collapsed');b.setAttribute('aria-pressed',!hid);pref('parts',hid?'0':'1')}}
      else if(b.getAttribute('data-act')==='fs'){if(document.fullscreenElement)document.exitFullscreen();else if(w.requestFullscreen)w.requestFullscreen().catch(function(){toast('fullscreen not available')});else toast('fullscreen not supported')}});
    if(key===null)$$('[data-pv]',tools).forEach(function(b){b.hidden=true}),($('.lbl',tools).hidden=true);
    if(pref('parts')==='0'){var c=$('.vctl',w);if(c){c.classList.add('collapsed');$('[data-act=parts]',tools).setAttribute('aria-pressed','false')}}
    new MutationObserver(function(){var m=$('.vmsg',v);if(m&&!/loading/i.test(m.textContent)){m.classList.remove('load');m.classList.add('err');if(/webgl/i.test(m.textContent)&&!m.__x){m.__x=1;m.innerHTML+='<br><small>Try enabling hardware acceleration in the browser settings, or use the rendered images on the Renders tab.</small>'}}}).observe(v,{childList:true,subtree:true});
  });
}
document.addEventListener('fullscreenchange',function(){setTimeout(function(){if(window.__resize3d)window.__resize3d()},80)});

/* ---------- rtl ---------- */
var rtl={done:false,hits:[],idx:-1};
function rtlFile(){var h=parseHash();return h.id==='rtl'&&h.parts[1]?decodeURIComponent(h.parts[1]):''}
function rtlSelectLines(){
  var pre=$('#rtl-src');if(!pre)return;var q=parseHash().q.L;$$('.ln.sel',pre).forEach(function(l){l.classList.remove('sel')});if(!q)return;
  var m=q.match(/^(\d+)(?:-(\d+))?$/);if(!m)return;var a=+m[1],b=+(m[2]||m[1]),ls=$$('.ln',pre);
  for(var i=a;i<=b&&i<=ls.length;i++)ls[i-1].classList.add('sel');if(ls[a-1])ls[a-1].scrollIntoView({block:'center'})}
function rtlHits(){var pre=$('#rtl-src');rtl.hits=$$('.ln.hit',pre);rtl.idx=rtl.hits.length?0:-1;rtlShow()}
function rtlShow(){$$('.ln.cur').forEach(function(l){l.classList.remove('cur')});var c=$('#ui-rcnt');
  if(rtl.idx>=0){var l=rtl.hits[rtl.idx];l.classList.add('cur');l.scrollIntoView({block:'center'});c.textContent=(rtl.idx+1)+' / '+rtl.hits.length}
  else c.textContent=$('#rtl-find').value?'no matches':''}
function rtlStep(d){if(!rtl.hits.length)return;rtl.idx=(rtl.idx+d+rtl.hits.length)%rtl.hits.length;rtlShow()}
function rtlLinkUses(){var u=$('#rtl-uses');if(!u||!window.RTL)return;var map={};RTL.mods.forEach(function(m){m.modules.forEach(function(n){map[n]=m.file})});
  $$('code',u).forEach(function(c){if(c.__l)return;c.__l=1;c.innerHTML=c.textContent.split(', ').map(function(n){return map[n]?'<a href="#/rtl/'+encodeURIComponent(map[n])+'">'+esc(n)+'</a>':esc(n)}).join(', ')})}
function rtlInit(){
  if(rtl.done||!window.RTL||!$('#rtl-view'))return;rtl.done=true;
  var page=$('#page-rtl'),tw=$('.tablewrap',page)||$('#rtltable');
  /* jump list */
  var opts='<option value="">Jump to file or module...</option><optgroup label="Files">'+RTL.mods.map(function(m){return '<option value="'+esc(m.file)+'">'+esc(m.file)+(m.modules.length?'  ('+esc(m.modules.join(', '))+')':'')+'</option>'}).join('')+'</optgroup>';
  var mo=[];RTL.mods.forEach(function(m){m.modules.forEach(function(n){mo.push([n,m.file])})});mo.sort();
  opts+='<optgroup label="Modules">'+mo.map(function(x){return '<option value="'+esc(x[1])+'">'+esc(x[0])+'  in '+esc(x[1])+'</option>'}).join('')+'</optgroup>';
  var jump=el('select',{id:'ui-rjump','aria-label':'Jump to RTL file or module'},opts),jb=el('div',{class:'rtlbar'});jb.appendChild(jump);
  jb.appendChild(el('span',{class:'hint'},'or click a row below'));
  var anchor=tw&&tw.closest('.tablewrap')||$('#rtltable');anchor.parentNode.insertBefore(jb,anchor);
  jump.onchange=function(){if(jump.value)location.hash='#/rtl/'+encodeURIComponent(jump.value)};
  /* toolbar in viewer */
  var find=$('#rtl-find'),bar=el('div',{class:'rtlbar'},'<span id="ui-rbtns"></span>');
  find.parentNode.insertBefore(bar,find);bar.appendChild(find);
  find.setAttribute('aria-label','Find in file');
  var b=function(id,t,title){return el('button',{type:'button',id:id,class:'sm',title:title||t},t)};
  var prev=b('ui-rprev','prev','Previous match (Shift+Enter)'),next=b('ui-rnext','next','Next match (Enter)'),cnt=el('span',{class:'cnt',id:'ui-rcnt','aria-live':'polite'});
  var cp=b('ui-rcopy','copy file','Copy the whole file'),wr=b('ui-rwrap','wrap lines','Toggle line wrapping'),fm=b('ui-rfm','A-','Smaller text'),fp=b('ui-rfp','A+','Larger text'),cl=b('ui-rlink','copy link','Copy a link to the selected line(s)');
  [prev,next,cnt,cp,cl,wr,fm,fp].forEach(function(n){bar.appendChild(n)});
  var pre=$('#rtl-src'),fs=parseFloat(pref('rtl.fs'))||0.9;
  function setFs(){pre.style.setProperty('--srcfs',fs+'em');pref('rtl.fs',String(fs))}setFs();
  fm.onclick=function(){fs=Math.max(.6,fs-.1);setFs()};fp.onclick=function(){fs=Math.min(1.8,fs+.1);setFs()};
  function setWrap(on){pre.classList.toggle('wrap',on);wr.setAttribute('aria-pressed',on);pref('rtl.wrap',on?'1':'0')}setWrap(pref('rtl.wrap')==='1');wr.onclick=function(){setWrap(!pre.classList.contains('wrap'))};
  cp.onclick=function(){copyText($$('.ln',pre).map(function(l){return l.textContent}).join('\n'),'file copied')};
  cl.onclick=function(){copyText(location.href,'link copied')};
  prev.onclick=function(){rtlStep(-1)};next.onclick=function(){rtlStep(1)};
  find.addEventListener('input',rtlHits);
  find.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();rtlStep(e.shiftKey?-1:1)}});
  /* line anchors */
  pre.addEventListener('click',function(e){var ln=e.target.closest('.ln');if(!ln)return;var rect=ln.getBoundingClientRect(),fsz=parseFloat(getComputedStyle(ln).fontSize);
    if(e.clientX-rect.left>fsz*4.4)return;var ls=$$('.ln',pre),n=ls.indexOf(ln)+1,f=rtlFile(),cur=parseHash().q.L||'',m=cur.match(/^(\d+)/),L=String(n);
    if(e.shiftKey&&m)L=Math.min(+m[1],n)+'-'+Math.max(+m[1],n);
    try{history.replaceState(null,'','#/rtl/'+encodeURIComponent(f)+'?L='+L)}catch(x){}rtlSelectLines();copyText(location.href,'link to line '+L+' copied')});
  new MutationObserver(function(){rtl.hits=[];rtl.idx=-1;$('#ui-rcnt').textContent='';rtlLinkUses();rtlSelectLines();var f=rtlFile();if(f)jump.value=f}).observe(pre,{childList:true});
  $('#rtl-view').addEventListener('keydown',function(){});
}

/* ---------- route glue ---------- */
var lastPid=null;
function afterRoute(){
  var h=parseHash(),pid=info[h.id]?h.id:'home';
  document.title=info[pid].title+' - AprilTag camera';
  crumbs.innerHTML=(pid==='home'?'<span>Home</span>':'<a href="#/home">Home</a><span class="sep">/</span><span>'+esc(info[pid].group)+'</span><span class="sep">/</span><span aria-current="page">'+esc(info[pid].title)+'</span>');
  $$('#navlinks .navlink').forEach(function(a){if(a.classList.contains('on'))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  if(window.__navOpenGroup)window.__navOpenGroup(pid);
  var on=$('#navlinks .navlink.on');if(on&&on.scrollIntoView&&lastPid!==pid)on.scrollIntoView({block:'nearest'});
  buildToc(pid);enhancePage(pid);startSpy(pid);
  setTimeout(function(){enhancePage(pid)},500);   // pages that build tables lazily
  if(pid==='gallery')galRoute(h.q);
  if(pid==='models')viewerInit();
  if(pid==='rtl'){rtlInit();rtlLinkUses();rtlSelectLines()}
  if(pid==='bom'&&h.q.q!=null){var bq=$('#bom-q');if(bq){bq.value=h.q.q;bq.dispatchEvent(new Event('input'))}}
  if(pid==='netlist'&&h.q.q!=null){var nf=$('input.filter[data-target="nettable"]');if(nf){nf.value=h.q.q;nf.dispatchEvent(new Event('input'))}}
  if(h.q.find){var fi=$('#page-'+pid+' input[type=search]');if(fi&&!fi.value){fi.value=h.q.find;fi.dispatchEvent(new Event('input'))}}
  if(h.parts[1]&&pid!=='rtl'){var t=document.getElementById(pid+'--'+h.parts[1]);if(t)setTimeout(function(){t.scrollIntoView()},30)}
  lastPid=pid;
}
window.addEventListener('hashchange',afterRoute);
window.__uiRefresh=function(){tocSync();afterRoute()};
buildDash();
afterRoute();
document.body.classList.add('ui-ready');
})();
