"""Device clock: the 1 MHz tick generator of cam_core must be exact for the 100 MHz (1/100) and 85.714 MHz (7/600) cores (tb/tb_clock.v)."""
import rtlutil

RTL = ['rtl/csi2_rx.v', 'rtl/thresh_binarize.v', 'rtl/despeckle.v', 'rtl/run_ccl.v', 'rtl/mask_stream.v', 'rtl/i2c_master.v',
       'rtl/sensor_init.v', 'rtl/spi_slave.v', 'rtl/cam_core.v', 'tb/tb_clock.v']


def test_device_clock_tick_exact_and_carries():
    out = rtlutil.run(rtlutil.build('tb_clock', RTL, top='tb_clock'))
    assert 'CLOCK PASS' in out, out[-800:]
