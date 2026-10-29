#!/usr/bin/env python3
"""Generate docs/bom/index.html from docs/bom/bom.json.

Usage: python docs/bom/build_bom.py
Edit bom.json (unit_price, link, checked, status) and re-run. An item counts toward the verified
total only if status == "verified" (needs a link and a unit_price). Items with "fixed": true are
one-time per-order costs and are not multiplied by the board count.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "bom.json"), encoding="utf-8"))
for i, it in enumerate(data["items"]):
    if it.get("status") == "verified" and (it.get("unit_price") is None or not it.get("link")):
        sys.exit("item %d (%s) marked verified without price/link" % (i, it.get("value")))
blob = json.dumps(data).replace("</", "<\\/")
html = TEMPLATE = None

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AprilTag Camera BOM</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c2128;--mut:#5b6573;--card:#fff;--bd:#d8dde4;--acc:#0b63c5;--ok:#17703a;--warn:#a15c00;--bad:#b3261e;--okbg:#e4f4ea;--warnbg:#fff1d6;--badbg:#fde7e5}
@media (prefers-color-scheme:dark){:root{--bg:#12151a;--fg:#e4e8ee;--mut:#98a2b0;--card:#1b2027;--bd:#2f3742;--acc:#6db0ff;--ok:#6fd49a;--warn:#f0b45a;--bad:#ff8a80;--okbg:#17301f;--warnbg:#38290d;--badbg:#3b1b19}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:8px 10px}
.card b{display:block;font-size:20px}.card span{color:var(--mut);font-size:12px}
.ctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
input,select,button{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:6px 8px}
button{cursor:pointer}button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
#q{flex:1 1 180px;min-width:0}#mult{width:80px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd)}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd);vertical-align:top}
th{cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--card)}th.s::after{content:" \25B2"}th.s.d::after{content:" \25BC"}
td.n,th.n{text-align:right}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-word}
tr.grp td{background:var(--bg);font-weight:600}
.tag{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;white-space:nowrap}
.v{background:var(--okbg);color:var(--ok)}.u{background:var(--warnbg);color:var(--warn)}.h{background:var(--badbg);color:var(--bad)}
.note{color:var(--mut);font-size:12px;margin-top:3px}.hard{color:var(--bad);font-size:12px;margin-top:3px}
a{color:var(--acc)}tfoot td{font-weight:600}.foot{color:var(--mut);font-size:12px;margin-top:12px}
@media (max-width:760px){
 table,thead,tbody,tfoot,tr,td{display:block;width:100%}thead{display:none}
 tr{border-bottom:2px solid var(--bd);padding:6px 0}td{border:0;padding:2px 8px;text-align:left!important}
 td[data-l]::before{content:attr(data-l) ": ";color:var(--mut);font-size:12px}
}
</style></head><body><main>
<h1>AprilTag Camera - Parts &amp; Cost</h1>
<p class="sub" id="sub"></p>
<div class="cards">
 <div class="card"><b id="tV">-</b><span>Verified total (<span class="bn"></span> board(s))</span></div>
 <div class="card"><b id="tVb">-</b><span>Verified, per board (recurring)</span></div>
 <div class="card"><b id="tF">-</b><span>Verified one-time (fab setup etc.)</span></div>
 <div class="card"><b id="tU">-</b><span>Unverified lines (not in total)</span></div>
 <div class="card"><b id="tH">-</b><span>Hard-to-source lines</span></div>
</div>
<div class="ctl">
 <input id="q" type="search" placeholder="Filter: designator, MPN, value, vendor...">
 <select id="cat"><option value="">All categories</option></select>
 <select id="st"><option value="">All status</option><option value="verified">Verified</option><option value="unverified">Unverified</option><option value="hard">Hard to source</option></select>
 <label>Boards <input id="mult" type="number" min="1" value="1"></label>
 <button data-m="1">1</button><button data-m="10">10</button><button data-m="100">100</button>
 <button id="grp">Group by category</button>
</div>
<table><thead><tr id="hd"></tr></thead><tbody id="tb"></tbody><tfoot id="tf"></tfoot></table>
<p class="foot" id="ft"></p>
<script>
var DATA=__DATA__;
var cols=[["category","Category"],["designators","Designators"],["qty","Qty",1],["value","Value / description"],["mpn","MPN"],["mfr","Mfr"],["link","Buy"],["unit_price","Unit $",1],["ext","Ext $ (x boards)",1],["checked","Checked"],["status","Status"]];
var S={k:"category",d:false,g:false,m:1};
var items=DATA.items.map(function(x,i){x.i=i;return x});
function $(i){return document.getElementById(i)}
function money(v){return v==null?"-":"$"+v.toFixed(v<1?4:2)}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function mult(x){return x.fixed?1:S.m}
function ext(x){return x.unit_price==null?null:x.qty*x.unit_price*mult(x)}
function isV(x){return x.status==="verified"&&x.unit_price!=null&&x.link}
function linkify(t){return esc(t).replace(/(https?:\/\/[^\s)]+)/g,'<a href="$1" target="_blank" rel="noopener">link</a>')}
function head(){$("hd").innerHTML=cols.map(function(c,i){return '<th data-k="'+c[0]+'" class="'+(c[2]?"n ":"")+(S.k===c[0]?"s"+(S.d?" d":""):"")+'">'+c[1]+'</th>'}).join("");
 Array.prototype.forEach.call($("hd").children,function(th){th.onclick=function(){var k=th.dataset.k;if(S.k===k)S.d=!S.d;else{S.k=k;S.d=false}render()}})}
function row(x){var e=ext(x),v=isV(x);
 var st=v?'<span class="tag v">verified</span>':'<span class="tag u">unverified</span>';
 if(x.hard)st+=' <span class="tag h">hard to source</span>';
 var buy=x.link?'<a href="'+esc(x.link)+'" target="_blank" rel="noopener">'+esc(x.link.replace(/^https?:\/\/(www\.)?/,"").split("/")[0])+'</a>':"";
 var d=esc(x.value);
 if(x.hard)d+='<div class="hard">'+linkify(x.hard)+'</div>';
 if(x.notes)d+='<div class="note">'+linkify(x.notes)+'</div>';
 if(x.fixed)d+='<div class="note">One-time per order (not multiplied by boards).</div>';
 var mp=esc(x.mpn)+(x.mpn&&x.mpn_suggested?' <span class="note">(suggested)</span>':"");
 var cells=[esc(x.category),'<span class="mono">'+esc(x.designators)+'</span>',x.qty,d,'<span class="mono">'+mp+'</span>',esc(x.mfr),buy,money(x.unit_price),e==null?"-":money(e)+(v?"":'*'),esc(x.checked),st];
 return '<tr>'+cells.map(function(c,i){return '<td data-l="'+cols[i][1]+'" class="'+(cols[i][2]?"n":"")+'">'+c+'</td>'}).join("")+'</tr>'}
function render(){
 var q=$("q").value.toLowerCase(),cat=$("cat").value,st=$("st").value;
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
 $("tb").innerHTML=html||'<tr><td colspan="11">No matching parts.</td></tr>';
 // totals over all items (unfiltered)
 var perBoard=0,fixed=0,unv=0,hard=0;
 items.forEach(function(x){if(isV(x)){if(x.fixed)fixed+=x.qty*x.unit_price;else perBoard+=x.qty*x.unit_price}else unv++;if(x.hard)hard++});
 var tot=perBoard*S.m+fixed;
 Array.prototype.forEach.call(document.getElementsByClassName("bn"),function(e){e.textContent=S.m});
 $("tV").textContent=money(tot);$("tVb").textContent=money(perBoard);$("tF").textContent=money(fixed);$("tU").textContent=unv+" of "+items.length;$("tH").textContent=hard;
 $("tf").innerHTML='<tr><td colspan="8">Verified total for '+S.m+' board(s) ('+money(perBoard)+' x '+S.m+' + '+money(fixed)+' one-time)</td><td class="n">'+money(tot)+'</td><td colspan="2">Per board avg: '+money(tot/S.m)+'</td></tr>';
 Array.prototype.forEach.call(document.querySelectorAll("[data-m]"),function(b){b.className=(+b.dataset.m===S.m)?"on":""});
 $("grp").className=S.g?"on":"";head()}
$("sub").textContent=DATA.project+" - prices checked "+DATA.price_checked+" - sources: "+DATA.sources;
$("ft").textContent=DATA.notes+" * = extended price shown but excluded from verified total. Fixed-cost scaling (e.g. fab setup, stencil, 5-board minimum) is not modelled for quantities above one order.";
var cats=[];items.forEach(function(x){if(cats.indexOf(x.category)<0)cats.push(x.category)});
cats.forEach(function(c){var o=document.createElement("option");o.value=o.textContent=c;$("cat").appendChild(o)});
$("q").oninput=$("cat").onchange=$("st").onchange=render;
$("mult").oninput=function(){var v=parseInt(this.value,10);S.m=v>0?v:1;render()};
Array.prototype.forEach.call(document.querySelectorAll("[data-m]"),function(b){b.onclick=function(){S.m=+b.dataset.m;$("mult").value=S.m;render()}});
$("grp").onclick=function(){S.g=!S.g;render()};
render();
</script></main></body></html>
"""

html = TEMPLATE.replace("__DATA__", blob)
out = os.path.join(HERE, "index.html")
open(out, "w", encoding="utf-8").write(html)
v = sum(i["qty"] * i["unit_price"] for i in data["items"] if i["status"] == "verified" and not i.get("fixed"))
f = sum(i["qty"] * i["unit_price"] for i in data["items"] if i["status"] == "verified" and i.get("fixed"))
u = sum(1 for i in data["items"] if i["status"] != "verified")
print("wrote %s: verified per-board %.2f + one-time %.2f = %.2f (1 board); %d/%d unverified" % (out, v, f, v + f, u, len(data["items"])))
