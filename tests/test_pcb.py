"""Board-level checks on the netlist/placement data (pcb/design.py) - no KiCad needed - plus consistency between the
FPGA pin plan (tools/pins.py), the RTL top-level ports, the generated LPF and the PCB nets."""
import os, sys, re, json, collections
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pcb')); sys.path.insert(0, os.path.join(ROOT, 'tools'))
import design as D
import pins

NL = D.netlist()


def part(ref): return next(p for p in D.parts if p['ref'] == ref)


def test_no_duplicate_references_and_pads():
    refs = [p['ref'] for p in D.parts]
    assert len(refs) == len(set(refs))


def test_every_net_has_at_least_two_connections():
    singles = {n: v for n, v in NL.items() if len(v) < 2}
    assert not singles, singles


def test_fpga_power_pins_all_connected_to_the_right_rails():
    u1 = part('U1')['nets']
    pt = {b: n for b, n, t in json.load(open(os.path.join(ROOT, 'pcb', 'ecp5_85f_bg381_pins.json')))}
    names = {b: n for b, n, t in json.load(open(os.path.join(ROOT, 'pcb', 'ecp5_85f_bg381_pins.json')))}
    rail = {'GND': 'GND', 'VCC': '+1V1', 'VCCAUX': '+2V5'}
    for ball, name in names.items():
        if name in rail: assert u1.get(ball) == rail[name], (ball, name, u1.get(ball))
        if name.startswith('VCCIO'):
            assert u1.get(ball) == ('+1V8' if int(name[5:]) in (0, 1, 7) else '+3V3'), (ball, name)
    assert sum(1 for b, n in names.items() if n == 'GND') >= 100


def test_decoupling_budget_per_rail():
    caps = collections.Counter()
    for p in D.parts:
        if p['fp'].startswith('C_') and p['nets'].get('2') == 'GND': caps[p['nets']['1']] += 1
    assert caps['+1V1'] >= 12 and caps['+2V5'] >= 4 and caps['+1V8'] >= 5 and caps['+3V3'] >= 12, caps
    assert caps['AVDD_S'] >= 2 and caps['DVDD_S'] >= 2 and caps['DOVDD_S'] >= 2


def test_fpga_signal_balls_match_pin_plan_and_lpf():
    u1 = part('U1')['nets']
    for sig, (ball, std, extra) in pins.PINS.items():
        assert ball in u1 and u1[ball], sig
    lpf = pins.lpf()
    for sig, (ball, std, extra) in pins.PINS.items():
        assert f'LOCATE COMP "{sig}" SITE "{ball}";' in lpf
    for sig, n in pins.DIFF_N.items():
        assert u1[n].endswith('_N')


def test_every_rtl_top_port_has_a_pin():
    src = open(os.path.join(ROOT, 'rtl', 'apriltag_cam_top.v')).read()
    body = src[src.index('module apriltag_cam_top'):src.index(');')]
    ports = re.findall(r'(?:input|output|inout)\s+(?:wire|reg)?\s*(?:\[(\d+):0\])?\s*(\w+)', body)
    need = set()
    for hi, name in ports:
        if hi: need.update(f'{name}[{i}]' for i in range(int(hi) + 1))
        else: need.add(name)
    assert need == set(pins.PINS), (need ^ set(pins.PINS))


def test_pin_plan_uses_legal_balls_and_banks():
    io = {r[0]: r for r in json.load(open(os.path.join(ROOT, 'pcb', 'ecp5_85f_bg381_io.json')))}
    for sig, (ball, std, extra) in pins.PINS.items():
        assert ball in io, (sig, ball)
        bank = io[ball][1]
        want = {'LVCMOS18': (0, 1), 'LVDS': (7,)}.get(std, (2, 3))
        assert bank in want, (sig, ball, bank, std)
    # differential pairs: P and N balls share a tile (same row/col) and are PIO A/B
    for sig, nball in pins.DIFF_N.items():
        p = io[pins.PINS[sig][0]]; n = io[nball]
        assert (p[4], p[5]) == (n[4], n[5]) and {p[6], n[6]} in ({'A', 'B'}, {'C', 'D'}), sig
    # the clock lane must be on an edge-clock capable pad
    assert 'PCLKT' in io[pins.PINS['mipi_clk_p'][0]][2]
    # IDDRX2F gearing is only available on left/right banks (nextpnr-ecp5 enforces this)
    assert io[pins.PINS['mipi_clk_p'][0]][1] in (2, 3, 6, 7)


