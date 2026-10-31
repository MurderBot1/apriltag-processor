"""Architecture A3 board update: take the routed board (pcb/output/apriltag_cam.kicad_pcb), add the 10 FPGA->RP2350 frame-bus nets
(FB_D0..FB_D7, FB_CLK, FB_FS: FPGA bank-2 balls <-> RP2350 GPIO16..25, see pcb/design.py), rename U1 to the LFE5U-45F and route ONLY the new
nets with Freerouting, keeping every existing track and via fixed.   Run with KiCad's python:
   "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/apply_a3.py [--route]
Then:  "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/make_outputs.py"""
import os, sys, subprocess, shutil
import pcbnew
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design as D

OUT = os.path.join(HERE, 'output')
PCB = os.path.join(OUT, 'apriltag_cam.kicad_pcb')
NEW_NETS = [f'FB_D{i}' for i in range(8)] + ['FB_CLK', 'FB_FS']


def main():
    b = pcbnew.LoadBoard(PCB)
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
            if n in NEW_NETS and pad.GetNetname() != n:
                pad.SetNet(nets[n]); changed += 1
    print('pads assigned to new nets:', changed)
    for t in b.GetTracks():
        t.SetLocked(True)
    pcbnew.SaveBoard(os.path.join(OUT, 'apriltag_cam_a3_in.kicad_pcb'), b)
    if '--route' in sys.argv:
        dsn = os.path.join(OUT, 'apriltag_cam_a3.dsn'); ses = os.path.join(OUT, 'apriltag_cam_a3.ses')
        if os.path.exists(ses): os.remove(ses)
        print('DSN export', pcbnew.ExportSpecctraDSN(b, dsn))
        java = r'C:\Program Files\Java\jdk-25\bin\java.exe'
        cmd = [java, '-jar', os.path.join(HERE, 'tools', 'freerouting-2.1.0.jar'), '-de', dsn, '-do', ses, '-mp', '40', '--gui.enabled=false']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get('ROUTE_TIMEOUT', 1800)))
        open(os.path.join(OUT, 'freerouting_a3.log'), 'w').write(r.stdout + r.stderr)
        print(r.stdout[-600:])
        if os.path.exists(ses):
            print('SES import', pcbnew.ImportSpecctraSES(b, ses))
    for t in b.GetTracks():
        t.SetLocked(False)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(PCB, b)
    print('saved', PCB)


if __name__ == '__main__':
    main()
