"""Generate the BOM / PCB-viewer part thumbnails (site/img/parts/*.webp) by rendering each part's real 3D model.

  py -3.12 render/render_part_thumbs.py [--spp 96] [--only key,key] [--skip-fc]

Pipeline
  1. FreeCAD (freecadcmd)  render/_thumbs_fc.py : KiCad .step -> per-face meshes + the STEP's own face colours (work/thumbs/*.json)
  2. Blender 5.1 (Cycles, HIP GPU when RENDER_DEVICE=HIP)  render/_thumbs_bl.py : studio render, transparent bg + shadow catcher, 512 px
  3. Pillow: PNG -> WebP, and writes site/data/partthumbs.js (BOM line / footprint -> thumbnail rules)
Models: KiCad 3dmodels where the library has one (passives, SOT-23, WSON, QFN-56 as the RP2350 QFN-60 stand-in, USB-C (GCT 16P
as stand-in for the HRO TYPE-C-31-M-12), tact switch, 1.27 mm SMD header, 3225 crystal); parametric models otherwise (ECP5 BGA,
3225 oscillator, OV9281 CSP, CLA020 lens holder, M12 lens, M2 screw, M2 heat-set insert, filament spool, bare PCB with the real routed top
copper as texture).  A real model dropped in render/models/<key>.glb|obj|stl (keys: ov9281, holder, lens, ...) replaces the parametric one.
Fee rows (assembly setup / stencil / feeder / placement) use inline SVG icons drawn by assets/partthumbs.js."""
import os, sys, json, subprocess
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, 'work'); TH = os.path.join(WORK, 'thumbs'); PNG = os.path.join(WORK, 'tp')
OUTP = os.path.join(HERE, 'out', 'parts')          # persistent copy; site/build_site.py copies it to site/img/parts + site/data/partthumbs.js
SITE_IMG = os.path.join(ROOT, 'site', 'img', 'parts')
KICAD = 'C:/Program Files/KiCad/10.0/share/kicad/3dmodels'
FC = 'C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe'
BL = 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe'
argv = sys.argv[1:]
def opt(n, d): return argv[argv.index(n) + 1] if n in argv else d
SPP = opt('--spp', '96'); ONLY = opt('--only', 'all')

STEPS = {  # json key -> KiCad step (relative to 3dmodels)
    'c0402': 'Capacitor_SMD.3dshapes/C_0402_1005Metric.step', 'c0603': 'Capacitor_SMD.3dshapes/C_0603_1608Metric.step',
    'c0805': 'Capacitor_SMD.3dshapes/C_0805_2012Metric.step', 'r0402': 'Resistor_SMD.3dshapes/R_0402_1005Metric.step',
    'led0603': 'LED_SMD.3dshapes/LED_0603_1608Metric.step', 'l1008': 'Inductor_SMD.3dshapes/L_1008_2520Metric.step',
    'l0603': 'Inductor_SMD.3dshapes/L_0603_1608Metric.step', 'sot236': 'Package_TO_SOT_SMD.3dshapes/SOT-23-6.step',
    'sot235': 'Package_TO_SOT_SMD.3dshapes/SOT-23-5.step', 'wson8': 'Package_SON.3dshapes/WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm.step',
    'sw': 'Button_Switch_SMD.3dshapes/SW_SPST_PTS810.step', 'hdr': 'Connector_PinHeader_1.27mm.3dshapes/PinHeader_2x05_P1.27mm_Vertical_SMD.step',
    'xtal': 'Crystal.3dshapes/Crystal_SMD_3225-4Pin_3.2x2.5mm.step',
    'usbc': 'Connector_USB.3dshapes/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.step',
    'ecp5': '@Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm.step', 'qfn60': '@QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm.step',
    'osc': '@Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm.step', 'usbc_hro': '@USB_C_Receptacle_HRO_TYPE-C-31-M-12.step',
    'ov9281': '@OV9281_CSP.step', 'm12': '@M12_LENS_MOUNT.step',
    'qfn': 'Package_DFN_QFN.3dshapes/QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm.step',
}
# BOM-line rules: [field, regex (case-insens.), thumbnail key]; first match wins.  'fee-*' keys are SVG icons (no image file).
RULES = [
    ['mpn', '^LFE5U', 'ecp5'], ['mpn', '^RP2350', 'rp2350'], ['mpn', '^W25Q', 'flash'],
    ['mpn', '^TLV62569', 'tlv62569'], ['mpn', '^TLV75525', 'tlv75525'], ['mpn', '^TLV75518', 'tlv75518'],
    ['mpn', '^TLV75528', 'tlv75528'], ['mpn', '^ME6211C25', 'tlv75525'], ['mpn', '^ME6211C28', 'tlv75528'], ['mpn', '^TLV75512', 'tlv75512'], ['mpn', '^USBLC6', 'usblc6'],
    ['mpn', '^OV9281', 'ov9281'], ['mpn', '^CLA020', 'holder'], ['value', '^M12 lens(?! holder)', 'lens'],
    ['mpn', '^ABM8', 'xtal'], ['mpn', '^O9322', 'osc'], ['mpn', '^TYPE-C', 'usbc'], ['mpn', '^HX PZ1', 'hdr'],
    ['mpn', '^PTS810', 'sw'], ['mpn', '^KT-0603', 'led'], ['mpn', '^BLM18', 'l0603'], ['mpn', '^DFE252012', 'l1008'],
    ['mpn', '^CL05', 'c0402'], ['mpn', '^CL10', 'c0603'], ['mpn', '^CL21', 'c0805'], ['mpn', '^RC0402', 'r0402'],
    ['mpn', '^ZSCRW', 'screw'], ['mpn', '^SZTB', 'insert'], ['mpn', '^PolyLite', 'filament'],
    ['value', '^4-layer PCB', 'pcb'], ['value', 'PCBA setup', 'fee-setup'], ['value', 'stencil', 'fee-stencil'],
    ['value', 'Feeder loading', 'fee-feeder'], ['value', 'SMT placement', 'fee-place'],
]
# footprint (3D viewer) fallbacks when a ref has no BOM line
FP = [['^C_0402', 'c0402'], ['^C_0603', 'c0603'], ['^C_0805', 'c0805'], ['^R_0402', 'r0402'], ['^LED_0603', 'led'], ['^L_1008', 'l1008'],
      ['^L_0603', 'l0603'], ['^SOT-23-6', 'usblc6'], ['^SOT-23-5', 'tlv62569'], ['^WSON-8', 'flash'], ['^QFN-60', 'rp2350'],
      ['caBGA-381', 'ecp5'], ['^SW_SPST', 'sw'], ['^USB_C', 'usbc'], ['^PinHeader_2x05', 'hdr'], ['^Crystal_SMD', 'xtal'],
      ['^Oscillator', 'osc'], ['OV9281', 'ov9281'], ['M12_LENS_MOUNT', 'holder']]


