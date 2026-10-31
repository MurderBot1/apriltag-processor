"""Full re-route of the board with the repository's grid router, seed sweep, picked by KiCad DRC.  Used for architecture A3 (10 new frame-bus nets).

   py -3.12 pcb/route_sweep.py build              # "KiCad python" build_pcb.py -> unrouted board from pcb/design.py, export the router problem
   py -3.12 pcb/route_sweep.py run 1 2 3 ...      # route with these seeds (3 at a time, 8 threads, 170 s each; IN2_PEN=2 W0=0.10 VIA_COST=9)
   py -3.12 pcb/route_sweep.py eval 1 2 3 ...     # import every complete solution, narrow the +1V1MCU stub on the MCU DVDD pad, run KiCad DRC, print a table
   py -3.12 pcb/route_sweep.py pick 128           # copy that candidate to pcb/output/apriltag_cam.kicad_pcb  (then: kicad python pcb/make_outputs.py)

Result for A3 (2026-10-31): of about 90 completed router runs (mostly IN2_PEN=2; IN2_PEN 4 and 8 were far worse) the best was seed 128 with 0 router violations; KiCad DRC 69 violations + 10 unconnected (baseline of the 85F board:
72 + 12), all 10 FB_* nets connected.  Other seeds with 0 router violations: 11 (73 + 15), 36 (75 + 23).  The 'unconnected' items are plane fan-out artefacts
of the same kind as in the baseline.  pcb/ripup_region.py + pcb/route_a3.py are an earlier incremental attempt (rip up only the nets crossing the MCU's
escape area) that routed 9 of the 10 nets."""
import os, sys, re, glob, json, shutil, subprocess, collections
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')
K = r'C:\Program Files\KiCad\10.0\bin\python.exe'
CLI = r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
ENV = dict(os.environ, IN2_PEN='2', W0='0.10', VIA_COST='9', PFMAX='6', HINC='1.5', POLISH='500')

NARROW = '''
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1]); n = 0
for t in b.GetTracks():
    if t.GetClass() == 'PCB_VIA' or t.GetNetname() != '+1V1MCU': continue
    s, e = t.GetStart(), t.GetEnd()
    xs = [pcbnew.ToMM(s.x) - 100, pcbnew.ToMM(e.x) - 100]; ys = [100 - pcbnew.ToMM(s.y), 100 - pcbnew.ToMM(e.y)]
    if min(xs) >= 14.1 and max(xs) <= 15.0 and min(ys) >= 9.7 and max(ys) <= 10.1:
        t.SetWidth(pcbnew.FromMM(0.2)); n += 1        # a 0.3 mm power stub on the 0.2 mm DVDD pad of the QFN breaks the clearance to the neighbouring pads
pcbnew.SaveBoard(sys.argv[2], b)
'''


def sol(sd): return os.path.join(OUT, f'full_sol_{sd}.txt')


def build():
    subprocess.run([K, os.path.join(HERE, 'build_pcb.py')], cwd=HERE)
    subprocess.run([K, os.path.join(HERE, 'router', 'export_problem.py'), os.path.join(OUT, 'apriltag_cam_unrouted.kicad_pcb'), os.path.join(OUT, 'full_problem.txt')])


def run(seeds):
    for i in range(0, len(seeds), 3):
        procs = []
        for sd in seeds[i:i + 3]:
            log = open(os.path.join(OUT, f'full_r{sd}.log'), 'w')
            procs.append(subprocess.Popen([os.path.join(HERE, 'router', 'router14.exe'), os.path.join(OUT, 'full_problem.txt'), sol(sd), '8', '170', '250'],
                                          env=dict(ENV, SEED=str(sd)), stdout=log, stderr=log))
        for p in procs: p.wait()


def evaluate(seeds):
    rows = []
    for sd in seeds:
        log = open(os.path.join(OUT, f'full_r{sd}.log')).read()
        m = re.search(r'unrouted jobs (\d+).*signals\) (\d+)', log)
        if not m or m.group(1) != '0':
            print(sd, 'unrouted jobs', m and m.group(1)); continue
        out = os.path.join(OUT, f'ev_{sd}.kicad_pcb')
        subprocess.run([K, os.path.join(HERE, 'router', 'import_solution.py'), os.path.join(OUT, 'apriltag_cam_unrouted.kicad_pcb'), sol(sd), out], capture_output=True)
        open(os.path.join(OUT, '_narrow.py'), 'w').write(NARROW)
        subprocess.run([K, os.path.join(OUT, '_narrow.py'), out, out], capture_output=True)
        shutil.copy(os.path.join(OUT, 'apriltag_cam_unrouted.kicad_pro'), os.path.join(OUT, f'ev_{sd}.kicad_pro'))
        subprocess.run([CLI, 'pcb', 'drc', '--output', os.path.join(OUT, f'ev_{sd}.json'), '--format', 'json', '--severity-all', '--units', 'mm', '--all-track-errors', out], capture_output=True)
        d = json.load(open(os.path.join(OUT, f'ev_{sd}.json')))
        c = collections.Counter(v['type'] for v in d['violations'])
        print(sd, 'router viol', m.group(2), 'DRC violations', len(d['violations']), 'unconnected', len(d.get('unconnected_items', [])), dict(c))


if __name__ == '__main__':
    cmd, seeds = sys.argv[1], [int(a) for a in sys.argv[2:]]
    if cmd == 'build': build()
    elif cmd == 'run': run(seeds)
    elif cmd == 'eval': evaluate(seeds)
    elif cmd == 'pick': shutil.copy(os.path.join(OUT, f'ev_{seeds[0]}.kicad_pcb'), os.path.join(OUT, 'apriltag_cam.kicad_pcb'))
