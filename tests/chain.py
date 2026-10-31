"""Full-chain helpers: sensor image(s) -> CSI-2 @120fps -> cam_core RTL -> frame packets on the MCU bus -> C tag unit (what the RP2350 firmware runs)."""
import os, sys, time, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import rtlutil, csi_stream, golden, tpu_harness, attpu

RTL = ['rtl/csi2_rx.v', 'rtl/thresh_binarize.v', 'rtl/despeckle.v', 'rtl/run_ccl.v', 'rtl/mask_stream.v', 'rtl/i2c_master.v',
       'rtl/sensor_init.v', 'rtl/spi_slave.v', 'rtl/cam_core.v', 'tb/tb_cam.v']


def build():
    return rtlutil.build('tb_cam' + os.environ.get('CHAIN_TAG', ''), RTL)


def run_frames(vvp, frames, tag, maxcyc=None, maxham=2, **kw):
    """Simulate the frames back to back; returns (log, res, seconds).  res['results'][i] describes packet i that left on the MCU bus:
    dict(seq, cyc, packet (parsed, see attpu.parse_packet), words = the 16+16*31 word result image the C tag unit produces from it (same layout as the
    old FPGA result RAM, so decode_tags() works unchanged), tags).  res['stats'] = the STATS line of the testbench (statistics registers).
    maxcyc: simulation clock budget (tests that expect FEWER packets than frames, e.g. a rejected bad-CRC frame, pass a small budget because the
    testbench otherwise waits for the missing packet until it expires)"""
    pre = os.path.join(rtlutil.SIM, tag)
    npk = csi_stream.write_stream(frames, pre, **kw)
    out = pre + '.out'
    for old in [f for f in os.listdir(rtlutil.SIM) if f.startswith(tag + '.pkt.')]:
        os.remove(os.path.join(rtlutil.SIM, old))
    t = time.time()
    log = rtlutil.run(vvp, [f'frames={pre}.frames.hex', f'plen={pre}.plen.hex', f'npk={npk}', f'nframes={len(frames)}',
                            f'out={out}', f'pkt={pre}.pkt'] + ([f'maxcyc={maxcyc}'] if maxcyc else []), timeout=7200)
    res = parse(out, pre + '.pkt', maxham)
    for i in range(len(res['packets'])):
        try: os.remove(f'{pre}.pkt.{i}.hex')
        except OSError: pass
    return log, res, time.time() - t


def parse(path, pkt_prefix=None, maxham=2):
    results, stats, raw = [], None, []
    for l in open(path).read().splitlines():
        if l.startswith('PACKET'):
            d = dict(x.split('=') for x in l.split()[2:]); raw.append((int(l.split()[1]), int(d['bytes']), int(d['end'])))
        elif l.startswith('STATS'):
            stats = dict(x.split('=') for x in l.split()[1:])
    for n, nbytes, end in raw:
        if nbytes != attpu.PKT_BYTES or pkt_prefix is None:
            continue
        pkt = attpu.parse_packet(attpu.load_packet_hex(f'{pkt_prefix}.{n}.hex'))
        words, nt = attpu.detect(pkt, maxham=maxham)
        results.append(dict(seq=pkt['seq'], cyc=end, packet=pkt, words=words[:16 + 16 * 31], tags=nt, index=n))
    return dict(results=results, stats=stats, packets=raw)


def decode_tags(words):
    return tpu_harness.parse_results(words + [0] * (512 - len(words)))


def iss_reference(img, frame_id):
    """golden pipeline on the same image: Python threshold -> components -> TPU ISS"""
    mask = golden.binarize_clean(img)
    tags, mach, nc = tpu_harness.run_iss(mask, frame_id=frame_id)
    return tags, mach, nc
