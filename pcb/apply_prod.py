"""Production-readiness update of the routed board without a full re-route: put the value labels of pcb/design.py on the footprints
(flash W25Q128JVPIQ, LDOs ME6211C25 / ME6211C28, crystal 12MHz 10pF), set the lens-holder screw holes to LENS_SCREW_HOLE (1.9 mm, M1.6 screws)
and refill the zones.
   "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/apply_prod.py in.kicad_pcb out.kicad_pcb"""
import os, sys
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design as D

LENS_SCREW_HOLE = 1.9       # keep equal to build_pcb.LENS_SCREW_HOLE (build_pcb imports pcbnew and builds the whole board, so it is not imported here)


def main(src, dst):
    b = pcbnew.LoadBoard(src)
    want = {p['ref']: p for p in D.parts}
    n_val = n_hole = 0
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        if ref in want and fp.GetValue() != want[ref]['value']:
            print(' ', ref, fp.GetValue(), '->', want[ref]['value']); fp.SetValue(want[ref]['value']); n_val += 1
        if ref == 'LH1':
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    d = pcbnew.FromMM(LENS_SCREW_HOLE)
                    pad.SetSize(pcbnew.VECTOR2I(d, d)); pad.SetDrillSize(pcbnew.VECTOR2I(d, d)); n_hole += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(dst, b)
    print('values changed:', n_val, ' screw holes set:', n_hole)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
