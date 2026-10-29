"""Full-chain helpers: sensor image(s) -> CSI-2 @120fps -> cam_core RTL -> results read over SPI."""
import os, sys, time, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, csi_stream, golden, tpu_harness

RTL = ['rtl/csi2_rx.v', 'rtl/thresh_binarize.v', 'rtl/despeckle.v', 'rtl/run_ccl.v', 'rtl/tpu_core.v', 'rtl/i2c_master.v',
       'rtl/sensor_init.v', 'rtl/spi_slave.v', 'rtl/cam_core.v', 'tb/tb_cam.v']


def build():
    tpu_harness.tpu_prog.program()[1].hexfile(os.path.join(rtlutil.ROOT, 'rtl', 'tpu_prog.hex'))
    return rtlutil.build('tb_cam', RTL)


def run_frames(vvp, frames, tag, maxcyc=None, **kw):
    """maxcyc: simulation clock budget for the testbench (default 400M = the testbench's own limit; tests that expect FEWER results than
    frames, e.g. a rejected bad-CRC frame, pass a small budget because the testbench otherwise waits for the missing result until it expires)"""
    pre = os.path.join(rtlutil.SIM, tag)
    npk = csi_stream.write_stream(frames, pre, **kw)
    out = pre + '.out'
    t = time.time()
    log = rtlutil.run(vvp, [f'frames={pre}.frames.hex', f'plen={pre}.plen.hex', f'npk={npk}', f'nframes={len(frames)}',
                            f'out={out}'] + ([f'maxcyc={maxcyc}'] if maxcyc else []), timeout=7200)
    return log, parse(out), time.time() - t


def parse(path):
    lines = open(path).read().splitlines()
    results, stats, i = [], None, 0
    while i < len(lines):
        l = lines[i]
        if l.startswith('RESULT'):
            d = dict(x.split('=') for x in l.split()[1:])
            words = [int(x, 16) for x in lines[i + 1:i + 1 + 16 + 16 * 8]]
            results.append(dict(seq=int(d['seq']), bank=int(d['bank']), tags=int(d['tags']), cyc=int(d['cyc']), words=words))
            i += 1 + 16 + 16 * 8
        elif l.startswith('STATS'):
            stats = dict(x.split('=') for x in l.split()[1:]); i += 1
        else: i += 1
    return dict(results=results, stats=stats)


def decode_tags(words):
    return tpu_harness.parse_results(words + [0] * (512 - len(words)))


def iss_reference(img, frame_id):
    """golden pipeline on the same image: Python threshold -> components -> TPU ISS"""
    mask = golden.binarize_clean(img)
    tags, mach, nc = tpu_harness.run_iss(mask, frame_id=frame_id)
    return tags, mach, nc
