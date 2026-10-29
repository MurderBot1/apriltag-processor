(function(){
'use strict';
var D=window.BOM;if(!D)return;
var started=false;
window.initBom=function(){
if(started)return;started=true;
var root=document.getElementById('page-bom');
function $(i){return document.getElementById('bom-'+i)}
var cols=[["category","Category"],["designators","Designators"],["qty","Qty",1],["value","Value / description"],["mpn","MPN"],["mfr","Mfr"],["link","Buy"],["unit_price","Unit $",1],["ext","Ext $",1],["checked","Checked"],["status","Status"]];
var S={k:"category",d:false,g:false,m:1};
var items=D.items.map(function(x,i){x.i=i;return x});
function money(v){return v==null?"-":"$"+v.toFixed(v<1?4:2)}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function mult(x){return x.fixed?1:S.m}
function ext(x){return x.unit_price==null?null:x.qty*x.unit_price*mult(x)}
function isV(x){return x.status==="verified"&&x.unit_price!=null&&x.link}
function linkify(t){return esc(t).replace(/(https?:\/\/[^\s)]+)/g,'<a href="$1" target="_blank" rel="noopener">link</a>')}
function head(){var hd=$('hd');hd.innerHTML=cols.map(function(c){return '<th data-k="'+c[0]+'" class="'+(c[2]?"n ":"")+(S.k===c[0]?"s"+(S.d?" d":""):"")+'">'+c[1]+'</th>'}).join("");
 Array.prototype.forEach.call(hd.children,function(th){th.onclick=function(){var k=th.getAttribute('data-k');if(S.k===k)S.d=!S.d;else{S.k=k;S.d=false}render()}})}
function row(x){var e=ext(x),v=isV(x);
 var st=v?'<span class="tag v">verified</span>':'<span class="tag u">unverified</span>';
 if(x.hard)st+=' <span class="tag h">hard to source</span>';
 var buy=x.link?'<a href="'+esc(x.link)+'" target="_blank" rel="noopener">'+esc(x.link.replace(/^https?:\/\/(www\.)?/,"").split("/")[0])+'</a>':"";
 var d=esc(x.value);
 if(x.hard)d+='<div class="bnote hard">'+linkify(x.hard)+'</div>';
 if(x.notes)d+='<div class="bnote">'+linkify(x.notes)+'</div>';
 if(x.fixed)d+='<div class="bnote">One-time per order (not multiplied by boards).</div>';
 var mp=esc(x.mpn)+(x.mpn&&x.mpn_suggested?' <span class="bnote">(suggested)</span>':"");
 var cells=[esc(x.category),'<span class="pins">'+esc(x.designators)+'</span>',x.qty,d,'<span class="pins">'+mp+'</span>',esc(x.mfr),buy,money(x.unit_price),e==null?"-":money(e)+(v?"":'*'),esc(x.checked),st];
 return '<tr>'+cells.map(function(c,i){return '<td data-l="'+cols[i][1]+'" class="'+(cols[i][2]?"n":"")+'">'+c+'</td>'}).join("")+'</tr>'}
function render(){
 var q=$('q').value.toLowerCase(),cat=$('cat').value,st=$('st').value;
 var L=items.filter(function(x){
  if(cat&&x.category!==cat)return false;
  if(st==="verified"&&!isV(x))return false;if(st==="unverified"&&isV(x))return false;if(st==="hard"&&!x.hard)return false;
  return !q||[x.category,x.designators,x.value,x.mpn,x.mfr,x.notes,x.hard].join(" ").toLowerCase().indexOf(q)>=0});
 L.sort(function(a,b){var k=S.k,A=k==="ext"?ext(a):a[k],B=k==="ext"?ext(b):b[k];
  if(A==null||A==="")A=S.d?-Infinity:Infinity;if(B==null||B==="")B=S.d?-Infinity:Infinity;
  var r=typeof A==="number"&&typeof B==="number"?(A===B?0:A<B?-1:1):String(A).localeCompare(String(B),undefined,{numeric:true});
  return (S.d?-r:r)||a.i-b.i});
 var html="",last=null;
 L.forEach(function(x){if(S.g&&x.category!==last){last=x.category;var sub=0,n=0;L.forEach(function(y){if(y.category===last&&isV(y)){sub+=ext(y)}if(y.category===last)n++});
   html+='<tr class="grp"><td colspan="11">'+esc(last)+' - '+n+' line(s), verified subtotal '+money(sub)+'</td></tr>'}html+=row(x)});
 $('tb').innerHTML=html||'<tr><td colspan="11">No matching parts.</td></tr>';
 var perBoard=0,fixed=0,unv=0,hard=0;
 items.forEach(function(x){if(isV(x)){if(x.fixed)fixed+=x.qty*x.unit_price;else perBoard+=x.qty*x.unit_price}else unv++;if(x.hard)hard++});
 var tot=perBoard*S.m+fixed;
 Array.prototype.forEach.call(root.getElementsByClassName("bn"),function(e){e.textContent=S.m});
 $('tV').textContent=money(tot);$('tVb').textContent=money(perBoard);$('tF').textContent=money(fixed);$('tU').textContent=unv+" of "+items.length;$('tH').textContent=hard;
 $('tf').innerHTML='<tr><td colspan="8">Verified total for '+S.m+' board(s) ('+money(perBoard)+' x '+S.m+' + '+money(fixed)+' one-time)</td><td class="n">'+money(tot)+'</td><td colspan="2">Per board avg: '+money(tot/S.m)+'</td></tr>';
 Array.prototype.forEach.call(root.querySelectorAll("[data-m]"),function(b){b.className=(+b.getAttribute('data-m')===S.m)?"on":""});
 $('grp').className=S.g?"on":"";head()}
$('sub').textContent=D.project+" - prices checked "+D.price_checked+" - sources: "+D.sources;
$('ft').textContent=D.notes+" * = extended price shown but excluded from verified total. Fixed-cost scaling (e.g. fab setup, stencil, 5-board minimum) is not modelled for quantities above one order.";
var cats=[];items.forEach(function(x){if(cats.indexOf(x.category)<0)cats.push(x.category)});
cats.forEach(function(c){var o=document.createElement("option");o.value=o.textContent=c;$('cat').appendChild(o)});
$('q').oninput=$('cat').onchange=$('st').onchange=render;
$('mult').oninput=function(){var v=parseInt(this.value,10);S.m=v>0?v:1;render()};
Array.prototype.forEach.call(root.querySelectorAll("[data-m]"),function(b){b.onclick=function(){S.m=+b.getAttribute('data-m');$('mult').value=S.m;render()}});
$('grp').onclick=function(){S.g=!S.g;render()};
render();
};
})();
