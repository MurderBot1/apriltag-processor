#!/usr/bin/env python3
"""Compact VCD -> JSON converter for the site's waveform viewer (site/assets/sim.js).

    vcd_to_json(path, spec) -> dict   (see gen_sim.py for how specs are built)

Handles $dumpon/$dumpoff windows: time that was not dumped is removed from the time axis and recorded in
'breaks' ([t_compressed, skipped_ns]) so the viewer can draw a gap marker.  Only the top scope's variables are
used (testbenches expose the chosen signals there under friendly names).  Values: int, or -1 for x/z.
"""
import re, sys, json


def parse_vcd(path):
    scale_ps = 1
    ids = {}            # id -> list of var entries
    vars_ = []
    scope = []
    txt = open(path, 'r', errors='replace').read()
    p = txt.find('$enddefinitions')
    hdr, body = txt[:p], txt[p:]
    m = re.search(r'\$timescale\s+(\d+)\s*(\w+)', hdr)
    if m:
        scale_ps = int(m.group(1)) * {'s': 10**12, 'ms': 10**9, 'us': 10**6, 'ns': 1000, 'ps': 1, 'fs': 0.001}[m.group(2)]
    for m in re.finditer(r'\$scope\s+\w+\s+(\S+)\s+\$end|\$upscope\s+\$end|\$var\s+(\w+)\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]*\])?\s+\$end', hdr):
        if m.group(1): scope.append(m.group(1))
        elif m.group(2) is None: scope.pop()
        else:
            v = dict(type=m.group(2), w=int(m.group(3)), id=m.group(4), name=m.group(5), scope='.'.join(scope))
            vars_.append(v); ids.setdefault(v['id'], []).append(v)
    return scale_ps, vars_, ids, body


def to_int(s):
    return -1 if re.search(r'[xXzZ]', s) else int(s, 2)


def convert(path, signals, squeeze_gap_ns=200, break_ns=40, marks=None, ps_per_ns=1000):
    """signals: list of dicts {src: vcd name, name:, group:, fmt: 'h'|'d'|'b', names: {val: label}, w: optional}.
    Returns dict(tmax, breaks, signals=[{name,w,group,fmt,names,ch:[t,v,t,v..]}])"""
    scale_ps, vars_, ids, body = parse_vcd(path)
    by = {}
    for v in vars_:
        by.setdefault(v['name'], v)
    out = {}
    for s in signals:
        v = by.get(s['src'])
        if v is None:
            raise SystemExit('%s: signal %r not in VCD (have %s)' % (path, s['src'], sorted(by)[:60]))
        out[v['id']] = out.get(v['id'], []) + [dict(s, w=v['w'], ch=[])]
    t = 0.0           # absolute time in ns
    off = False
    skipped = 0.0     # ns removed so far
    breaks = []
    cur = {}          # id -> last value written
    tok = re.compile(r'#(\d+)|\$(dumpoff|dumpon|dumpvars|dumpall|end|comment)|([01xXzZ])(\S+)|[bB]([01xXzZ]+)\s+(\S+)|[rR](\S+)\s+(\S+)')
    first = True
    def tc():            # compressed time of the current absolute time
        return t - skipped
    for m in tok.finditer(body):
        if m.group(1) is not None:
            nt = int(m.group(1)) * scale_ps / ps_per_ns
            if first and nt > squeeze_gap_ns:
                skipped = nt                      # dump starts late (windowed): start the axis at 0
            elif nt - t > squeeze_gap_ns and not first:
                cut = nt - t - break_ns          # long quiet / not-dumped stretch: replaced by a short gap marker
                breaks.append([round(t - skipped, 3), round(cut, 1)])
                skipped += cut
            t = nt; first = False
        elif m.group(2):
            d = m.group(2)
            if d == 'dumpoff':
                off = True; off_t = t
            elif d == 'dumpon':
                off = False
        else:
            if m.group(3):
                vid, val = m.group(4), to_int(m.group(3))
            elif m.group(5):
                vid, val = m.group(6), to_int(m.group(5))
            else:
                continue
            if off or vid not in out:
                continue
            for s in out[vid]:
                ch = s['ch']
                if ch and ch[-1] == val and True:
                    continue
                if len(ch) >= 2 and ch[-2] == round(tc(), 3):
                    ch[-1] = val
                else:
                    ch += [round(tc(), 3), val]
    # dumpoff windows: time between dumpoff and dumpon is treated by the squeeze above only if the gap is long
    tmax = round(tc(), 3)
    res = []
    for lst in out.values():
        for s in lst:
            # drop consecutive duplicates introduced by dumpon re-dump
            ch = s['ch']; c2 = []
            for i in range(0, len(ch), 2):
                if c2 and c2[-1] == ch[i + 1]: continue
                c2 += [ch[i], ch[i + 1]]
            s['ch'] = c2
    ordered = []
    for s in signals:
        for lst in out.values():
            for q in lst:
                if q['name'] == s['name'] and q not in ordered: ordered.append(q)
    mk = []
    for mark in (marks or []):
        sig = next(q for q in ordered if q['name'] == mark['sig'])
        ch, prev, n = sig['ch'], None, 0
        for i in range(0, len(ch), 2):
            v = ch[i + 1]
            if v < 0:
                continue
            if prev is None:
                prev = v
                continue
            hit = (v > 0 and prev <= 0) if mark.get('edge', 'rise') == 'rise' else (v != prev)
            if hit and n < mark.get('max', 3):
                n += 1; mk.append([ch[i], mark['label'] % v if '%' in mark['label'] else mark['label']])
            prev = v
    return dict(tmax=tmax, breaks=breaks, signals=ordered, marks=sorted(mk))


if __name__ == '__main__':
    print('library; see gen_sim.py')
