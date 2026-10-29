"""Pin plan for the ECP5-85F caBGA381: single source of truth for the LPF (FPGA constraints) and the PCB netlist.
Balls were chosen from the Project Trellis IO database (pcb/ecp5_85f_bg381_io.json): MIPI on left bank 7 (VCCIO 1.8 V; 4:1 DDR gearing is only
supported on left/right banks; clock lane on the PCLKT7_0 edge-clock pad), sensor control + oscillator on bank 1 (1.8 V), MCU SPI / LEDs on bank 2 (3.3 V)."""
import os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# name -> (ball, io_standard, extra)       diff pairs list the P ball; the N ball is given separately
PINS = {
    'clk_24m':        ('D12', 'LVCMOS18', 'PULLMODE=NONE'),
    'mipi_clk_p':     ('F2',  'LVDS', 'DIFFRESISTOR=OFF'),   # PCLKT7_0 / N = E2   (IDDRX2F needs a left/right bank)
    'mipi_d_p[0]':    ('G3',  'LVDS', 'DIFFRESISTOR=OFF'),   # PCLKT7_1 / N = F3
    'mipi_d_p[1]':    ('H4',  'LVDS', 'DIFFRESISTOR=OFF'),   # GR_PCLK7_1 / N = G5
    'sensor_xvclk':   ('B13', 'LVCMOS18', 'DRIVE=8'),
    'sensor_xshutdn': ('C13', 'LVCMOS18', 'DRIVE=4'),
    'i2c_scl':        ('A12', 'LVCMOS18', 'PULLMODE=NONE'),
    'i2c_sda':        ('A13', 'LVCMOS18', 'PULLMODE=NONE'),
    'spi_sck':        ('E16', 'LVCMOS33', 'PULLMODE=DOWN'),
    'spi_cs_n':       ('E17', 'LVCMOS33', 'PULLMODE=UP'),
    'spi_mosi':       ('E18', 'LVCMOS33', 'PULLMODE=NONE'),
    'spi_miso':       ('F16', 'LVCMOS33', 'DRIVE=8'),
    'mcu_irq':        ('F18', 'LVCMOS33', 'DRIVE=4'),
    'mcu_rst_n':      ('G16', 'LVCMOS33', 'PULLMODE=UP'),
    'leds[0]':        ('D18', 'LVCMOS33', 'DRIVE=4'),
    'leds[1]':        ('D19', 'LVCMOS33', 'DRIVE=4'),
    'leds[2]':        ('E19', 'LVCMOS33', 'DRIVE=4'),
    'leds[3]':        ('F19', 'LVCMOS33', 'DRIVE=4'),
}
DIFF_N = {'mipi_clk_p': 'E2', 'mipi_d_p[0]': 'F3', 'mipi_d_p[1]': 'G5'}   # complementary balls (board nets MIPI_*_N)


def lpf():
    lines = ['BLOCK RESETPATHS;', 'BLOCK ASYNCPATHS;']
    for n, (ball, std, extra) in PINS.items():
        lines.append(f'LOCATE COMP "{n}" SITE "{ball}";')
        lines.append(f'IOBUF PORT "{n}" IO_TYPE={std} {extra};')
    lines += ['FREQUENCY PORT "clk_24m" 24 MHz;', 'FREQUENCY PORT "mipi_clk_p" 400 MHz;']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    open(os.path.join(ROOT, 'rtl', 'apriltag_cam.lpf'), 'w').write(lpf())
    print(lpf())
