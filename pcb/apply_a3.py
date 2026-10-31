"""Architecture A3 board update, step 1: take a routed board, add the 10 FPGA->RP2350 frame-bus nets (FB_D0..FB_D7, FB_CLK, FB_FS: FPGA bank-6 balls <->
RP2350 GPIO16..25, see pcb/design.py and tools/pins.py), put the new U1 value on the footprint and save.  Routing is done by pcb/route_a3.py.
   "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/apply_a3.py --assign-only in.kicad_pcb out.kicad_pcb"""
import os, sys
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design as D

NEW_NETS = [f'FB_D{i}' for i in range(8)] + ['FB_CLK', 'FB_FS']


def main(src, dst):
    b = pcbnew.LoadBoard(src)
    nets = b.GetNetsByName()
    for n in NEW_NETS:
        if not nets.has_key(n):
            b.Add(pcbnew.NETINFO_ITEM(b, n))
    nets = b.GetNetsByName()
    want = {p['ref']: p for p in D.parts if p['ref'] in ('U1', 'U2')}
    changed = 0
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        if ref not in want:
            continue
        if ref == 'U1':
            fp.SetValue(want['U1']['value'])
        for pad in fp.Pads():
            n = want[ref]['nets'].get(pad.GetNumber(), '')
            cur = pad.GetNetname()
            if (n in NEW_NETS and cur != n) or (cur in NEW_NETS and cur != n):
                pad.SetNet(nets[n] if n else nets['']); changed += 1
    pcbnew.SaveBoard(dst, b)
    print('pads (re)assigned:', changed)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--assign-only']
    main(args[0], args[1])
