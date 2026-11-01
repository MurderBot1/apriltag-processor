"""Netlist + placement for the AprilTag camera board (pure Python, no KiCad needed to import).

Coordinates are in mm, board centre = (0,0), +X right, +Y up as seen from the LENS (top) side.
Every part is a dict: ref, lib (KiCad .pretty), fp (footprint name), value, x, y, rot (deg, ccw seen from top), side
('top'/'bottom'), nets {pad: net}.  Parts with many pins (FPGA, MCU, sensor) get their nets from pin tables."""
import json, os, sys, collections, math
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import pins as fpga_pins

P = json.load(open(os.path.join(HERE, 'pcb_params.json')))
BW, BH = P['board']['width'], P['board']['height']
FPGA_POS = (0.0, -8.0)
SENSOR_POS = tuple(P['sensor']['center'])

parts = []
_counters = collections.Counter()


def ref(prefix):
    _counters[prefix] += 1
    return f'{prefix}{_counters[prefix]}'


def add(prefix, lib, fp, value, x, y, rot=0, side='bottom', nets=None, ref_=None, dnp=False, note=''):
    r = ref_ or ref(prefix)
    parts.append(dict(ref=r, lib=lib, fp=fp, value=value, x=x, y=y, rot=rot, side=side, nets=nets or {}, dnp=dnp, note=note))
    return r


C0402 = ('Capacitor_SMD', 'C_0402_1005Metric')
C0603 = ('Capacitor_SMD', 'C_0603_1608Metric')
C0805 = ('Capacitor_SMD', 'C_0805_2012Metric')
R0402 = ('Resistor_SMD', 'R_0402_1005Metric')


def cap(value, net, x, y, rot=0, size=C0402, other='GND', side='bottom'):
    return add('C', size[0], size[1], value, x, y, rot, side, {'1': net, '2': other})


def res(value, n1, n2, x, y, rot=0, side='bottom'):
    return add('R', R0402[0], R0402[1], value, x, y, rot, side, {'1': n1, '2': n2})


# ---------------------------------------------------------------------------------------------- FPGA U1
fpga_pin_tab = json.load(open(os.path.join(HERE, 'ecp5_85f_bg381_pins.json')))      # [ball, name, type]
io_tab = {r[0]: r for r in json.load(open(os.path.join(HERE, 'ecp5_85f_bg381_io.json')))}
ball_net = {}
for ball, name, typ in fpga_pin_tab:
    if name == 'GND': ball_net[ball] = 'GND'
    elif name == 'VCC': ball_net[ball] = '+1V1'
    elif name == 'VCCAUX': ball_net[ball] = '+2V5'
    elif name.startswith('VCCIO'):
        bank = int(name[5:])
        ball_net[ball] = '+1V8' if bank in (0, 1, 7) else '+3V3'
# application IO from the pin plan
SIG = {}
for sig, (ball, std, extra) in fpga_pins.PINS.items():
    SIG[sig] = ball
board_sig = {
    'clk_24m': 'CLK24M', 'mipi_clk_p': 'MIPI_CLK_P', 'mipi_d_p[0]': 'MIPI_D0_P', 'mipi_d_p[1]': 'MIPI_D1_P',
    'sensor_xvclk': 'XVCLK', 'sensor_xshutdn': 'XSHUTDN', 'i2c_scl': 'SCL', 'i2c_sda': 'SDA',
    'spi_sck': 'SPI_SCK', 'spi_cs_n': 'SPI_CS', 'spi_mosi': 'SPI_MOSI', 'spi_miso': 'SPI_MISO', 'mcu_irq': 'FPGA_IRQ',
    'mcu_rst_n': 'FPGA_RST', **{f'mcu_d[{i}]': f'FB_D{i}' for i in range(8)}, 'mcu_clk': 'FB_CLK', 'mcu_fs': 'FB_FS', 'leds[0]': 'LED_STAT', 'leds[1]': 'LED_1', 'leds[2]': 'LED_2', 'leds[3]': 'LED_3'}
for sig, ball in SIG.items():
    ball_net[ball] = board_sig[sig]
for sig, ball in fpga_pins.DIFF_N.items():
    ball_net[ball] = board_sig[sig].replace('_P', '_N')
