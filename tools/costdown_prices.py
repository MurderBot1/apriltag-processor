"""Read LCSC prices/stock through LCSC's product-detail API (same method as docs/bom/AUDIT.md).
    py -3.12 tools/costdown_prices.py C1551826 C2943786 ...   or no args for the study's list -> results/costdown_prices.json
Each entry: code, MPN, package, stock, price ladder (qty -> USD).  Only parts whose page was read are 'verified'."""
import sys, json, subprocess, os, datetime
CODES = dict(
    ecp5_85f='C1551826', ecp5_25f_bg256='C1521614', ecp5_45f_bg381='C1551300', ecp5_45f_bg256='C1550834', artix35='C1521698', gw2a18='C5799574',
    rv1106g3='C5328706', rk3566='C2943786', rk3576='C42388007', rk3588='C5156490', rk3588s='C7422743', imxrt1176='C1020239', imx8mm='C880326',
    t113s3='C5197687', v853='C5137799', rp2350a='C42411118', flash='C190862', ecp5um45_8='C1550814', ecp5_25f_7='C1552129')
codes = dict((c, c) for c in sys.argv[1:]) if len(sys.argv) > 1 else CODES
out = {}
for k, c in codes.items():
    try:
        t = subprocess.run(['curl', '-s', '-m', '30', '-A', 'Mozilla/5.0', f'https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={c}'], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
        r = json.loads(t)['result']
        out[k] = dict(code=c, mpn=r['productModel'], brand=r.get('brandNameEn'), package=r.get('encapStandard'), stock=r.get('stockNumber'),
                      min_buy=r.get('minBuyNumber'), ladder=[(p['ladder'], p['usdPrice']) for p in r.get('productPriceList', [])],
                      catalog=r.get('catalogName'), url=f'https://www.lcsc.com/product-detail/{c}.html', checked=str(datetime.date.today()))
    except Exception as e:
        out[k] = dict(code=c, error=repr(e))
    print(k, out[k].get('mpn'), out[k].get('package'), 'stock', out[k].get('stock'), out[k].get('ladder') or out[k].get('error'))
if len(sys.argv) == 1:
    os.makedirs('results', exist_ok=True); json.dump(out, open('results/costdown_prices.json', 'w'), indent=1)
