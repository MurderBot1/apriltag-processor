"""Frame buffer scheduling of the A3 firmware: the buffer pool (firmware/core/atframe.c, the code the RP2350 receiver uses), buffer release
order in at_app_poll, drop counting, and a cross-check of the C pool against the drop model of tools/frame_budget.py."""
import ctypes as C
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwutil import Dev, P, simfw      # noqa: E402
import frame_budget as fb             # noqa: E402
import test_fw_app as ta              # noqa: E402

FREE, FILLING, READY, BUSY = 0, 1, 2, 3


class PoolStruct(C.Structure):         # at_bufpool_t (firmware/core/atframe.h)
    _fields_ = [('n', C.c_uint8), ('state', C.c_uint8 * 4), ('held', C.c_int8), ('order', C.c_uint32 * 4), ('arrivals', C.c_uint32),
                ('lost_nobuf', C.c_uint32), ('lost_abort', C.c_uint32), ('received', C.c_uint32), ('max_depth', C.c_uint32)]


class Pool:
    """the C at_bufpool_t"""
    def __init__(self, n):
        self.L = simfw.lib()
        self.p = self.L.atfw_pool_new(n)

    def __del__(self):
        self.L.atfw_pool_free(self.p)

    @property
    def s(self):
        return PoolStruct.from_address(self.p)

    def states(self):
        return list(self.s.state)[:self.s.n]

    def claim(self): return self.L.at_buf_claim(self.p)
    def complete(self, i): self.L.at_buf_complete(self.p, i)
    def abort(self, i): self.L.at_buf_abort(self.p, i)
    def acquire(self): return self.L.at_buf_acquire(self.p)
    def release(self): self.L.at_buf_release(self.p)
    def lost(self): return self.L.at_buf_lost(self.p)


def test_buffer_count_is_three_and_fits_sram():
    assert simfw.NBUF == 3
    assert simfw.PKT_BYTES == 132128
    assert 3 * simfw.PKT_BYTES == 396384
    assert 3 * simfw.PKT_BYTES < 400 * 1024          # leaves > 100 KB of the 512 KB striped SRAM for tables, app state and stacks


def test_pool_fill_hold_release_order():
    p = Pool(3)
    a, b, c = p.claim(), p.claim(), p.claim()
    assert (a, b, c) == (0, 1, 2) and p.claim() == -1
    assert p.acquire() == -1                          # nothing complete yet
    p.complete(b); p.complete(a)                      # arrival order: b then a
    assert p.states() == [READY, READY, FILLING]
    assert p.acquire() == b                           # oldest packet first, not lowest index
    assert p.acquire() == -1                          # one buffer held at a time
    p.release()
    assert p.acquire() == a
    p.release()
    assert p.acquire() == -1 and p.states() == [FREE, FREE, FILLING]


def test_pool_drop_counting():
    p = Pool(3)
    ids = [p.claim() for _ in range(3)]
    assert p.claim() == -1
    p.complete(-1)                                    # a packet found no buffer: sunk and counted
    assert p.lost() == 1 and p.s.lost_nobuf == 1
    for i in ids:
        p.complete(i)
    assert p.s.received == 3 and p.s.max_depth == 3
    j = p.acquire(); p.release()
    k = p.claim()
    assert k == j
    p.abort(k)                                        # resync: the buffer is free again, one more loss
    assert p.states()[k] == FREE and p.lost() == 2 and p.s.lost_abort == 1
    p.abort(-1)                                       # resync while the sink was active
    assert p.lost() == 3


def test_pool_busy_buffer_is_not_reused():
    p = Pool(2)
    a = p.claim(); p.complete(a)
    assert p.acquire() == a
    b = p.claim(); p.complete(b)
    assert p.claim() == -1                            # a is held, b is ready: nothing to fill
    p.release()
    assert p.claim() == a


def drive_pool(design, nbuf, tpu, pose):
    """drive the C pool with the timing of tools/frame_budget.py (one core); returns the number of packets lost"""
    p = Pool(nbuf)
    T, S, R = fb.T, fb.S, fb.R
    nframes = max(2000, 20 * len(tpu))
    events = sorted([(k * T + S, 0, k) for k in range(nframes)] + [(k * T + R, 1, k) for k in range(nframes)])
    early = design in ('single_early', 'pipe')
    queue = []                                        # (ready time, tpu, pose) of the complete packets, in arrival order
    busy_until = 0.0
    release_at = None
    filling = -1
    lost = 0

    def advance(now):
        nonlocal busy_until, release_at
        while True:
            if release_at is not None and release_at <= now:
                p.release(); release_at = None
            if release_at is None and queue:
                t0 = max(busy_until, queue[0][0])
                if t0 <= now:
                    _, a, pz = queue.pop(0)
                    assert p.acquire() >= 0
                    busy_until = t0 + (a if design == 'pipe' else a + pz)
                    release_at = t0 + (a if early else a + pz)
                    continue
            break

    for t, kind, k in events:
        advance(t)
        if kind == 0:
            filling = p.claim()
            lost += filling < 0
        else:
            p.complete(filling)                       # filling < 0: sunk packet
            if filling >= 0:
                queue.append((t, tpu[k % len(tpu)], pose[k % len(pose)]))
    return lost + 0


