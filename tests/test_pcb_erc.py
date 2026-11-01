"""ERC-style sanity checks of the board netlist (pcb/design.py) and a consistency check of the JLCPCB fabrication package
(pcb/output: gerbers + drill + pick-and-place + BOM) against the netlist, the KiCad board and docs/bom/bom.json.
No KiCad needed: the outputs are plain text / CSV / zip files."""
import os, sys, re, csv, json, math, zipfile, collections
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pcb')); sys.path.insert(0, os.path.join(ROOT, 'tools'))
import design as D

NL = D.netlist()
OUT = os.path.join(ROOT, 'pcb', 'output')
PARTS = {p['ref']: p for p in D.parts}
ACTIVE = ('U', 'J', 'Y', 'SW', 'D')          # reference prefixes that can source / sink a signal (not R/C/L/FB/TP)


def pin_tab(name): return json.load(open(os.path.join(ROOT, 'pcb', name)))


def prefix(ref): return ref.rstrip('0123456789')


# ------------------------------------------------------------------------------------------------ power pins
def test_every_fpga_power_and_ground_ball_is_connected_to_a_rail():
    u1 = PARTS['U1']['nets']
    for ball, name, typ in pin_tab('ecp5_85f_bg381_pins.json'):
        if name in ('GND', 'VCC', 'VCCAUX') or name.startswith('VCCIO'):
            assert u1.get(ball), f'U1 ball {ball} ({name}) has no net'
    # no power ball is on a signal net and no signal ball is on a rail by mistake
    rails = {'GND', '+1V1', '+2V5', '+1V8', '+3V3'}
    names = {b: n for b, n, t in pin_tab('ecp5_85f_bg381_pins.json')}
    for ball, net in u1.items():
        if net in rails: assert names.get(ball) in ('GND', 'VCC', 'VCCAUX') or names.get(ball, '').startswith('VCCIO'), (ball, net)


def test_every_mcu_power_and_ground_pad_is_connected():
    u2 = PARTS['U2']['nets']
    power_names = ('IOVDD', 'DVDD', 'ADC_AVDD', 'VREG_AVDD', 'VREG_VIN', 'VREG_FB', 'VREG_LX', 'VREG_PGND', 'USB_OTP_VDD', 'QSPI_IOVDD', 'GND')
    want = {'IOVDD': '+3V3', 'DVDD': '+1V1MCU', 'VREG_VIN': '+3V3', 'USB_OTP_VDD': '+3V3', 'QSPI_IOVDD': '+3V3', 'GND': 'GND', 'VREG_FB': '+1V1MCU',
            'VREG_PGND': 'GND', 'VREG_LX': 'VREG_LX', 'ADC_AVDD': 'ADC_AVDD', 'VREG_AVDD': 'VREG_AVDD'}
    seen = collections.Counter()
    for num, name, typ in pin_tab('rp2350a_pins.json'):
        if name in power_names:
            assert u2.get(num) == want[name], f'U2 pad {num} ({name}): net {u2.get(num)!r}, want {want[name]!r}'
            seen[name] += 1
    assert seen['IOVDD'] == 6 and seen['DVDD'] == 3, seen      # RP2350A: 6 IOVDD pads, 3 DVDD pads (pad 11 and pad 20 are IOVDD)


def test_all_other_ic_supply_pins_are_connected():
    """LDO / buck / flash / ESD / oscillator: IN, EN, GND and VCC pins sit on a net; only NC pins may be empty."""
    allowed_empty = {'U6': {'4'}, 'U7': {'4'}, 'U8': {'4'}, 'U9': {'4'}}
    for r in ('U3', 'U4', 'U5', 'U6', 'U7', 'U8', 'U9', 'U11'):
        for pad, net in PARTS[r]['nets'].items():
            assert net or pad in allowed_empty.get(r, set()), f'{r} pad {pad} is floating'
    for r in ('U6', 'U7', 'U8', 'U9'):        # SOT-23-5 LDO: 1 IN, 2 GND, 3 EN (tied to IN), 5 OUT
        n = PARTS[r]['nets']
        assert n['1'] == '+3V3' and n['3'] == '+3V3' and n['2'] == 'GND' and n['5'] != '+3V3', r
    for r in ('Y1', 'Y2'):
        assert PARTS[r]['nets'].get('2') == 'GND'
    for ref in ('U4', 'U5'):
        n = PARTS[ref]['nets']
        assert n['1'] == '+5V' and n['4'] == '+5V' and n['2'] == 'GND' and n['3'] and n['5'], ref     # TLV62569: EN=1 and VIN=4 on +5V, SW=3, FB=5
    # unused sensor balls are listed explicitly as unconnected, never half-wired
    s = PARTS['U10']['nets']
    assert sum(1 for v in s.values() if not v) <= 14