def run(cmd, env=None):
    e = dict(os.environ); e.update(env or {})
    r = subprocess.run(cmd, env=e, capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    for ln in out.splitlines():
        if any(k in ln for k in ('FAIL', 'Traceback', 'Error:', 'OK ', 'RENDERED')): print('  ', ln.strip())
    return r.returncode


def main():
    os.makedirs(TH, exist_ok=True); os.makedirs(PNG, exist_ok=True); os.makedirs(SITE_IMG, exist_ok=True); os.makedirs(OUTP, exist_ok=True)
    if '--skip-fc' not in argv:
        print('1/3 FreeCAD: KiCad STEP -> coloured meshes')
        run([FC, os.path.join(HERE, '_thumbs_fc.py')], {'THUMB_OUT': TH.replace('\\', '/'), 'THUMB_JOBS': json.dumps({k: (os.path.join(HERE, 'models', v[1:]).replace(chr(92), '/') if v[0] == '@' else KICAD + '/' + v) for k, v in STEPS.items()})})
    print('2/3 Blender: studio renders (%s spp)' % SPP)
    env = {'RENDER_DEVICE': os.environ.get('RENDER_DEVICE', 'HIP')}
    run([BL, '-b', '-P', os.path.join(HERE, '_thumbs_bl.py'), '--', WORK, PNG, ONLY, '--spp', SPP, '--res', '512'], env)
    print('3/3 WebP + data/partthumbs.js')
    keys = []
    for f in sorted(os.listdir(PNG)):
        if not f.endswith('.png'): continue
        k = f[:-4]; im = Image.open(os.path.join(PNG, f)).convert('RGBA')
        for d in (OUTP, SITE_IMG): im.save(os.path.join(d, k + '.webp'), 'WEBP', quality=90, alpha_quality=95, method=6)
        keys.append(k)
    js = 'window.PARTTHUMBS=' + json.dumps({'dir': 'img/parts/', 'ext': '.webp', 'keys': keys, 'rules': RULES, 'fp': FP}, separators=(',', ':')) + ';'
    os.makedirs(os.path.join(ROOT, 'site', 'data'), exist_ok=True)
    for d in (os.path.join(HERE, 'out', 'partthumbs.js'), os.path.join(ROOT, 'site', 'data', 'partthumbs.js')): open(d, 'w', encoding='utf-8').write(js)
    print('done:', len(keys), 'thumbnails')


if __name__ == '__main__':
    main()
