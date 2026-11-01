"""Framing / COBS / CRC16 of the USB protocol: C implementation (firmware/core/atproto.c) cross-checked against the Python one."""
import ctypes as C
import os
import random
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'host'))
from apriltag_cam import protocol as P      # noqa: E402
from apriltag_cam import simfw              # noqa: E402

L = simfw.lib()
MAX_BODY = P.MAX_BODY


class RX(C.Structure):
    _fields_ = [('buf', C.c_uint8 * P.MAX_FRAME), ('n', C.c_size_t), ('overflow', C.c_uint8), ('bad_frames', C.c_uint32)]


class CRx:
    """Firmware receiver state machine."""
    def __init__(self):
        self.r = RX()
        L.at_rx_init(C.byref(self.r))

    def feed(self, data):
        out = []
        t = C.c_uint8()
        body = C.c_void_p()
        n = C.c_size_t()
        for b in data:
            if L.at_rx_feed(C.byref(self.r), b, C.byref(t), C.byref(body), C.byref(n)):
                out.append((t.value, C.string_at(body.value, n.value) if n.value else b''))
        return out

    @property
    def bad(self):
        return self.r.bad_frames


def c_encode(typ, body):
    out = (C.c_uint8 * (len(body) + len(body) // 254 + 16))()
    n = L.at_frame_encode(typ, bytes(body), len(body), out, len(out))
    return bytes(out[:n])


def rbody(rng, n):
    return bytes(rng.randrange(256) for _ in range(n))


def special_bodies():
    yield b''
    for n in (1, 2, 3, 100, 252, 253, 254, 255, 256):
        yield bytes(n)                        # all zero
        yield b'\xff' * n                     # all 0xFF
        yield b'\x01' * n
        yield bytes((i % 255) + 1 for i in range(n))   # no zeros at all
        yield bytes([0xFF] * (n // 2) + [0] + [0xFF] * (n - n // 2 - 1)) if n else b''


# ---------------------------------------------------------------------------------------- CRC
def test_crc_check_value():
    assert P.crc16(b'123456789') == 0x29B1
    assert L.at_crc16(b'123456789', 9) == 0x29B1
    assert P.crc16(b'') == 0xFFFF


def test_crc_c_matches_python_random():
    rng = random.Random(1)
    for _ in range(300):
        d = rbody(rng, rng.randrange(0, 300))
        assert L.at_crc16(d, len(d)) == P.crc16(d)


# ---------------------------------------------------------------------------------------- round trips
def test_encode_c_equals_python_and_roundtrips_random():
    rng = random.Random(2)
    rx = CRx()
    dec = P.FrameDecoder()
    for i in range(600):
        n = rng.randrange(0, MAX_BODY + 1)
        body = rbody(rng, n)
        typ = rng.randrange(1, 256)
        fc, fp = c_encode(typ, body), P.encode_frame(typ, body)
        assert fc == fp
        assert fc[-1] == 0 and 0 not in fc[:-1]
        assert rx.feed(fc) == [(typ, body)]
        assert dec.feed(fp) == [(typ, body)]
    assert rx.bad == 0 and dec.bad_frames == 0


def test_special_patterns_roundtrip():
    rx, dec = CRx(), P.FrameDecoder()
    k = 0
    for body in special_bodies():
        fr = P.encode_frame(0x42, body)
        assert fr == c_encode(0x42, body)
        assert rx.feed(fr) == [(0x42, body)]
        assert dec.feed(fr) == [(0x42, body)]
        k += 1
    assert k > 30 and rx.bad == 0


def test_type_zero_and_ff_bytes_in_header():
    for typ in (0, 1, 0xFF, 0x80):
        fr = P.encode_frame(typ, b'\x00\xff\x00')
        assert CRx().feed(fr) == [(typ, b'\x00\xff\x00')]


def test_encode_rejects_oversize_and_small_buffer():
    assert c_encode(1, b'x' * (MAX_BODY + 1)) == b''
    with pytest.raises(ValueError):
        P.encode_frame(1, b'x' * (MAX_BODY + 1))
    out = (C.c_uint8 * 4)()
    assert L.at_frame_encode(1, b'abcdef', 6, out, 4) == 0
    assert len(c_encode(1, b'x' * MAX_BODY)) > MAX_BODY


def test_cobs_decode_python_edge():
    assert P.cobs_decode(P.cobs_encode(b'')) == b''
    for n in (253, 254, 255, 256, 508, 509):
        for fill in (0, 0xFF, 1):
            d = bytes([fill]) * n
            assert P.cobs_decode(P.cobs_encode(d)) == d
    with pytest.raises(ValueError):
        P.cobs_decode(b'\x05\x01')


# ---------------------------------------------------------------------------------------- damaged frames
def test_truncated_frames_never_accepted():
    rng = random.Random(3)
    for n in (0, 1, 7, 40, 200, 256):
        fr = P.encode_frame(0x09, rbody(rng, n))
        for cut in range(1, len(fr) - 1):                 # every proper prefix (cut before the terminator)
            rx = CRx()
            assert rx.feed(fr[:cut] + b'\x00') == [], (n, cut)
            assert rx.bad >= 1
            assert rx.feed(P.encode_frame(0x01, b'ok')) == [(0x01, b'ok')]   # and it resynchronises on the very next frame


def test_truncated_frame_swallows_at_most_next_frame_then_recovers():
    fr = P.encode_frame(0x04, b'A' * 30)
    nxt = P.encode_frame(0x01, b'n')
    rx = CRx()
    got = rx.feed(fr[:10] + nxt + nxt + nxt)             # no terminator after the truncated part
    assert got == [(0x01, b'n'), (0x01, b'n')]           # the merged garbage frame is rejected, later ones fine


def test_single_bit_flips_always_detected():
    rng = random.Random(4)
    for n in (0, 1, 5, 36, 254):
        fr = bytearray(P.encode_frame(0x82, rbody(rng, n)))
        for i in range(len(fr) - 1):
            for bit in range(8):
                bad = bytearray(fr)
                bad[i] ^= 1 << bit
                assert CRx().feed(bytes(bad)) == [], (n, i, bit)
                assert P.FrameDecoder().feed(bytes(bad)) == []


def test_random_multi_bit_corruption_detected():
    rng = random.Random(5)
    accepted = 0
    for _ in range(4000):
        n = rng.randrange(0, 60)
        body = rbody(rng, n)
        fr = bytearray(P.encode_frame(0x83, body))
        for _ in range(rng.randrange(2, 6)):
            i = rng.randrange(len(fr) - 1)
            fr[i] ^= 1 << rng.randrange(8)
        got = CRx().feed(bytes(fr))
        if got and got != [(0x83, body)]:
            accepted += 1
    assert accepted == 0


def test_burst_error_up_to_16_bits_detected():
    rng = random.Random(6)
    for _ in range(1500):
        body = rbody(rng, rng.randrange(1, 80))
        fr = bytearray(P.encode_frame(0x02, body))
        i = rng.randrange(len(fr) - 3)
        burst = rng.randrange(1, 0x10000) | 0x8001
        for k in range(16):
            if burst >> k & 1:
                pos = i + k // 8
                if pos < len(fr) - 1:
                    fr[pos] ^= 1 << (k % 8)
        got = CRx().feed(bytes(fr))
        assert got == [] or got == [(0x02, body)]


# ---------------------------------------------------------------------------------------- streams
def test_garbage_between_frames_and_resync():
    rng = random.Random(7)
    rx, dec = CRx(), P.FrameDecoder()
    expect, stream = [], bytearray()
    for i in range(120):
        g = rbody(rng, rng.randrange(0, 50))
        stream += g + b'\x00'                              # garbage is terminated by a delimiter
        body = rbody(rng, rng.randrange(0, 80))
        expect.append((0x10 + i % 5, body))
        stream += P.encode_frame(*expect[-1])
    assert rx.feed(bytes(stream)) == expect
    assert dec.feed(bytes(stream)) == expect
    assert rx.bad > 0 and dec.bad_frames > 0               # the garbage was seen and counted


def test_back_to_back_and_byte_wise_and_random_chunks():
    rng = random.Random(8)
    msgs = [(1 + i % 200, rbody(rng, rng.randrange(0, 257))) for i in range(150)]
    stream = b''.join(P.encode_frame(t, b) for t, b in msgs)
    assert CRx().feed(stream) == msgs
    d = P.FrameDecoder()
    got = []
    for b in stream:
        got += d.feed(bytes([b]))
    assert got == msgs
    d = P.FrameDecoder()
    got, pos = [], 0
    while pos < len(stream):
        k = rng.randrange(1, 40)
        got += d.feed(stream[pos:pos + k])
        pos += k
    assert got == msgs and d.bad_frames == 0


def test_empty_frames_ignored_not_counted():
    rx = CRx()
    assert rx.feed(b'\x00\x00\x00') == []
    assert rx.bad == 0
    assert rx.feed(P.encode_frame(7, b'x')) == [(7, b'x')]


def test_overflow_dropped_then_recovers():
    rx, dec = CRx(), P.FrameDecoder()
    for junk_len in (P.MAX_FRAME, P.MAX_FRAME + 1, 1000, 100000):
        junk = bytes([0x55]) * junk_len
        assert rx.feed(junk + b'\x00') == []
        assert dec.feed(junk + b'\x00') == []
        assert rx.feed(P.encode_frame(3, b'after')) == [(3, b'after')]
        assert dec.feed(P.encode_frame(3, b'after')) == [(3, b'after')]
    assert rx.bad == 4 or rx.bad == 3        # exactly-MAX_FRAME junk is not an overflow but still fails decoding/CRC
    assert dec.bad_frames == rx.bad


def test_overflow_flag_does_not_leak_into_next_frame():
    rx = CRx()
    rx.feed(bytes([9]) * 5000 + b'\x00')
    good = [(0x20, b'\x00' * 256)]
    assert rx.feed(P.encode_frame(*good[0])) == good


def test_max_size_frame_exact_fit():
    body = bytes((i * 7) & 0xFF for i in range(MAX_BODY))
    assert len(P.encode_frame(0x55, body)) <= P.MAX_FRAME + 2
    assert CRx().feed(P.encode_frame(0x55, body)) == [(0x55, body)]


def test_all_zero_wire_bytes_never_inside_frame():
    rng = random.Random(9)
    for _ in range(200):
        fr = P.encode_frame(rng.randrange(256), bytes(rng.choice((0, 255, rng.randrange(256))) for _ in range(rng.randrange(257))))
        assert 0 not in fr[:-1] and fr[-1] == 0


# ---------------------------------------------------------------------------------------- doc / header consistency
def test_message_ids_match_header():
    hdr = open(os.path.join(ROOT, 'firmware', 'core', 'atproto.h')).read()
    ids = {m.group(1): int(m.group(2), 16) for m in re.finditer(r'(AT_(?:CMD|RSP)_\w+)\s*=\s*(0x[0-9A-Fa-f]+)', hdr)}
    errs = {m.group(1): int(m.group(2)) for m in re.finditer(r'(AT_ERR_\w+)\s*=\s*(\d+)', hdr)}
    assert len(ids) >= 20 and len(errs) == 6
    for name, val in ids.items():
        pname = name[3:]                       # CMD_PING / RSP_POSE ...
        assert getattr(P, pname) == val, name
    for name, val in errs.items():
        assert getattr(P, name[3:]) == val, name


def test_doc_tables_match_header():
    doc = open(os.path.join(ROOT, 'docs', 'protocol.md')).read()
    hdr = open(os.path.join(ROOT, 'firmware', 'core', 'atproto.h')).read()
    hdr_ids = {m.group(1): int(m.group(2), 16) for m in re.finditer(r'AT_((?:CMD|RSP)_\w+)\s*=\s*(0x[0-9A-Fa-f]+)', hdr)}
    hdr_errs = {m.group(1): int(m.group(2)) for m in re.finditer(r'AT_ERR_(\w+)\s*=\s*(\d+)', hdr)}
    doc_ids = {}
    for m in re.finditer(r'^\|\s*(0x[0-9A-Fa-f]{2})\s*\|\s*([A-Z_]+)\s*\|\s*([^|]*)\|', doc, re.M):
        doc_ids[int(m.group(1), 16)] = (m.group(2), m.group(3).strip())
    doc_errs = {int(m.group(1)): m.group(2) for m in re.finditer(r'^\|\s*(\d)\s*\|\s*([A-Z_]+)\s*\|', doc, re.M)}
    assert {v: k for k, v in hdr_errs.items()} == doc_errs
    names = {v: k.split('_', 1)[1] for k, v in hdr_ids.items()}
    assert set(names) == set(doc_ids), set(names) ^ set(doc_ids)
    for i, n in names.items():
        assert doc_ids[i][0] == n, (hex(i), n, doc_ids[i])
    # body sizes for the fixed-size device->host messages and commands
    sizes = {'ACK': 1, 'PONG': 12, 'POSE': P.POSE_LEN, 'CONFIG': 40, 'TAG': 36, 'STATUS': P.STATUS_LEN, 'NAK': 2}
    for i, (n, col) in doc_ids.items():
        if i >= 0x80 and n in sizes:
            assert int(col) == sizes[n], (n, col)
    for n, ln in {'SET_CALIB': 36, 'ADD_TAG': 34, 'STREAM': 3, 'SET_SENSOR': 3, 'SET_TRACK': 4, 'SET_AE': 1, 'SET_AUTO_RATIO': 1, 'GET_TAG': 2}.items():
        row = [c for (nm, c) in doc_ids.values() if nm == n][0]
        assert str(ln) in row, (n, row)