# configuration + JTAG pins (fixed balls)
CFG = {'~{PROGRAM}': 'FPGA_PROGRAMN', '~{INIT}': 'FPGA_INITN', 'DONE': 'FPGA_DONE', 'CCLK': 'FPGA_CCLK',
       'TCK': 'JTAG_TCK', 'TMS': 'JTAG_TMS', 'TDI': 'JTAG_TDI', 'TDO': 'JTAG_TDO',
       'CFG_0': 'CFG0', 'CFG_1': 'CFG1', 'CFG_2': 'CFG2'}
for ball, name, typ in fpga_pin_tab:
    if name in CFG: ball_net[ball] = CFG[name]
    if io_tab.get(ball):
        fn = io_tab[ball][2]
        if fn == 'D0/MOSI/IO0': ball_net[ball] = 'FPGA_CFG_MOSI'
        elif fn == 'D1/MISO/IO1': ball_net[ball] = 'FPGA_CFG_MISO'
        elif fn.startswith('HOLDN/DI/BUSY/CSSPIN'): ball_net[ball] = 'FPGA_CFG_CS'
fpga_nets = {b: n for b, n in ball_net.items()}
add('U', 'Package_BGA', 'Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm', 'LFE5U-25F-8BG381I', FPGA_POS[0], FPGA_POS[1], 0, 'bottom',
    fpga_nets, ref_='U1', note='Lattice ECP5-25F (custom RTL: CSI-2/D-PHY RX, threshold, despeckle, CCL, frame bus to the MCU)')

# ---------------------------------------------------------------------------------------------- MCU U2 (RP2350A)
mcu_pin_tab = json.load(open(os.path.join(HERE, 'rp2350a_pins.json')))              # [number, name, type]
MCU_GPIO = {'GPIO2': 'SPI_SCK', 'GPIO3': 'SPI_MOSI', 'GPIO4': 'SPI_MISO', 'GPIO5': 'SPI_CS', 'GPIO6': 'FPGA_PROGRAMN',
            'GPIO7': 'FPGA_INITN', 'GPIO8': 'FPGA_DONE', 'GPIO9': 'FPGA_IRQ', 'GPIO10': 'MCU_AUX', 'GPIO11': 'FPGA_RST',
            'GPIO12': 'FPGA_CFG_MISO', 'GPIO13': 'FPGA_CFG_CS', 'GPIO14': 'FPGA_CCLK', 'GPIO15': 'FPGA_CFG_MOSI',
            **{f'GPIO{16 + i}': f'FB_D{i}' for i in range(8)}, 'GPIO24': 'FB_CLK', 'GPIO25': 'FB_FS'}
MCU_OTHER = {'IOVDD': '+3V3', 'DVDD': '+1V1MCU', 'XIN': 'XIN', 'XOUT': 'XOUT_R', 'SWCLK': 'SWCLK', 'SWDIO': 'SWDIO', 'RUN': 'MCU_RUN',
             'ADC_AVDD': 'ADC_AVDD', 'VREG_AVDD': 'VREG_AVDD', 'VREG_PGND': 'GND', 'VREG_LX': 'VREG_LX', 'VREG_VIN': '+3V3',
             'VREG_FB': '+1V1MCU', 'USB_DM': 'USB_DM_MCU', 'USB_DP': 'USB_DP_MCU', 'USB_OTP_VDD': '+3V3', 'QSPI_IOVDD': '+3V3',
             'QSPI_SD3': 'QSPI_SD3', 'QSPI_SCLK': 'QSPI_SCLK', 'QSPI_SD0': 'QSPI_SD0', 'QSPI_SD2': 'QSPI_SD2',
             'QSPI_SD1': 'QSPI_SD1', '~{QSPI_SS}': 'QSPI_SS', 'GND': 'GND'}
mcu_nets = {}
for num, name, typ in mcu_pin_tab:
    if name in MCU_GPIO: mcu_nets[num] = MCU_GPIO[name]
    elif name in MCU_OTHER: mcu_nets[num] = MCU_OTHER[name]
MCU_POS = (18.0, 9.5)
add('U', 'Package_DFN_QFN', 'QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm', 'RP2350A', MCU_POS[0], MCU_POS[1], 0, 'bottom', mcu_nets, ref_='U2',
    note='Raspberry Pi RP2350A: USB, frame bus receiver (PIO+DMA), tag unit (C), pose solve, field map/calibration storage')
mx, my = MCU_POS
# MCU decoupling + VREG
for i, (dx, dy) in enumerate([(-4.4, 3.2), (-4.4, -3.2), (4.4, 3.2), (4.4, -3.2), (-1.6, 4.6), (1.6, -4.6)]):
    cap('100n', '+3V3', mx + dx, my + dy)
