"""I2C master + OV9281 init sequencer against a behavioural sensor model (all 103 init writes land in order,
read-back, ID register 0x9281, NACK detection)."""
import os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
import rtlutil


def test_sensor_init_and_register_access():
    vvp = rtlutil.build('tb_i2c', ['rtl/i2c_master.v', 'rtl/sensor_init.v', 'tb/tb_i2c.v'])
    out = rtlutil.run(vvp, [])
    assert 'TIMEOUT' not in out, out
    m = re.search(r'INIT writes_logged=(\d+) expected=(\d+) nacks=(\d+) errors=(\d+)', out)
    assert m, out
    logged, expected, nacks, errors = map(int, m.groups())
    assert logged == expected == 103 and nacks == 0 and errors == 0
    assert 'READBACK 3509=55' in out
    assert 'ID_HI=92' in out and 'ID_LO=81' in out
    assert 'NACK_PROBE nack=1' in out
