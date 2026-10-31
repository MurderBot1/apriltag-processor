"""Remove the routed copper (not locked fan-out) of every signal net that passes through a rectangle, so the grid router can re-route it together with new nets.
usage: kicad-python ripup_region.py in.kicad_pcb out.kicad_pcb x0 x1 y0 y1   (mm, board-centre coordinates, +Y up); prints the nets, writes <out>.nets"""
import sys, pcbnew
SKIP = ('GND', '+3V3', '+1V1', '+1V8', '+2V5', '+1V2', '+1V1MCU', '+2V8', '+5V', 'VBUS', 'SW1V1', 'SW3V3', 'VREG_LX', '')
b = pcbnew.LoadBoard(sys.argv[1]); x0, x1, y0, y1 = [float(v) for v in sys.argv[3:7]]
f = lambda p: (pcbnew.ToMM(p.x) - 100, 100 - pcbnew.ToMM(p.y))
def inside(p):
    x, y = f(p); return x0 < x < x1 and y0 < y < y1
nets = set()
for t in b.GetTracks():
    if t.IsLocked() or t.GetNetname() in SKIP or t.GetNetname().startswith('FB_'): continue
    if t.GetClass() == 'PCB_VIA':
        if inside(t.GetPosition()): nets.add(t.GetNetname())
    elif inside(t.GetStart()) or inside(t.GetEnd()): nets.add(t.GetNetname())
n = 0
for t in list(b.GetTracks()):
    if t.GetNetname() in nets and not t.IsLocked() and not t.GetNetname().startswith('FB_'):
        b.Remove(t); n += 1
pcbnew.SaveBoard(sys.argv[2], b)
open(sys.argv[2] + '.nets', 'w').write('\n'.join(sorted(nets)))
print('ripped', n, 'items of', len(nets), 'nets:', sorted(nets))