for i, (dx, dy) in enumerate([(-4.4, 1.2), (4.4, 1.2), (-4.4, -1.2)]):
    cap('100n', '+1V1MCU', mx + dx, my + dy)
cap('4u7', '+1V1MCU', mx + 5.9, my + 1.2, size=C0603)
cap('4u7', '+3V3', mx - 5.9, my + 1.2, size=C0603)
add('L', 'Inductor_SMD', 'L_1008_2520Metric', '3u3', mx + 1.6, my + 7.4, 0, 'bottom', {'1': 'VREG_LX', '2': '+1V1MCU'})
res('33R', '+3V3', 'VREG_AVDD', mx - 3.0, my - 5.6)
cap('4u7', 'VREG_AVDD', mx - 4.6, my - 5.6, size=C0603)
res('33R', '+3V3', 'ADC_AVDD', mx - 3.0, my - 6.8)
cap('100n', 'ADC_AVDD', mx - 4.6, my - 6.8)
res('10k', 'MCU_RUN', '+3V3', mx + 3.0, my - 5.6)
cap('100n', 'MCU_RUN', mx + 4.6, my - 5.6)
# 12 MHz crystal
add('Y', 'Crystal', 'Crystal_SMD_3225-4Pin_3.2x2.5mm', '12MHz', mx - 0.5, my + 8.6, 0, 'bottom', {'1': 'XIN', '2': 'GND', '3': 'XOUT', '4': 'GND'})
cap('15p', 'XIN', mx - 2.8, my + 6.8)
cap('15p', 'XOUT', mx + 1.8, my + 6.8)
res('1k', 'XOUT', 'XOUT_R', mx - 0.5, my + 6.2)
# flash W25Q128 (WSON-8 6x5)
FL = (18.5, -5.0)
add('U', 'Package_SON', 'WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm', 'W25Q128JVSIQ', FL[0], FL[1], 90, 'bottom',
    {'1': 'QSPI_SS', '2': 'QSPI_SD1', '3': 'QSPI_SD2', '4': 'GND', '5': 'QSPI_SD0', '6': 'QSPI_SCLK', '7': 'QSPI_SD3', '8': '+3V3', '9': 'GND'}, ref_='U3',
    note='16 MB QSPI flash: firmware, FPGA bitstream, field map/calibration slots')
cap('100n', '+3V3', FL[0] + 3.6, FL[1] + 3.0)
# boot button (QSPI_SS to GND through 1k)
add('SW', 'Button_Switch_SMD', 'SW_SPST_PTS810', 'BOOTSEL', P['boot_button']['pos'][0], P['boot_button']['pos'][1], 0, 'bottom',
    {'1': 'BOOT_N', '2': 'GND'})
res('1k', 'QSPI_SS', 'BOOT_N', 20.0, 8.0)
# SWD test points
for k, (n, dy) in enumerate((('SWCLK', 0), ('SWDIO', 1.8), ('GND', 3.6))):
    add('TP', 'TestPoint', 'TestPoint_Pad_D1.0mm', n, 20.5, -6 - dy, 0, 'bottom', {'1': n})

# ---------------------------------------------------------------------------------------------- USB-C J1
USB = (-20.0, -8.0)
add('J', 'Connector_USB', 'USB_C_Receptacle_HRO_TYPE-C-31-M-12', 'USB-C', USB[0], USB[1], 90, 'bottom',
    {'A1': 'GND', 'B1': 'GND', 'A12': 'GND', 'B12': 'GND', 'A4': 'VBUS', 'B4': 'VBUS', 'A9': 'VBUS', 'B9': 'VBUS',
     'A5': 'CC1', 'B5': 'CC2', 'A6': 'USB_DP', 'B6': 'USB_DP', 'A7': 'USB_DN', 'B7': 'USB_DN', 'A8': '', 'B8': '', 'SH': 'GND'},
    ref_='J1', note='USB-C: power + data (device, 5.1k Rd)')
res('5k1', 'CC1', 'GND', -12.4, -4.0)
res('5k1', 'CC2', 'GND', -12.4, -6.2)
add('U', 'Package_TO_SOT_SMD', 'SOT-23-6', 'USBLC6-2SC6', -12.4, -10.5, 0, 'bottom',
    {'1': 'USB_DP', '2': 'GND', '3': 'USB_DN', '4': 'USB_DN', '5': 'VBUS', '6': 'USB_DP'}, ref_='U11')
