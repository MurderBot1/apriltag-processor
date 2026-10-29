"""Build CSI-2 sensor streams for the full-chain testbench (OV9281 RAW8, 2 lanes, 120 fps timing).

frames.hex : all packet beats back to back, 4 hex digits per beat {lane1, lane0}
plen.hex   : one word per packet: beats | type<<24   (type 0 = FS, 1 = LINE, 2 = FE)
Slot timing (done in the testbench): every packet starts on an 800-beat slot boundary; a frame is
1041 slots (FS slot, 800 line slots, FE slot, 239 idle slots) = 832,800 beats = 8.328 ms @ 100 MHz = 120.07 fps.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import golden

SLOT = 800
FRAME_SLOTS = 1041


def packets_to_beats(pk):
    b = bytes(pk) + (b'\x00' if len(pk) & 1 else b'')
    a = np.frombuffer(b, np.uint8)
    return (a[1::2].astype(np.uint32) << 8) | a[0::2]


def write_stream(frames, prefix, bad_crc_lines=(), drop_lines=()):
    """frames: list of 800x1280 uint8; returns number of packets."""
    beats, plen = [], []
    for fi, img in enumerate(frames):
        pk = golden.csi2_frame_packets(img, fi & 0xFFFF)
        types = [0] + [1] * 800 + [2]
        for k, (p, t) in enumerate(zip(pk, types)):
            if t == 1 and (fi, k - 1) in drop_lines: continue
            if t == 1 and (fi, k - 1) in bad_crc_lines:
                p = golden.csi2_long(0x2A, img[k - 1].tobytes(), bad_crc=True)
            bt = packets_to_beats(p)
            assert len(bt) <= SLOT
            beats.append(bt); plen.append(len(bt) | (t << 24))
    beats = np.concatenate(beats)
    with open(prefix + '.frames.hex', 'w') as f:
        f.write('\n'.join(f'{v:04x}' for v in beats) + '\n')
    with open(prefix + '.plen.hex', 'w') as f:
        f.write('\n'.join(f'{v:08x}' for v in plen) + '\n')
    return len(plen)
