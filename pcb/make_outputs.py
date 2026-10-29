"""Fabrication/documentation outputs from pcb/output/apriltag_cam.kicad_pcb using kicad-cli:
DRC report, Gerbers + drill (zipped), pick-and-place, STEP model, board renders, netlist/BOM (via make_reports)."""
import os, sys, json, subprocess, zipfile, collections, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')
K = r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
PCB = os.path.join(OUT, 'apriltag_cam.kicad_pcb')


def run(*a):
    r = subprocess.run([K, *a], capture_output=True, text=True)
    print(' '.join(a[:3]), '->', (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else 'ok')
    return r


def main():
    # DRC
    run('pcb', 'drc', '--output', os.path.join(OUT, 'drc.json'), '--format', 'json', '--severity-all', '--units', 'mm',
        '--all-track-errors', PCB)
    d = json.load(open(os.path.join(OUT, 'drc.json')))
    c = collections.Counter(v['type'] for v in d['violations'])
    un = len(d.get('unconnected_items', []))
    summary = {'violations': dict(c), 'unconnected_items': un, 'total_violations': len(d['violations'])}
    json.dump(summary, open(os.path.join(OUT, 'drc_summary.json'), 'w'), indent=1)
    print('DRC summary', summary)
    # gerbers + drill
    g = os.path.join(OUT, 'gerbers'); shutil.rmtree(g, ignore_errors=True); os.makedirs(g)
    run('pcb', 'export', 'gerbers', '--output', g, '--layers',
        'F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts', PCB)
    run('pcb', 'export', 'drill', '--output', g + os.sep, '--format', 'excellon', PCB)
    with zipfile.ZipFile(os.path.join(OUT, 'apriltag_cam_gerbers.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(g)): z.write(os.path.join(g, f), f)
    run('pcb', 'export', 'pos', '--output', os.path.join(OUT, 'pick_and_place.csv'), '--format', 'csv', '--units', 'mm', PCB)
    run('pcb', 'export', 'step', '--output', os.path.join(OUT, 'apriltag_cam.step'), '--no-unspecified', '--drill-origin', PCB)
    for side in ('top', 'bottom'):
        run('pcb', 'render', '--side', side, '--width', '1600', '--height', '1600', '--output', os.path.join(OUT, f'board_{side}.png'), PCB)
    run('pcb', 'render', '--side', 'top', '--width', '1600', '--height', '1200', '--rotate', '-45,0,30',
        '--output', os.path.join(OUT, 'board_iso.png'), PCB)
    sys.path.insert(0, HERE)
    import make_reports; make_reports.main()


if __name__ == '__main__':
    main()