res('27R', 'USB_DP', 'USB_DP_MCU', -9.8, -13.0)
res('27R', 'USB_DN', 'USB_DM_MCU', -9.8, -14.2)
add('FB', 'Inductor_SMD', 'L_0603_1608Metric', 'BLM18 600R', -16.0, -15.0, 0, 'bottom', {'1': 'VBUS', '2': '+5V'})
cap('10u', '+5V', -18.0, -15.0, size=C0805)
cap('10u', 'VBUS', -14.0, -15.0, size=C0805)
cap('1u', '+5V', -19.5, -17.0, size=C0603)

# ---------------------------------------------------------------------------------------------- power tree
def buck(refn, x, y, vout, rtop, rbot, net_sw):
    u = add('U', 'Package_TO_SOT_SMD', 'SOT-23-5', 'TLV62569', x, y, 0, 'bottom',
            {'1': '+5V', '2': 'GND', '3': net_sw, '4': '+5V', '5': net_sw + '_FB'}, ref_=refn, note=f'5 V -> {vout} synchronous buck')
    add('L', 'Inductor_SMD', 'L_1008_2520Metric', '2u2', x + 4.0, y, 0, 'bottom', {'1': net_sw, '2': vout})
    res(rtop, vout, net_sw + '_FB', x, y + 2.6)
    res(rbot, net_sw + '_FB', 'GND', x + 1.5, y + 2.6)
    cap('10u', '+5V', x - 2.6, y - 2.0, size=C0805)
    for k in range(2):
        cap('22u', vout, x + 6.4 + 2.2 * k, y, size=C0805)
buck('U4', -8.5, -21.5, '+3V3', '453k', '100k', 'SW3V3')
buck('U5', 2.5, -21.5, '+1V1', '82k5', '100k', 'SW1V1')
cap('22u', '+1V1', 10.2, -21.0, size=C0805)
LDOS = [('U6', '+2V5', 'TLV75525', -21.0, 4.0), ('U7', '+1V8', 'TLV75518', -21.0, 9.0),
        ('U8', '+2V8', 'TLV75528', -21.0, 14.0), ('U9', '+1V2', 'TLV75512', -21.0, 19.0)]
for refn, out, val, x, y in LDOS:
    add('U', 'Package_TO_SOT_SMD', 'SOT-23-5', val, x, y, 0, 'bottom', {'1': '+3V3', '2': 'GND', '3': '+3V3', '4': '', '5': out}, ref_=refn,
        note=f'LDO {out}')
    cap('1u', '+3V3', x + 3.0, y - 1.2, size=C0603)
    cap('2u2', out, x + 3.0, y + 1.2, size=C0603)
cap('4u7', '+3V3', -15.0, 12.0, size=C0603)
cap('4u7', '+1V8', -15.0, 7.0, size=C0603)
# status LEDs (top side) + power LED
# The LEDs sit on the flat part of the front-cover roof (see pcb_params.json); each 1k resistor is on the top side
# next to its LED (the bottom is occupied by the USB-C receptacle there); cathode pad (1) faces the resistor.
(lx0, ly0), (lx1, ly1) = P['status_leds'][0]['pos'], P['status_leds'][1]['pos']
add('D', 'LED_SMD', 'LED_0603_1608Metric', 'PWR', lx0, ly0, 180, 'top', {'1': 'LED_PWR_K', '2': '+3V3'})
res('1k', 'LED_PWR_K', 'GND', lx0 + 2.8, ly0, 0, side='top')
add('D', 'LED_SMD', 'LED_0603_1608Metric', 'STAT', lx1, ly1, 180, 'top', {'1': 'LED_STAT_K', '2': '+3V3'})
res('1k', 'LED_STAT', 'LED_STAT_K', lx1 + 2.8, ly1, 180, side='top')

# ---------------------------------------------------------------------------------------------- FPGA support
# decoupling ring around U1 (bottom side)
fx, fy = FPGA_POS
slots = []
for i in range(11): slots.append((fx - 8.0 + 1.6 * i, fy + 10.2)); slots.append((fx - 8.0 + 1.6 * i, fy - 10.2))
for i in range(9): slots.append((fx - 10.4, fy - 6.4 + 1.6 * i)); slots.append((fx + 10.4, fy - 6.4 + 1.6 * i))
rails = ['+1V1'] * 12 + ['+2V5'] * 4 + ['+1V8'] * 5 + ['+3V3'] * 7
for (x, y), net in zip(slots, rails):
    rot = 90 if abs(x - fx) > 9 else 0
    cap('100n', net, x, y, rot)
