"""Housing + PCB + lens full-assembly STEP: render/out/apriltag_housing_pcb_lens.step  (colours kept).
Housing STEPs (housing/output/housing_front.step / housing_back.step, read-only) get a black colour (copied to render/work), then are attached
to a dummy footprint on a COPY of the board (render/work/apriltag_cam_models.kicad_pcb) at the assembly offsets used by housing.scad
(PCB bottom at z=6.5 above the back-shell bottom, front cover on the split plane z=8.0); kicad-cli merges everything (KiCad puts model z=0 of a top-side footprint on the board top face, z=1.595 in its frame).
Run:  py -3.12 render/make_assembly.py   (needs render/work/apriltag_cam_models.kicad_pcb; calls KiCad python + kicad-cli)"""
import re, subprocess, os
R = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), '/'); H = os.path.dirname(R) + '/housing/output'
for n in ('housing_front', 'housing_back'):
    t = open('%s/%s.step' % (H, n), encoding='utf8', errors='replace').read()
    ids = [int(m.group(1)) for m in re.finditer(r'^#(\d+)\s*=\s*MANIFOLD_SOLID_BREP', t, re.M)]
    mx = max(int(m) for m in re.findall(r'^#(\d+)\s*=', t, re.M)); k = mx + 1
    out = ["#%d=COLOUR_RGB('',0.0150,0.0150,0.0170);\n#%d=FILL_AREA_STYLE_COLOUR('',#%d);\n#%d=FILL_AREA_STYLE('',(#%d));\n#%d=SURFACE_STYLE_FILL_AREA(#%d);\n#%d=SURFACE_SIDE_STYLE('',(#%d));\n#%d=SURFACE_STYLE_USAGE(.BOTH.,#%d);\n#%d=PRESENTATION_STYLE_ASSIGNMENT((#%d));" % (k, k+1, k, k+2, k+1, k+3, k+2, k+4, k+3, k+5, k+4, k+6, k+5)]
    pres = k + 6; k += 7
    for i in ids: out.append("#%d=STYLED_ITEM('color',(#%d),#%d);" % (k, pres, i)); k += 1
    j = t.rindex('ENDSEC;'); open('%s/work/%s_black.step' % (R, n), 'w', encoding='utf8').write(t[:j] + '\n'.join(out) + '\n' + t[j:])
code = r'''
import pcbnew
b = pcbnew.LoadBoard("%s/work/apriltag_cam_models.kicad_pcb")
f = pcbnew.FOOTPRINT(b); f.SetReference("ASM1"); f.SetValue("housing"); f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(100), pcbnew.FromMM(100))); b.Add(f)
for fn, dz in (("housing_back_black", -6.5 - 1.595), ("housing_front_black", 1.5 - 1.595)):
    m = pcbnew.FP_3DMODEL(); m.m_Filename = "%s/work/%%s.step" %% fn
    m.m_Scale = pcbnew.VECTOR3D(1, 1, 1); m.m_Offset = pcbnew.VECTOR3D(0, 0, dz); m.m_Rotation = pcbnew.VECTOR3D(0, 0, 0); m.m_Show = True
    f.Models().push_back(m)
b.Save("%s/work/apriltag_cam_assembly.kicad_pcb")
''' % (R, R, R)
open(R + '/work/_asm.py', 'w').write(code)
subprocess.run([r'C:\Program Files\KiCad\10.0\bin\python.exe', R + '/work/_asm.py'], check=True)
subprocess.run([r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe', 'pcb', 'export', 'step', '--force', '--drill-origin', '--output', R + '/out/apriltag_housing_pcb_lens.step', R + '/work/apriltag_cam_assembly.kicad_pcb'], check=True)
