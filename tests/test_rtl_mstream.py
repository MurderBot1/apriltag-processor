"""rtl/mask_stream.v (FPGA -> MCU frame bus): packet format, byte timing, FIFO behaviour, late labeller, short frame, aborted packet (tb/tb_mstream.v)."""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(__file__))
import rtlutil


@pytest.fixture(scope='module')
def vvp():
    return rtlutil.build('tb_mstream', ['rtl/mask_stream.v', 'tb/tb_mstream.v'])


@pytest.mark.parametrize('args', [['frames=3'], ['late=1'], ['short=1'], ['abort=1']], ids=['three-frames', 'late-labeller', 'short-frame-padded', 'abort-mid-packet'])
def test_mask_stream(vvp, args):
    out = rtlutil.run(vvp, args)
    assert 'PASS' in out and 'FAIL' not in out, out[-800:]