cap('4u7', '+1V1', fx - 6, fy - 12.6, size=C0603); cap('4u7', '+1V1', fx + 6, fy - 12.6, size=C0603)
cap('4u7', '+2V5', fx - 3, fy + 12.0, size=C0603); cap('4u7', '+3V3', fx + 3, fy + 12.0, size=C0603)
# config straps (slave SPI: CFG[2:0] = 001) and handshake pull-ups
res('4k7', 'CFG0', '+3V3', fx - 13.2, fy + 6.0); res('4k7', 'CFG1', 'GND', fx - 13.2, fy + 4.6); res('4k7', 'CFG2', 'GND', fx - 13.2, fy + 3.2)
res('10k', 'FPGA_PROGRAMN', '+3V3', fx + 13.2, fy + 6.0); res('10k', 'FPGA_INITN', '+3V3', fx + 13.2, fy + 4.6)
res('10k', 'FPGA_DONE', '+3V3', fx + 13.2, fy + 3.2); res('10k', 'FPGA_RST', '+3V3', fx + 13.2, fy + 1.8)
res('10k', 'SPI_CS', '+3V3', fx + 13.2, fy + 0.4)
# 24 MHz 1.8 V oscillator for the FPGA PLL
add('Y', 'Oscillator', 'Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm', '24MHz 1.8V', fx - 13.6, fy - 12.0, 0, 'bottom',
    {'1': '+1V8', '2': 'GND', '3': 'CLK24M', '4': '+1V8'}, note='1.8 V CMOS oscillator, FPGA PLL reference')
cap('100n', '+1V8', fx - 13.6, fy - 14.6)
# MIPI terminations + sensor control pull-ups next to the FPGA top edge
for k, (p, n) in enumerate((('MIPI_CLK_P', 'MIPI_CLK_N'), ('MIPI_D0_P', 'MIPI_D0_N'), ('MIPI_D1_P', 'MIPI_D1_N'))):
    res('100R', p, n, fx - 5.0 + 2.2 * k, fy + 8.5)
res('2k2', 'SCL', '+1V8', fx + 5.0, fy + 8.5); res('2k2', 'SDA', '+1V8', fx + 6.4, fy + 8.5)
# JTAG header (2x5 1.27 mm) at the bottom edge
add('J', 'Connector_PinHeader_1.27mm', 'PinHeader_2x05_P1.27mm_Vertical_SMD', 'JTAG', 20.0, -14.5, 0, 'bottom',
    {'1': '+3V3', '2': 'JTAG_TMS', '3': 'GND', '4': 'JTAG_TCK', '5': 'GND', '6': 'JTAG_TDO', '7': '', '8': 'JTAG_TDI', '9': 'GND', '10': ''},
    ref_='J2')
for n, x in (('LED_1', 20.5), ('LED_2', 20.5)):
    pass
for k, n in enumerate(('LED_1', 'LED_2', 'LED_3', 'MCU_AUX', 'FPGA_IRQ')):
    add('TP', 'TestPoint', 'TestPoint_Pad_D1.0mm', n, 22.0, -10.0 - 1.8 * k, 0, 'bottom', {'1': n})

# ---------------------------------------------------------------------------------------------- sensor U10 (top side)
SENSOR_BALLS = {   # from the Antmicro OV9281 dual camera board schematic (KiCad 9, open hardware)
    'B8': 'AVDD_S', 'A2': 'DVDD_S', 'B7': 'DOVDD_S', 'F3': 'EVDD_S', 'E8': 'VH', 'D5': 'PVDD_S', 'D7': 'VN1', 'E7': 'VN2', 'F7': 'VN3',
    'E3': 'GND', 'C8': 'GND', 'A3': 'GND', 'G4': 'MIPI_CLK_P', 'H4': 'MIPI_CLK_N', 'G5': 'MIPI_D1_P', 'F5': 'MIPI_D1_N',
    'G3': 'MIPI_D0_P', 'H3': 'MIPI_D0_N', 'E4': 'SCL', 'A4': 'SDA', 'E2': 'XVCLK', 'A5': 'XSHUTDN',
    'B6': 'SNS_STROBE', 'B5': 'SNS_FSIN', 'C2': '', 'D6': '', 'C3': '', 'D4': '', 'C4': '', 'B4': '', 'C6': '', 'E6': '', 'D1': '',
    'E1': '', 'C7': '', 'A6': ''}