def test_ground_return_exists_for_every_supply_net():
    """each rail net that feeds an IC has a GND connection on some ground pin of the same board (cap or IC)."""
    rails = {n for n in NL if n.startswith('+') or n in ('VBUS', 'AVDD_S', 'DVDD_S', 'DOVDD_S', 'PVDD_S', 'EVDD_S', 'VH', 'VN1', 'VN2', 'VN3', 'ADC_AVDD', 'VREG_AVDD')}
    for n in rails:
        caps = [p for p in D.parts if prefix(p['ref']) == 'C' and n in p['nets'].values()]
        assert caps or n in ('VBUS',), f'rail {n} has no capacitor'


# ------------------------------------------------------------------------------------------------ decoupling
def _dist(a, b): return math.hypot(a['x'] - b['x'], a['y'] - b['y'])


# (rail, max distance from the part centre to a capacitor on that rail to GND, mm, minimum number of caps)
DECOUPLE = {
    'U1': [('+1V1', 16, 8), ('+2V5', 16, 2), ('+1V8', 16, 3), ('+3V3', 16, 4)],
    'U2': [('+3V3', 9, 4), ('+1V1MCU', 9, 2), ('ADC_AVDD', 9, 1), ('VREG_AVDD', 9, 1)],
    'U3': [('+3V3', 6, 1)],
    'U10': [('AVDD_S', 12, 2), ('DVDD_S', 12, 2), ('DOVDD_S', 12, 2), ('PVDD_S', 12, 1), ('EVDD_S', 12, 1), ('VH', 12, 1), ('VN1', 12, 1), ('VN2', 12, 1), ('VN3', 12, 1)],
}
for r in ('U4', 'U5'): DECOUPLE[r] = [('+5V', 6, 1)]
for r in ('U6', 'U7', 'U8', 'U9'): DECOUPLE[r] = [('+3V3', 5, 1), (PARTS[r]['nets']['5'], 5, 1)]


@pytest.mark.parametrize('ref', sorted(DECOUPLE))
def test_decoupling_present_near_every_ic_rail(ref):
    ic = PARTS[ref]
    for rail, dmax, nmin in DECOUPLE[ref]:
        assert rail in ic['nets'].values(), f'{ref} is not on rail {rail}'
        caps = [p for p in D.parts if prefix(p['ref']) == 'C' and p['nets'].get('1') == rail and p['nets'].get('2') == 'GND' and _dist(p, ic) <= dmax]
        assert len(caps) >= nmin, f'{ref}: only {len(caps)} cap(s) within {dmax} mm on {rail}, need {nmin}'


def test_buck_converters_have_output_capacitance():
    for ref, rail in (('U4', '+3V3'), ('U5', '+1V1')):
        big = [p for p in D.parts if prefix(p['ref']) == 'C' and p['value'] == '22u' and p['nets'].get('1') == rail]
        assert len(big) >= 1, (ref, rail)


# ------------------------------------------------------------------------------------------------ floating nets
def test_no_floating_or_source_less_nets():
    for n, pins in NL.items():
        refs = {r for r, _ in pins}
        assert len(pins) >= 2, f'net {n} has a single pin {pins}'
        assert any(prefix(r) in ACTIVE for r in refs), f'net {n} only touches passives {sorted(refs)}'


def test_no_pad_is_listed_twice_and_no_unknown_net_on_pads():
    for p in D.parts:
        assert all(isinstance(k, str) for k in p['nets'])
    # every signal net with a test point also reaches a real part
    for p in D.parts:
        if prefix(p['ref']) == 'TP':
            assert len(NL[p['nets']['1']]) >= 2, p['ref']


def test_ldo_substitutes_match_the_original_pinout_and_current():
    """U6/U8: TLV75525/TLV75528 (out of stock) replaced by ME6211C25 / ME6211C28, SOT-23-5, same pins (1 VIN, 2 GND, 3 CE, 4 NC, 5 VOUT)."""
    assert PARTS['U6']['value'] == 'ME6211C25' and PARTS['U8']['value'] == 'ME6211C28'
    for r in ('U6', 'U8'):
        assert PARTS[r]['fp'] == 'SOT-23-5'
        assert PARTS[r]['nets'] == {'1': '+3V3', '2': 'GND', '3': '+3V3', '4': '', '5': PARTS[r]['nets']['5']}


def test_crystal_load_capacitance_matches_the_crystal():
    """Y1 ABM8-272-T3 is a 10 pF crystal.  CL = C15*C16/(C15+C16) + Cstray with ~3 pF stray must be within 1 pF of 10 pF."""
    y = PARTS['Y1']
    assert '10pF' in y['value']
    caps = [p for p in D.parts if prefix(p['ref']) == 'C' and (p['nets'].get('1') in ('XIN', 'XOUT')) and p['nets'].get('2') == 'GND']
    assert len(caps) == 2 and {p['nets']['1'] for p in caps} == {'XIN', 'XOUT'}
    vals = [float(p['value'].replace('p', '')) for p in caps]
    cl = vals[0] * vals[1] / (vals[0] + vals[1]) + 3.0
    assert abs(cl - 10.0) <= 1.0, cl


