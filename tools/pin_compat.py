"""Ball compatibility of the used FPGA pins between ECP5 devices in the same package (from the Project Trellis database, iodb.json):
for every ball of tools/pins.py print the bank and pad function per device and report any difference.

    py -3.12 tools/pin_compat.py [LFE5U-85F LFE5U-45F ...] [--package CABGA381]       (default: 85F vs 45F vs 25F, CABGA381)
Exit status 1 if a used ball differs in bank or function between the devices.  The balls come from the open database, not from a Lattice
drawing: check them against the datasheet pin table before ordering boards."""
import json, os, sys, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import pins


def trellis_dir():
    for d in (os.environ.get('TRELLIS_DB'), 'C:/msys64/ucrt64/share/trellis/database', '/usr/share/trellis/database', '/usr/local/share/trellis/database'):
        if d and os.path.isdir(os.path.join(d, 'ECP5')):
            return os.path.join(d, 'ECP5')
    raise SystemExit('Project Trellis database not found (set TRELLIS_DB)')


def table(dev, package):
    d = json.load(open(os.path.join(trellis_dir(), dev, 'iodb.json')))
    meta = {(m['row'], m['col'], m['pio']): m for m in d['pio_metadata']}
    out = {}
    for ball, loc in d['packages'][package].items():
        m = meta.get((loc['row'], loc['col'], loc['pio']))
        out[ball] = (m['bank'], m.get('function', '-')) if m else None
    return out


def main(argv):
    package = 'CABGA381'
    if '--package' in argv:
        i = argv.index('--package'); package = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    devs = argv or ['LFE5U-85F', 'LFE5U-45F', 'LFE5UM-45F', 'LFE5U-25F']
    tabs = {d: table(d, package) for d in devs}
    balls = {}
    for sig, (ball, std, extra) in pins.PINS.items():
        balls[ball] = sig
    for sig, ball in pins.DIFF_N.items():
        balls[ball] = sig + ' (N)'
    bad = 0
    print('ball  signal'.ljust(34) + '  '.join(d.ljust(24) for d in devs))
    for ball in sorted(balls, key=lambda b: (b[0], int(b[1:]))):
        cells = [tabs[d].get(ball) for d in devs]
        flag = '' if all(c == cells[0] for c in cells) else '   <-- DIFFERS'
        bad += bool(flag)
        print(f'{ball:5s} {balls[ball]:26s}' + '  '.join(f'bank {c[0]} {c[1]}'.ljust(24) if c else 'missing'.ljust(24) for c in cells) + flag)
    print(f'{len(balls)} balls checked on {", ".join(devs)}: {"all identical" if not bad else str(bad) + " differ"}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