add('U', 'CUSTOM', 'OV9281_CSP', 'OV9281', SENSOR_POS[0], SENSOR_POS[1], 0, 'top', SENSOR_BALLS, ref_='U10',
    note='OmniVision OV9281 1280x800 global shutter (bare CSP). BALL PITCH/PAD SIZE ASSUMED 0.5/0.25 mm - VERIFY against the OmniVision drawing')
add('H', 'CUSTOM', 'M12_LENS_MOUNT', 'M12 holder 20x20', SENSOR_POS[0], SENSOR_POS[1], 0, 'top', {}, ref_='LH1', note='mechanical: M12 lens holder footprint')
# sensor rail decoupling and filters on the bottom side, directly under the lens holder
sx, sy = SENSOR_POS
for k, (net, val) in enumerate((('AVDD_S', '1u'), ('AVDD_S', '100n'), ('DVDD_S', '1u'), ('DVDD_S', '100n'), ('DOVDD_S', '1u'), ('DOVDD_S', '100n'),
                                ('PVDD_S', '100n'), ('EVDD_S', '100n'), ('VH', '1u'), ('VN1', '1u'), ('VN2', '1u'), ('VN3', '1u'))):
    cap(val, net, sx - 7.0 + 1.3 * k, sy - 4.5, size=C0402 if val == '100n' else C0603)
# sensor supply filtering (ferrite beads from the LDO rails)
for k, (src, dst) in enumerate((('+2V8', 'AVDD_S'), ('+1V2', 'DVDD_S'), ('+1V8', 'DOVDD_S'), ('+1V2', 'PVDD_S'), ('+2V8', 'EVDD_S'))):
    add('FB', 'Inductor_SMD', 'L_0603_1608Metric', 'BLM18 120R', sx - 6.0 + 2.6 * k, sy + 4.5, 0, 'bottom', {'1': src, '2': dst})
for k, n in enumerate(('SNS_STROBE', 'SNS_FSIN')):
    add('TP', 'TestPoint', 'TestPoint_Pad_D1.0mm', n, sx + 8.5, sy - 4.0 + 1.8 * k, 0, 'bottom', {'1': n})

# mounting holes
for i, (x, y) in enumerate(P['mounting_holes']['positions']):
    add('H', 'MountingHole', 'MountingHole_2.2mm_M2', 'M2', x, y, 0, 'top', {}, ref_=f'MH{i + 1}')


def nets_used():
    s = set()
    for p in parts:
        s.update(n for n in p['nets'].values() if n)
    return sorted(s)


def netlist():
    """net -> [(ref, pad)]"""
    d = collections.defaultdict(list)
    for p in parts:
        for pad, n in p['nets'].items():
            if n: d[n].append((p['ref'], pad))
    return d


# ---- spread the passives over both sides: the top side is empty outside the lens-holder footprint, and the housing roof
# leaves 2.0 mm for top parts (0402/0603/0805 are <= 1.25 mm).  Keep clear of the lens holder, LEDs, USB-C tabs and screw posts.
def _top_ok(p):
    if not p['ref'].startswith(('C', 'R')) or p['lib'] == 'CUSTOM' or p['side'] != 'bottom': return False
    x, y = p['x'], p['y']
    if abs(x) <= 11.0 and -1.8 <= y <= 19.8: return False                  # lens holder + sensor
    if abs(x + 20.0) < 5.0 and abs(y + 8.0) < 9.0: return False             # USB-C shield tabs
    for q in parts:
        if q['ref'].startswith('MH') and math.hypot(q['x'] - x, q['y'] - y) < 5.0: return False
    return True


if os.environ.get('PASSIVES_TOP', '0') == '1':
    for _p in parts:
        if _top_ok(_p): _p['side'] = 'top'


def bom():
    g = collections.defaultdict(list)
    for p in parts:
        if p['lib'] == 'CUSTOM' or p['ref'].startswith(('MH', 'TP')): continue
        g[(p['value'], p['fp'])].append(p['ref'])
    return g


if __name__ == '__main__':
    nl = netlist()
    print(len(parts), 'parts,', len(nl), 'nets')
    singles = [n for n, v in nl.items() if len(v) < 2]
    print('single-pin nets:', singles)