def test_mipi_pairs_connect_sensor_to_fpga():
    s = part('U10')['nets']
    for n in ('MIPI_CLK_P', 'MIPI_CLK_N', 'MIPI_D0_P', 'MIPI_D0_N', 'MIPI_D1_P', 'MIPI_D1_N'):
        refs = {r for r, _ in NL[n]}
        assert 'U1' in refs and 'U10' in refs, n
    assert any(n == 'XVCLK' for n in s.values()) and any(n == 'XSHUTDN' for n in s.values())


def test_usb_and_mcu_connectivity():
    assert {r for r, _ in NL['USB_DP_MCU']} == {'U2', next(p['ref'] for p in D.parts if p['value'] == '27R' and 'USB_DP' in p['nets'].values())}
    # CC pins have 5.1k pull-downs
    for cc in ('CC1', 'CC2'):
        assert any(p['value'] == '5k1' for p in D.parts if cc in p['nets'].values())
    # SPI to the FPGA and the configuration port are wired MCU <-> FPGA
    for n in ('SPI_SCK', 'SPI_CS', 'SPI_MOSI', 'SPI_MISO', 'FPGA_PROGRAMN', 'FPGA_INITN', 'FPGA_DONE', 'FPGA_CCLK',
              'FPGA_CFG_MOSI', 'FPGA_CFG_MISO', 'FPGA_CFG_CS', 'FPGA_IRQ', 'FPGA_RST'):
        refs = {r for r, _ in NL[n]}
        assert 'U1' in refs and 'U2' in refs, n
    # slave SPI configuration straps CFG[2:0] = 001
    assert any(p['nets'] == {'1': 'CFG0', '2': '+3V3'} for p in D.parts)
    assert any(p['nets'] == {'1': 'CFG1', '2': 'GND'} for p in D.parts) and any(p['nets'] == {'1': 'CFG2', '2': 'GND'} for p in D.parts)


def test_flash_wiring():
    f = part('U3')['nets']
    assert f['8'] == '+3V3' and f['4'] == 'GND' and f['9'] == 'GND'
    assert {f[k] for k in '1235 67'.replace(' ', '')} == {'QSPI_SS', 'QSPI_SD1', 'QSPI_SD2', 'QSPI_SD0', 'QSPI_SCLK', 'QSPI_SD3'}


def test_regulator_feedback_dividers_give_the_right_voltages():
    def vout(rtop, rbot, vfb=0.6):
        k = lambda s: float(s.replace('k', 'e3').replace('R', ''))
        # values like '82k5' mean 82.5k
        def val(s):
            m = re.fullmatch(r'(\d+)k(\d)?', s)
            return float(m.group(1)) * 1e3 + (float(m.group(2)) * 100 if m.group(2) else 0)
        return vfb * (1 + val(rtop) / val(rbot))
    assert abs(vout('453k', '100k') - 3.3) < 0.1
    assert abs(vout('82k5', '100k') - 1.1) < 0.05


def test_mechanical_contract():
    P = D.P
    mh = [(p['x'], p['y']) for p in D.parts if p['ref'].startswith('MH')]
    assert sorted(mh) == sorted(map(tuple, P['mounting_holes']['positions']))
    s = part('U10')
    assert (s['x'], s['y']) == tuple(P['sensor']['center']) and s['side'] == 'top'
    leds = {p['value']: (p['x'], p['y']) for p in D.parts if p['value'] in ('PWR', 'STAT')}
    for l in P['status_leds']: assert leds[l['name']] == tuple(l['pos'])
    # everything except the sensor, the lens holder, LEDs and mounting holes is on the bottom side
    for p in D.parts:
        if p['side'] == 'top': assert p['ref'] in ('U10', 'LH1') or p['value'] in ('PWR', 'STAT') or p['ref'].startswith('MH'), p['ref']
    # all parts inside the outline
    for p in D.parts:
        assert abs(p['x']) <= D.BW / 2 + 0.01 and abs(p['y']) <= D.BH / 2 + 0.01, p['ref']


def test_sensor_ball_map_has_unique_balls_and_all_supplies():
    b = D.SENSOR_BALLS
    assert len(b) == len(set(b))
    for n in ('AVDD_S', 'DVDD_S', 'DOVDD_S', 'EVDD_S', 'PVDD_S', 'VH', 'VN1', 'VN2', 'VN3'):
        assert n in b.values(), n
    assert sum(1 for v in b.values() if v == 'GND') == 3
