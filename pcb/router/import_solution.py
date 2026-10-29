"""Apply router.cpp output (T/V lines, mm in pcbnew coordinates) to a board, fill zones, save.
usage: kicad-python import_solution.py <in.kicad_pcb> <solution.txt> <out.kicad_pcb>"""
import sys, pcbnew
mm = pcbnew.FromMM


def main(src, sol, dst):
    b = pcbnew.LoadBoard(src)
    nt = nv = 0
    for ln in open(sol):
        f = ln.split()
        if not f: continue
        if f[0] == 'T':
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I(mm(float(f[3])), mm(float(f[4])))); t.SetEnd(pcbnew.VECTOR2I(mm(float(f[5])), mm(float(f[6]))))
            t.SetWidth(mm(float(f[7]))); t.SetLayer({'0': pcbnew.F_Cu, '1': pcbnew.B_Cu, '2': pcbnew.In2_Cu}[f[2]])
            net = b.FindNet(f[1].split('~')[0]); t.SetNet(net) if net else None
            b.Add(t); nt += 1
        elif f[0] == 'V':
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(mm(float(f[2])), mm(float(f[3]))))
            v.SetWidth(mm(0.45)); v.SetDrill(mm(0.20)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
            net = b.FindNet(f[1].split('~')[0]); v.SetNet(net) if net else None
            b.Add(v); nv += 1
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(dst, b)
    print('imported tracks', nt, 'vias', nv)


if __name__ == '__main__':
    main(*sys.argv[1:4])
