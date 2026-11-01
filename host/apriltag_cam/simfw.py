"""Native firmware (firmware/core compiled for the PC) driven through a fake HAL: fake FPGA register/result memory, fake flash,
collected tx bytes.  Used by the host SimTransport and by the firmware tests."""
import collections
import ctypes as C
import os
import random
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, 'firmware', 'core')
DLL = os.path.join(ROOT, 'firmware', 'tests', 'libatfw.dll' if os.name == 'nt' else 'libatfw.so')
SOURCES = [os.path.join(CORE, f) for f in ('atpose.c', 'atproto.c', 'atapp.c', 'atae.c', 'atratio.c', 'atframe.c', 'attpu.c')] + \
          [os.path.join(ROOT, 'firmware', 'tests', 'atfw_shim.c')]

FPGA_ID = 0x41544731
REG_ID, REG_STATUS, REG_FRAME, REG_I2C, REG_I2C_DATA, REG_THRESH, REG_FRAME_SUM = 0x00, 0x18, 0x1C, 0x40, 0x44, 0x0C, 0x60
REG_TIME_LO, REG_TIME_HI = 0x64, 0x68
PKT_MAGIC = 0x4D335441
PKT_WORDS = 4 + 32000 + 4 + 1024
PKT_BYTES = 4 * PKT_WORDS
SLOT_BYTES = 4096
NBUF = 3                       # AT_NBUF
FRAME_PIXELS = 1024000


def _find_gcc():
    g = shutil.which('gcc')
    if g:
        return g
    for p in (r'C:\msys64\mingw64\bin\gcc.exe',):
        if os.path.exists(p):
            return p
    raise RuntimeError('no native C compiler found')


def build_library(force=False):
    """(Re)build libatfw if missing or older than any source."""
    srcs = SOURCES + [os.path.join(CORE, f) for f in os.listdir(CORE) if f.endswith('.h')]
    if not force and os.path.exists(DLL) and os.path.getmtime(DLL) >= max(os.path.getmtime(s) for s in srcs):
        return DLL
    gcc = _find_gcc()
    env = dict(os.environ)
    env['PATH'] = os.path.dirname(gcc) + os.pathsep + env.get('PATH', '')
    subprocess.check_call([gcc, '-O2', '-Wall', '-Wextra', '-shared', '-o', DLL] + SOURCES + ['-lm'], env=env)
    return DLL


_lib = None


def lib():
    global _lib
    if _lib is None:
        path = build_library()
        if os.name == 'nt':
            try:
                os.add_dll_directory(os.path.dirname(_find_gcc()))
            except (AttributeError, OSError):
                pass
        _lib = L = C.CDLL(path)
        L.atfw_sizeof_app.restype = C.c_size_t
        L.atfw_app_new.restype = C.c_void_p
        L.atfw_app_free.argtypes = [C.c_void_p]
        L.atfw_stats.argtypes = [C.c_void_p, C.POINTER(C.c_uint32)]
        L.atfw_ae_mean.argtypes = [C.c_void_p]
        L.atfw_ae_mean.restype = C.c_float
        for n in ('atfw_rx_max_depth', 'atfw_rx_lost'):
            getattr(L, n).argtypes = [C.c_void_p]
            getattr(L, n).restype = C.c_uint32
        L.atfw_pool_new.argtypes = [C.c_uint]
        L.atfw_pool_new.restype = C.c_void_p
        L.atfw_pool_free.argtypes = [C.c_void_p]
        L.atfw_pool_state.argtypes = [C.c_void_p, C.c_uint]
        L.atfw_pool_state.restype = C.c_uint
        for n in ('at_buf_claim', 'at_buf_acquire'):
            getattr(L, n).argtypes = [C.c_void_p]
            getattr(L, n).restype = C.c_int
        for n in ('at_buf_complete', 'at_buf_abort'):
            getattr(L, n).argtypes = [C.c_void_p, C.c_int]
        L.at_buf_release.argtypes = [C.c_void_p]
        L.at_buf_lost.argtypes = [C.c_void_p]
        L.at_buf_lost.restype = C.c_uint32
        L.at_app_init.argtypes = [C.c_void_p, C.c_void_p]
        L.at_app_rx.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        L.at_app_poll.argtypes = [C.c_void_p]
        L.at_app_poll.restype = C.c_int
        L.at_store_save.argtypes = [C.c_void_p]
        L.at_store_save.restype = C.c_int
        L.at_store_load.argtypes = [C.c_void_p]
        L.at_store_load.restype = C.c_int
        L.at_crc16.argtypes = [C.c_char_p, C.c_size_t]
        L.at_crc16.restype = C.c_uint16
        L.at_frame_encode.argtypes = [C.c_uint8, C.c_char_p, C.c_size_t, C.c_void_p, C.c_size_t]
        L.at_frame_encode.restype = C.c_size_t
        L.at_ae_step.argtypes = [C.c_void_p, C.c_float]
        L.at_ae_step.restype = C.c_int
        L.at_ae_init.argtypes = [C.c_void_p, C.c_uint16, C.c_uint8]
        L.at_rx_init.argtypes = [C.c_void_p]
        L.at_rx_feed.argtypes = [C.c_void_p, C.c_uint8, C.POINTER(C.c_uint8), C.POINTER(C.c_void_p), C.POINTER(C.c_size_t)]
        L.at_rx_feed.restype = C.c_int
    return _lib


