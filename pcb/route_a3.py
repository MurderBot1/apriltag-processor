"""Architecture A3 board update, grid-router flow (no Freerouting): start from pcb/output/apriltag_cam.kicad_pcb as it is in git (routed, 4 layers),
assign the 10 new frame-bus nets, rip up the signal nets that pass through the MCU's left/bottom escape area, and re-route those nets together with the
new ones using pcb/router/router14.exe (negotiated-congestion grid router), keeping all other copper fixed.

   py -3.12 pcb/route_a3.py [--seeds 1 2 3 ...] [--region x0 x1 y0 y1]      (needs KiCad 10's python for pcbnew; uses the output dir pcb/output)
Result (2026-10-31): 9 of the 10 new nets route, the last (one MCU left-column pad) never does, with any seed / region / pin permutation tried; see docs/hardware.md.
The routed board is written to pcb/output/<tag>_routed.kicad_pcb and is NOT copied over pcb/output/apriltag_cam.kicad_pcb."""
import os, sys, subprocess, shutil, argparse, glob, re
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')
KPY = r'C:\Program Files\KiCad\10.0\bin\python.exe'
FB = [f'FB_D{i}' for i in range(8)] + ['FB_CLK', 'FB_FS']


def kpy(*a):
    r = subprocess.run([KPY, *a], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='*', default=list(range(1, 9)))
    ap.add_argument('--region', type=float, nargs=4, default=[10.5, 19.5, 3.0, 13.5])
    ap.add_argument('--tag', default='a3'); ap.add_argument('--time', type=int, default=150)
    a = ap.parse_args()
    t = a.tag
    base = os.path.join(OUT, f'{t}_base.kicad_pcb')
    if not os.path.exists(base):
        shutil.copy(os.path.join(OUT, 'apriltag_cam.kicad_pcb'), base)
    # nets onto the pads (design.py is the source of truth)
    print(kpy('apply_a3.py', '--assign-only', base, os.path.join(OUT, f'{t}_assigned.kicad_pcb')).splitlines()[-1:])
    rip = os.path.join(OUT, f'{t}_ripped.kicad_pcb')
    kpy('ripup_region.py', os.path.join(OUT, f'{t}_assigned.kicad_pcb'), rip, *map(str, a.region))
    prob = os.path.join(OUT, f'{t}_problem.txt')
    kpy('router/export_problem.py', rip, prob)
    nets = set(open(rip + '.nets').read().split()) | set(FB)
    lines = []
    for l in open(prob).read().splitlines():
        f = l.split()
        if f and f[0] == 'N' and f[3] in nets: l += '~fix'
        lines.append(l)
    open(prob, 'w').write('\n'.join(lines) + '\n')
    procs = []
    for sd in a.seeds:
        env = dict(os.environ, FIXONLY='1', IN2_PEN='2', W0='0.10', VIA_COST='9', SEED=str(sd), PFMAX='6', HINC='1.5', POLISH='500')
        log = open(os.path.join(OUT, f'{t}_r{sd}.log'), 'w')
        procs.append((sd, subprocess.Popen([os.path.join(HERE, 'router', 'router14.exe'), prob, os.path.join(OUT, f'{t}_sol_{sd}.txt'), '3', str(a.time), '250'], env=env, stdout=log, stderr=log)))
    best = None
    for sd, p in procs:
        p.wait()
        txt = open(os.path.join(OUT, f'{t}_r{sd}.log')).read()
        m = re.search(r'unrouted jobs (\d+) \(of (\d+)\).*violations \(signals\) (\d+)', txt)
        print('seed', sd, m.groups() if m else txt[-200:])
        if m and (best is None or (int(m.group(1)), int(m.group(3))) < best[0]): best = ((int(m.group(1)), int(m.group(3))), sd)
    print('best', best)
    if best:
        sd = best[1]
        print(kpy('router/import_solution.py', rip, os.path.join(OUT, f'{t}_sol_{sd}.txt'), os.path.join(OUT, f'{t}_routed.kicad_pcb')).splitlines()[-1:])
    return best


if __name__ == '__main__':
    main()
