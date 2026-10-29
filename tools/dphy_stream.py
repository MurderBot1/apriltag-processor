"""Generate MIPI D-PHY HS lane bit streams (2 lanes, 1 bit per UI) for the D-PHY receiver testbench.

Each packet becomes one HS burst on both lanes: [LP gap noise][HS-ZERO][sync 0xB8][payload bytes, LSB first,
byte i -> lane i%2][HS-TRAIL].  Lane 1 may be delayed by `skew` UI relative to lane 0.  Bits are packed 32 per word,
earliest bit in bit 0, written as hex words (one per line)."""
import numpy as np, os, sys
sys.path.insert(0, os.path.dirname(__file__))


def bits_of_bytes(bs):
    a = np.frombuffer(bytes(bs), np.uint8)
    return ((a[:, None] >> np.arange(8)) & 1).reshape(-1)


def lane_streams(packets, slot_ui=6400, lp_ui=300, zero_ui=160, skew=0, rng=None, jitter_slots=False):
    rng = rng or np.random.default_rng(0)
    l0, l1 = [], []
    for p in packets:
        p = bytes(p) + (b'\x00' if len(p) & 1 else b'')
        b0, b1 = p[0::2], p[1::2]
        def burst(pay):
            bits = np.concatenate([np.zeros(zero_ui, np.uint8), bits_of_bytes(b'\xB8')[:8], bits_of_bytes(pay)])
            trail = np.full(8, 1 - bits[-1], np.uint8)
            return np.concatenate([bits, trail])
        s0, s1 = burst(b0), burst(b1)
        lp = lp_ui + (int(rng.integers(0, 40)) if jitter_slots else 0)
        for lane, s, sk in ((l0, s0, 0), (l1, s1, skew)):
            n_lp = lp + sk
            noise = rng.integers(0, 2, n_lp).astype(np.uint8)
            body = np.concatenate([noise, s])
            pad = slot_ui - len(body)
            assert pad >= 0, (slot_ui, len(body))
            lane.append(np.concatenate([body, rng.integers(0, 2, pad).astype(np.uint8)]))
    return np.concatenate(l0), np.concatenate(l1)


def pack_words(bits):
    n = (len(bits) + 31) // 32 * 32
    b = np.zeros(n, np.uint64); b[:len(bits)] = bits
    w = (b.reshape(-1, 32) << np.arange(32, dtype=np.uint64)).sum(axis=1)
    return w.astype(np.uint32)


def write_lanes(packets, prefix, **kw):
    a, b = lane_streams(packets, **kw)
    for name, bits in (('l0', a), ('l1', b)):
        with open(f'{prefix}.{name}.hex', 'w') as f:
            f.write('\n'.join(f'{int(w):08x}' for w in pack_words(bits)) + '\n')
    return len(a)