def test_flash_label_matches_the_wson_footprint():
    f = PARTS['U3']
    assert f['fp'].startswith('WSON-8') and f['value'] == 'W25Q128JVPIQ'      # JVSIQ would be the SOIC-8 208 mil package


# ------------------------------------------------------------------------------------------------ fabrication package
def _have_outputs():
    return all(os.path.exists(os.path.join(OUT, f)) for f in ('apriltag_cam.kicad_pcb', 'apriltag_cam_gerbers.zip', 'pick_and_place.csv', 'bom.csv'))


needs_out = pytest.mark.skipif(not _have_outputs(), reason='pcb/output not generated')

LAYERS = ['F_Cu.gtl', 'In1_Cu.g1', 'In2_Cu.g2', 'B_Cu.gbl', 'F_Mask.gts', 'B_Mask.gbs', 'F_Paste.gtp', 'B_Paste.gbp', 'F_Silkscreen.gto', 'B_Silkscreen.gbo',
          'Edge_Cuts.gm1']


def _pcb_text(): return open(os.path.join(OUT, 'apriltag_cam.kicad_pcb'), encoding='utf-8').read()


@needs_out
def test_gerber_zip_has_all_layers_and_drill_and_matches_the_folder():
    z = zipfile.ZipFile(os.path.join(OUT, 'apriltag_cam_gerbers.zip'))
    names = set(z.namelist())
    for l in LAYERS: assert f'apriltag_cam-{l}' in names, l
    assert 'apriltag_cam.drl' in names
    for n in names:
        data = z.read(n)
        assert len(data) > 200, n
        norm = lambda b: b.replace(b'
', b'
')        # git may normalise line endings of the text files on checkout
        assert norm(data) == norm(open(os.path.join(OUT, 'gerbers', n), 'rb').read()), f'{n}: zip differs from gerbers/'
    for n in names:
        if n.endswith(('.gtl', '.gbl', '.g1', '.g2', '.gm1')):
            assert z.read(n).rstrip().endswith(b'M02*'), n


@needs_out
def test_gerbers_are_newer_than_nothing_but_describe_this_board():
    """the .gbrjob board size equals the outline in pcb_params.json, 4 copper layers."""
    job = json.load(open(os.path.join(OUT, 'gerbers', 'apriltag_cam-job.gbrjob')))
    assert job['GeneralSpecs']['LayerNumber'] == 4
    assert abs(job['GeneralSpecs']['Size']['X'] - D.BW) < 0.3 and abs(job['GeneralSpecs']['Size']['Y'] - D.BH) < 0.3


@needs_out
def test_drill_file_matches_vias_and_respects_jlcpcb_minimums():
    txt = open(os.path.join(OUT, 'gerbers', 'apriltag_cam.drl'), encoding='utf-8').read()
    tools, cur, hits, via_tools = {}, None, collections.Counter(), set()
    pending_via = False
    for line in txt.splitlines():
        if line.startswith('; #@! TA.AperFunction'): pending_via = 'ViaDrill' in line
        m = re.match(r'T(\d+)C([\d.]+)$', line)
        if m:
            tools[int(m.group(1))] = float(m.group(2))
            if pending_via: via_tools.add(int(m.group(1)))
            continue
        m = re.match(r'T(\d+)$', line)
        if m: cur = int(m.group(1)); continue
        if line.startswith('X') and cur is not None: hits[cur] += 1
    assert tools and min(tools.values()) >= 0.2, tools           # JLCPCB 4-layer: 0.2 mm finished via is the standard process
    n_via = len(re.findall(r'^\t\(via\b', _pcb_text(), re.M))
    assert n_via > 0 and sum(hits[t] for t in via_tools) == n_via, (n_via, {t: hits[t] for t in via_tools})


@needs_out
def test_pick_and_place_bom_csv_netlist_and_kicad_board_agree():
    pnp = list(csv.DictReader(open(os.path.join(OUT, 'pick_and_place.csv'), encoding='utf-8')))
    pnp_refs = [r['Ref'] for r in pnp]
    assert len(pnp_refs) == len(set(pnp_refs))
    board_refs = re.findall(r'\(property "Reference" "([^"]+)"', _pcb_text())
    assert sorted(board_refs) == sorted(PARTS), 'KiCad board and design.py reference sets differ'
    assert set(PARTS) - set(pnp_refs) <= {r for r in PARTS if r.startswith(('MH', 'TP'))}, 'parts missing from the pick-and-place file'
    assert set(pnp_refs) <= set(PARTS)
    bom = list(csv.DictReader(open(os.path.join(OUT, 'bom.csv'), encoding='utf-8')))
    bom_refs = [r for row in bom for r in row['References'].split()]
    assert len(bom_refs) == len(set(bom_refs))
    # parts that are deliberately not assembled from the BOM: sensor, lens holder, mounting holes, test points
    skipped = set(pnp_refs) - set(bom_refs)
    assert all(r in ('U10', 'LH1') or r.startswith(('MH', 'TP')) for r in skipped), skipped
    by_ref = {r: row for row in bom for r in row['References'].split()}
    for r in pnp:
        if r['Ref'] in by_ref:
            assert r['Val'] == by_ref[r['Ref']]['Value'] and r['Package'] == by_ref[r['Ref']]['Footprint'], r['Ref']
        assert r['Side'] == PARTS[r['Ref']]['side'], f"{r['Ref']} side"
        assert r['Val'] == PARTS[r['Ref']]['value'], r['Ref']
    # bom.csv is exactly what design.py produces
    want = {(len(refs), val, fp) for (val, fp), refs in D.bom().items()}
    assert {(int(r['Qty']), r['Value'], r['Footprint']) for r in bom} == want
    # placement is on the board
    for r in pnp:
        assert abs(float(r['PosX']) - 100) <= D.BW / 2 + 0.5 and abs(float(r['PosY']) + 100) <= D.BH / 2 + 0.5, r['Ref']


def _expand(text):
    """'C1-C9 C13' -> C1..C9, C13 (bom.json designator syntax); '-' and free text give nothing."""
    out = []
    for tok in text.split():
        m = re.fullmatch(r'([A-Z]+)(\d+)-([A-Z]+)(\d+)', tok)
        if m and m.group(1) == m.group(3): out += [f'{m.group(1)}{i}' for i in range(int(m.group(2)), int(m.group(4)) + 1)]
        elif re.fullmatch(r'[A-Z]+\d+', tok): out.append(tok)
    return out


@needs_out
def test_bom_json_designators_match_bom_csv_and_mpn_matches_design_value():
    bom = list(csv.DictReader(open(os.path.join(OUT, 'bom.csv'), encoding='utf-8')))
    csv_refs = {r for row in bom for r in row['References'].split()}
    items = json.load(open(os.path.join(ROOT, 'docs', 'bom', 'bom.json')))['items']
    json_refs = collections.Counter()
    for it in items:
        for tok in _expand(it['designators']): json_refs[tok] += 1
    # the sensor is quote-only and listed; everything else on the PCB must be in bom.json exactly once
    assert set(json_refs) - csv_refs <= {'U10', 'LH1'}, set(json_refs) - csv_refs
    assert csv_refs - set(json_refs) == set(), csv_refs - set(json_refs)
    assert all(v == 1 for v in json_refs.values()), [k for k, v in json_refs.items() if v > 1]
    mpn = {tok: it['mpn'] for it in items for tok in _expand(it['designators'])}
    for r in ('U1', 'U3', 'U6', 'U7', 'U8', 'U9', 'U4', 'U5', 'U2', 'U11'):
        v = PARTS[r]['value']
        assert mpn[r].upper().startswith(v.upper()), f'{r}: design value {v} vs BOM MPN {mpn[r]}'
    assert mpn['U3'].startswith('W25Q128JVPIQ') and mpn['U6'] == 'ME6211C25M5G-N' and mpn['U8'] == 'ME6211C28M5G-N'
    assert mpn['Y1'] == 'ABM8-272-T3'


@needs_out
def test_drc_has_no_unconnected_items_and_no_clearance_class_errors():
    """pcb/output/drc_summary.json is written by pcb/make_outputs.py (KiCad DRC).  Only silk / dangling-via / library warnings may remain."""
    s = json.load(open(os.path.join(OUT, 'drc_summary.json')))
    assert s['unconnected_items'] == 0, s
    allowed = {'silk_over_copper', 'silk_overlap', 'via_dangling', 'lib_footprint_issues'}
    assert set(s['violations']) <= allowed, s


@needs_out
def test_lens_holder_screw_holes_are_1p9_mm():
    """M1.6 holder screws: a 1.9 mm hole lets the head bear on the FR4 (2.6 mm let it pass through)."""
    txt = _pcb_text()
    i = txt.index('M12_LENS_MOUNT')
    holes = re.findall(r'\(pad "" np_thru_hole circle.*?\(drill ([\d.]+)\)', txt[i:i + 4000], re.S)
    assert len(holes) == 2 and all(abs(float(h) - 1.9) < 1e-6 for h in holes), holes
