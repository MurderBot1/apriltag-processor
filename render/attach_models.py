"""Attach a real 3D model to every footprint of a COPY of the board (render/work/apriltag_cam.kicad_pcb -> apriltag_cam_models.kicad_pcb).
Run with KiCad python:  "C:/Program Files/KiCad/10.0/bin/python.exe" render/attach_models.py
Official-library models stay as they are; footprints whose library model does not exist in KiCad 10's 3dmodels (or that never had one)
get the parametric models from render/models (gen_models.py).  Mounting holes (4x MH, plain NPTH holes) are not parts."""
import os, pcbnew
R = 'D:/apriltag-proccessor/render'
LIB = 'C:/Program Files/KiCad/10.0/share/kicad/3dmodels'
b = pcbnew.LoadBoard(R + '/work/apriltag_cam.kicad_pcb')
OWN = {'Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm': 'Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm',
       'QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm': 'QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm',
       'Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm': 'Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm',
       'USB_C_Receptacle_HRO_TYPE-C-31-M-12': 'USB_C_Receptacle_HRO_TYPE-C-31-M-12',
       'OV9281_CSP': 'OV9281_CSP', 'M12_LENS_MOUNT': 'M12_LENS_MOUNT', 'TestPoint_Pad_D1.0mm': 'TestPoint_Pad_D1.0mm'}
src = {}
for f in b.GetFootprints():
    name = str(f.GetFPID().GetLibItemName())
    models = f.Models()
    cur = [m.m_Filename for m in models]
    if name in OWN:
        while len(models): models.pop_back()
        m = pcbnew.FP_3DMODEL(); m.m_Filename = R + '/models/' + OWN[name] + '.step'
        m.m_Scale = pcbnew.VECTOR3D(1, 1, 1); m.m_Offset = pcbnew.VECTOR3D(0, 0, 0); m.m_Rotation = pcbnew.VECTOR3D(0, 0, 0); m.m_Show = True
        models.push_back(m); src[f.GetReference()] = ('parametric', OWN[name])
    elif cur:
        p = cur[0].replace('${KICAD10_3DMODEL_DIR}', LIB)
        assert os.path.exists(p), (f.GetReference(), p)
        src[f.GetReference()] = ('official', cur[0].split('/')[-2] + '/' + cur[0].split('/')[-1])
    else:
        src[f.GetReference()] = ('none', name)
import json
json.dump(src, open(R + '/work/model_sources.json', 'w'), indent=1)
b.Save(R + '/work/apriltag_cam_models.kicad_pcb')
print(sum(1 for v in src.values() if v[0] == 'none'), 'without model:', [k for k, v in src.items() if v[0] == 'none'])