# ---------------------------------------------------------------------------------------------- fake flash
class FakeFlash:
    """Two 4 KB slots.  Erase sets 0xFF byte by byte, program ANDs bytes in (flash can only clear bits).
    power_cut_after = N makes the device 'lose power' after N byte-operations (erase byte / program byte); from then on every
    access fails and the contents are frozen.  torn_byte=True leaves the byte in flight half-programmed."""
    def __init__(self):
        self.slots = [bytearray(b'\xFF' * SLOT_BYTES) for _ in range(2)]
        self.power_cut_after = None
        self.ops = 0
        self.dead = False
        self.torn_byte = False
        self.write_corrupt = False
        self.rng = random.Random(1)

    def clone_contents(self):
        f = FakeFlash()
        f.slots = [bytearray(s) for s in self.slots]
        return f

    def read(self, slot, off, n):
        if self.dead or slot < 0 or slot >= 2 or off + n > SLOT_BYTES:
            return None
        return bytes(self.slots[slot][off:off + n])

    def _budget(self, n):
        """How many of the next n byte-operations complete before power is lost."""
        if self.dead:
            return 0
        if self.power_cut_after is None:
            return n
        return max(0, min(n, self.power_cut_after - self.ops))

    def erase(self, slot):
        if self.dead:
            return -1
        k = self._budget(SLOT_BYTES)
        self.slots[slot][:k] = bytes([0xFF]) * k
        self.ops += k
        if k < SLOT_BYTES:
            self.dead = True
            if self.torn_byte:
                self.slots[slot][k] = self.rng.randrange(256)       # cell mid-erase: arbitrary value
            return -1
        return 0

    def write(self, slot, off, data):
        if self.dead or off + len(data) > SLOT_BYTES:
            return -1
        data = bytearray(data)
        if self.write_corrupt and data:
            data[len(data) // 2] ^= 0x01                           # silent bit error (verify must catch it)
        k = self._budget(len(data))
        for i in range(k):
            self.slots[slot][off + i] &= data[i]
        self.ops += k
        if k < len(data):
            self.dead = True
            if self.torn_byte:
                self.slots[slot][off + k] &= (data[k] | self.rng.randrange(256))
            return -1
        return 0


# ---------------------------------------------------------------------------------------------- fake FPGA
def q16(v):
    return int(round(v * 65536.0)) & 0xFFFFFFFF


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def make_packet(seq, ts=0, frame_sum=0, status=0, mask=None, cand=None, count=0, ccl_flags=0, max_row=0):
    """One FPGA frame packet (rtl/mask_stream.v layout).  mask: uint32[32000] or None (all white), cand: uint32 array of 16 * count words."""
    import numpy as np
    w = np.zeros(PKT_WORDS, np.uint32)
    w[0] = PKT_MAGIC; w[1] = seq & 0xFFFFFFFF; w[2] = ts & 0xFFFFFFFF; w[3] = (ts >> 32) & 0xFFFFFFFF
    if mask is not None:
        w[4:32004] = mask
    w[32004] = (status & 0xFF) | ((ccl_flags & 15) << 8) | ((count & 0xFF) << 16)
    w[32005] = frame_sum & 0xFFFFFFFF; w[32006] = max_row & 0xFFFF; w[32007] = ~np.uint32(seq & 0xFFFFFFFF)
    if cand is not None:
        w[32008:32008 + len(cand)] = cand
    return w.tobytes()


class FakeFpga:
    """Register file of rtl/cam_core.v plus the MCU frame bus: a queue of frame packets that the firmware fetches through the HAL.
    publish(tags) queues a packet whose detections are injected (the real tag unit is replaced by the test hook for it); publish_packet() queues
    a real packet (mask + candidates) that the firmware's C tag unit processes.
    STATUS = {frames_sent[31:16], candidates[15:8], init_done[3], stream_busy[2], 0[1], any_frame[0]}."""
    def __init__(self):
        self.regs = {}
        self.queue = collections.deque()      # (packet bytes, injected tags or None)
        self.seq = 0
        self.count = 0
        self.frame_id = 0
        self.init_done = 1
        self.tpu_busy = 0                     # (stream_busy) kept for tests that poke it
        self.i2c_log = []              # (reg, value)
        self.sensor_regs = {}
        self.i2c_busy_polls = 0
        self.frame_sum = 0
        self.time_us = 0               # device clock; tests set it or let time_fn drive it (callable(fpga) -> us)
        self.time_fn = None
        self._time_hi = 0
        self.frame_sum_fn = None       # callable(fpga) -> int, overrides frame_sum
        self.on_sensor_write = None    # callable(fpga, reg) after each I2C write
        self.counters = {0x28: 0x00190008, 0x30: 0, 0x34: 0, 0x38: 0}
        self.fail_reads = 0            # next N register reads fail (return nonzero)
        self.read_log = []
        self._i2c_data = 0
        self.lost = 0                  # packets the receiver dropped (reported through the HAL like the DMA layer does)
        self.max_queue = NBUF          # frame buffers (AT_NBUF in firmware/core/atframe.h): one more packet is lost
        self.inject = {}               # seq -> list of tag records
        self.last_ts = 0

    def status(self):
        return ((self.seq & 0xFFFF) << 16) | ((self.count & 0xFF) << 8) | (self.init_done << 3) | (self.tpu_busy << 2) | (1 if self.seq else 0)

    def _now(self):
        return self.time_fn(self) if self.time_fn else self.time_us

    def publish(self, tags, frame_id=None, status=0, ccl_flags=0):
        """tags: iterable of (id, corners[4][2], ham=0, rot=0) or dicts {id, corners, ham}.  Queues one frame packet whose detections are `tags`."""
        recs = []
        for t in tags:
            if isinstance(t, dict):
                recs.append((t['id'], t['corners'], t.get('ham', 0), t.get('rot', 0)))
            else:
                t = tuple(t)
                recs.append((t[0], t[1], t[2] if len(t) > 2 else 0, t[3] if len(t) > 3 else 0))
        fid = (frame_id if frame_id is not None else self.frame_id + 1) & 0xFFFFFFFF
        self.frame_id = fid
        self.seq = (self.seq + 1) & 0xFFFF
        self.count = len(recs)
        ts = self._now()
        self._enqueue(make_packet(fid, ts, self.frame_sum_fn(self) if self.frame_sum_fn else self.frame_sum, status, count=len(recs), ccl_flags=ccl_flags), recs[:31], fid)

    def publish_packet(self, packet):
        """Queue a complete packet (bytes) built by make_packet() or taken from the RTL simulation; the real C tag unit decodes it."""
        self.seq = (self.seq + 1) & 0xFFFF
        self._enqueue(bytes(packet), None, None)

    def _enqueue(self, pkt, recs, fid):
        if len(self.queue) >= self.max_queue:
            self.lost += 1
            return
        if recs is not None:
            self.inject[fid] = recs
        self.queue.append(pkt)

    def read(self, addr, n):
        if self.fail_reads:
            self.fail_reads -= 1
            return None
        self.read_log.append((addr, n))
        return [self._reg(addr + 4 * i) for i in range(n)]

    def _reg(self, a):
        if a == REG_ID:
            return FPGA_ID
        if a == REG_STATUS:
            return self.status()
        if a == REG_FRAME:
            return self.frame_id
        if a == REG_TIME_LO:
            t = self._now() & 0xFFFFFFFFFFFFFFFF
            self._time_hi = t >> 32
            return t & 0xFFFFFFFF
        if a == REG_TIME_HI:
            return self._time_hi
        if a == REG_FRAME_SUM:
            return (self.frame_sum_fn(self) if self.frame_sum_fn else self.frame_sum) & 0xFFFFFFFF
        if a == REG_I2C_DATA:
            if self.i2c_busy_polls:
                self.i2c_busy_polls -= 1
                return 0x100
            return self._i2c_data & 0xFF
        if a in self.counters:
            return self.counters[a]
        return self.regs.get(a, 0)

    def write(self, addr, value):
        if addr == REG_I2C_DATA:
            self._i2c_data = value & 0xFF
            self.regs[addr] = value
        elif addr == REG_I2C:
            if value & 0x80000000:
                reg = value & 0xFFFF
                self.i2c_log.append((reg, self._i2c_data))
                self.sensor_regs[reg] = self._i2c_data
                if self.on_sensor_write:
                    self.on_sensor_write(self, reg)
            self.regs[addr] = value
        else:
            self.regs[addr] = value & 0xFFFFFFFF
        return 0

    @property
    def sensor_exposure(self):
        r = self.sensor_regs
        return ((r.get(0x3500, 0) << 16) | (r.get(0x3501, 0) << 8) | r.get(0x3502, 0)) >> 4

    @property
    def sensor_gain(self):
        return self.sensor_regs.get(0x3509, 0x10)


# ---------------------------------------------------------------------------------------------- native firmware instance
class HalStruct(C.Structure):
    _fields_ = [('ctx', C.c_void_p)] + [(n, C.c_void_p) for n in
                ('fpga_read', 'fpga_write', 'flash_read', 'flash_erase', 'flash_write', 'tx', 'micros', 'frame_get', 'frame_put', 'detect')]


class FrameBuf(C.Structure):          # at_frame_buf_t
    _fields_ = [('data', C.c_void_p), ('bytes', C.c_size_t), ('lost', C.c_uint32), ('max_depth', C.c_uint32)]


class FrameInfo(C.Structure):         # at_frame_t
    _fields_ = [('seq', C.c_uint32), ('ts', C.c_uint64), ('mask', C.c_void_p), ('cand', C.c_void_p), ('cand_count', C.c_uint32),
                ('ccl_flags', C.c_uint32), ('status', C.c_uint32), ('frame_sum', C.c_uint32), ('max_row_cycles', C.c_uint32)]


class TpuTag(C.Structure):            # attpu_tag_t
    _fields_ = [('id', C.c_uint16), ('ham', C.c_uint8), ('rot', C.c_uint8), ('c', C.c_int32 * 8), ('label', C.c_uint32),
                ('area', C.c_uint32), ('frame', C.c_uint32), ('quad_area', C.c_uint32)]


_FPGA_READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_size_t)
_FPGA_WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint32)
_FLASH_READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p, C.c_size_t)
_FLASH_ERASE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int)
_FLASH_WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p, C.c_size_t)
_TX = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(C.c_uint8), C.c_size_t)
_MICROS = C.CFUNCTYPE(C.c_uint32, C.c_void_p)
_FRAME_GET = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(FrameBuf))
_FRAME_PUT = C.CFUNCTYPE(None, C.c_void_p)
_DETECT = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(FrameInfo), C.POINTER(TpuTag), C.c_uint)