STREAMS = {
    'light': ([1.6] * 10, [1.8] * 10),
    'one_slow': ([1.6] * 9 + [9.3], [1.8] * 9 + [3.6]),
    'two_slow': ([1.6] * 8 + [9.3, 9.3], [1.8] * 8 + [3.6, 3.6]),
    'overload': ([12.0] * 10, [2.0] * 10),
}


@pytest.mark.parametrize('design', ['single', 'single_early', 'pipe'])
@pytest.mark.parametrize('nbuf', [2, 3])
@pytest.mark.parametrize('stream', sorted(STREAMS))
def test_c_pool_matches_drop_model(stream, nbuf, design):
    """the C buffer pool, driven with the same timing, loses exactly as many packets as the model says"""
    tpu, pose = STREAMS[stream]
    lost = fb.run_design(design, tpu, pose, nbuf)[1]
    assert drive_pool(design, nbuf, tpu, pose) == lost


def test_model_three_buffers_beat_two_and_early_release_helps():
    tpu, pose = STREAMS['one_slow']
    assert fb.run_design('single', tpu, pose, 2)[1] > 0
    assert fb.run_design('single', tpu, pose, 3)[1] == 0
    assert fb.run_design('single_early', *STREAMS['two_slow'], 3)[1] == 0     # the chosen design
    assert fb.run_design('single_early', *STREAMS['overload'], 3)[1] > 0      # 12 ms per frame is beyond any buffering


def test_model_real_dataset_numbers():
    """headline numbers of results/frame_budget.md (ESTIMATES from the emulated Cortex-M33, not measurements)"""
    d = json.load(open(os.path.join(fb.ROOT, 'results', 'tpu_c_m33_cycles.json')))
    pz = json.load(open(os.path.join(fb.ROOT, 'results', 'pose_m33_cycles.json')))
    lab = next(k for k in pz if k.startswith('float'))
    pm = {r['name']: r['ms'] for r in pz[lab]}
    for model, expect in (('nominal', 0), ('pessimistic', 20)):                 # of 2000 frames, chosen design: 3 buffers, early release
        tpu = [r['cycles'][model] / (d['mhz'] * 1000.0) for r in d['rows']]
        pose = [pm[r['name']][model] if r['tags'] else 0.0 for r in d['rows']]
        assert fb.run_design('single_early', tpu, pose, 3)[1] == expect
        assert fb.run_design('pipe', tpu, pose, 3)[1] == 0
    nominal = [r['cycles']['nominal'] / (d['mhz'] * 1000.0) for r in d['rows']]
    pose = [pm[r['name']]['nominal'] if r['tags'] else 0.0 for r in d['rows']]
    assert fb.run_design('single', nominal, pose, 2)[1] == 60                   # the first design: 2 buffers, 3 %


def test_buffer_is_released_before_the_pose_message():
    """at_app_poll gives the frame buffer back right after the tag unit, i.e. before the pose solve and the POSE message"""
    import struct
    dev = Dev()
    dev.set_config(ta.CAL, ta.TMAP)
    dev.ok(P.CMD_STREAM, struct.pack('<BH', 1, 1))                              # stream every pose
    dev.drain()
    dev.fw.put_log.clear()
    ta.push(dev, ta.rtl_tags('normal_004'))
    assert dev.fw.stats()['solved'] == 1
    assert dev.fw.put_log == [0]                                                # nothing was sent yet when the buffer went back
    assert len(dev.fw.tx) > 0                                                   # the POSE message followed


def test_drops_are_counted_and_depth_is_reported():
    dev = Dev()
    dev.set_config(ta.CAL, ta.TMAP)
    for k in range(5):
        dev.fpga.publish(ta.rtl_tags('normal_004'), frame_id=100 + k)
    assert dev.fpga.lost == 2
    while dev.fw.poll():
        pass
    lost, depth = dev.fw.rx_stats
    assert lost == 2 and depth == 3
    st = P.decode_status(dev.rsp(P.CMD_GET_STATUS, b'', P.RSP_STATUS))
    assert st.frames_dropped == 2 and st.frames_processed == 3
