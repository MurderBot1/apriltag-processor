"""Generate pcb/output/netlist.txt, bom.csv and placement.csv from pcb/design.py (no KiCad needed)."""
import os, csv, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import design as D

OUT = os.path.join(HERE, 'output'); os.makedirs(OUT, exist_ok=True)


def main():
    nl = D.netlist()
    with open(os.path.join(OUT, 'netlist.txt'), 'w') as f:
        for net in sorted(nl):
            f.write(f'{net}: ' + ' '.join(f'{r}.{p}' for r, p in sorted(nl[net])) + '\n')
    with open(os.path.join(OUT, 'bom.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Qty', 'Value', 'Footprint', 'References'])
        for (val, fp), refs in sorted(D.bom().items(), key=lambda kv: kv[1][0]):
            w.writerow([len(refs), val, fp, ' '.join(sorted(refs, key=lambda r: (r.rstrip('0123456789'), int(r.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ') or 0))))])
    with open(os.path.join(OUT, 'placement.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Ref', 'Value', 'Footprint', 'X_mm', 'Y_mm', 'Rot', 'Side', 'Note'])
        for p in D.parts:
            w.writerow([p['ref'], p['value'], p['fp'], p['x'], p['y'], p['rot'], p['side'], p['note']])
    print('parts', len(D.parts), 'nets', len(nl))


if __name__ == '__main__':
    main()