STAT_NAMES = ('solved', 'solve_fail', 'torn_reads', 'tx_msgs', 'frame_id', 'store_seq', 'ae_updates', 'nobs', 'pose_valid',
              'ae_exposure', 'ae_gain', 'ae_enabled', 'streaming', 'ntags', 'divider', 'rx_bad_frames')


class NativeFirmware:
    """One firmware instance (at_app_t) bound to a FakeFpga and FakeFlash.  `boot()` (re)initialises from the flash."""
    def __init__(self, fpga=None, flash=None, micros_step=250):
        self.L = lib()
        self.fpga = fpga or FakeFpga()
        self.flash = flash or FakeFlash()
        self.tx = bytearray()
        self.errors = []
        self.put_log = []
        self._max_depth = 0
        self.micros_step = micros_step
        self._clock = 0
        self.app = None
        self._make_hal()
        self.boot()

    def _make_hal(self):
        def guard(fn, default):
            def w(*a):
                try:
                    return fn(*a)
                except Exception as e:      # never let an exception cross the C boundary
                    self.errors.append(e)
                    return default
            return w

        def fpga_read(ctx, addr, words, n):
            r = self.fpga.read(addr, n)
            if r is None:
                return -1
            for i, v in enumerate(r):
                words[i] = v
            return 0

        def fpga_write(ctx, addr, value):
            return self.fpga.write(addr, value)

        def flash_read(ctx, slot, off, buf, n):
            d = self.flash.read(slot, off, n)
            if d is None:
                return -1
            C.memmove(buf, d, n)
            return 0

        def flash_erase(ctx, slot):
            return self.flash.erase(slot)

        def flash_write(ctx, slot, off, buf, n):
            return self.flash.write(slot, off, C.string_at(buf, n))

        def tx(ctx, data, n):
            self.tx += C.string_at(data, n)

        def micros(ctx):
            self._clock = (self._clock + self.micros_step) & 0xFFFFFFFF
            return self._clock

        def frame_get(ctx, b):
            b[0].lost = self.fpga.lost
            self._max_depth = max(self._max_depth, len(self.fpga.queue))
            b[0].max_depth = self._max_depth
            if not self.fpga.queue:
                return 0
            pkt = self.fpga.queue[0]
            self._pktbuf = C.create_string_buffer(pkt, len(pkt))       # keeps the memory alive until frame_put
            b[0].data = C.addressof(self._pktbuf); b[0].bytes = len(pkt)
            return 1

        def frame_put(ctx):
            self.put_log.append(len(self.tx))              # tx bytes sent so far: shows whether the buffer was released before the pose message
            if self.fpga.queue:
                self.fpga.queue.popleft()

        def detect(ctx, f, out, mx):
            recs = self.fpga.inject.pop(f[0].seq, None)
            if recs is None:
                return -1
            for i, (tid, cs, ham, rot) in enumerate(recs[:mx]):
                o = out[i]
                o.id = tid; o.ham = ham; o.rot = rot
                for c in range(4):
                    o.c[2 * c] = _s32(q16(cs[c][0])); o.c[2 * c + 1] = _s32(q16(cs[c][1]))
                o.label = i + 1; o.area = 1000; o.frame = f[0].seq; o.quad_area = 2000
            return min(len(recs), mx)

        self._cb = [_FPGA_READ(guard(fpga_read, -1)), _FPGA_WRITE(guard(fpga_write, -1)), _FLASH_READ(guard(flash_read, -1)),
                    _FLASH_ERASE(guard(flash_erase, -1)), _FLASH_WRITE(guard(flash_write, -1)), _TX(guard(tx, None)),
                    _MICROS(guard(micros, 0)), _FRAME_GET(guard(frame_get, 0)), _FRAME_PUT(guard(frame_put, None)),
                    _DETECT(guard(detect, -1))]
        self.hal = HalStruct(None, *[C.cast(c, C.c_void_p).value for c in self._cb])

    def boot(self):
        """Power-cycle the MCU: new firmware state, config re-loaded from flash.  FPGA and flash keep their state."""
        if self.app:
            self.L.atfw_app_free(self.app)
        self.app = self.L.atfw_app_new()
        self.L.at_app_init(self.app, C.byref(self.hal))
        self._raise()
        self.tx.clear()

    def close(self):
        if getattr(self, 'app', None):
            self.L.atfw_app_free(self.app)
            self.app = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def rx(self, data):
        data = bytes(data)
        self.L.at_app_rx(self.app, data, len(data))
        self._raise()

    def poll(self):
        r = self.L.at_app_poll(self.app)
        self._raise()
        return r

    def take_tx(self):
        d = bytes(self.tx)
        self.tx.clear()
        return d

    def stats(self):
        arr = (C.c_uint32 * 16)()
        self.L.atfw_stats(self.app, arr)
        return dict(zip(STAT_NAMES, arr))

    @property
    def rx_stats(self):
        """(packets lost reported by the receiver, most packets ever waiting or in processing)"""
        return self.L.atfw_rx_lost(self.app), self.L.atfw_rx_max_depth(self.app)

    def ae_mean(self):
        return self.L.atfw_ae_mean(self.app)

    def store_save(self):
        r = self.L.at_store_save(self.app)
        self._raise()
        return r

    def _raise(self):
        if self.errors:
            e = self.errors[0]
            self.errors.clear()
            raise e
