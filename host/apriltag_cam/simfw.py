"""Native firmware (firmware/core compiled for the PC) driven through a fake HAL: fake FPGA register/result memory, fake flash,
collected tx bytes.  Used by the host SimTransport and by the firmware tests."""
import ctypes as C
import os
import random
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, 'firmware', 'core')
DLL = os.path.join(ROOT, 'firmware', 'tests', 'libatfw.dll' if os.name == 'nt' else 'libatfw.so')
SOURCES = [os.path.join(CORE, f) for f in ('atpose.c', 'atproto.c', 'atapp.c', 'atae.c')] + \
          [os.path.join(ROOT, 'firmware', 'tests', 'atfw_shim.c')]

FPGA_ID = 0x41544731
REG_ID, REG_STATUS, REG_FRAME, REG_I2C, REG_I2C_DATA, REG_THRESH, REG_FRAME_SUM = 0x00, 0x18, 0x1C, 0x40, 0x44, 0x0C, 0x60
REG_TIME_LO, REG_TIME_HI, REG_FT0 = 0x64, 0x68, 0x6C
BANK0, BANK1 = 0x1000, 0x2000
SLOT_BYTES = 4096
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


class FakeFpga:
    """Register file + two result banks with the exact layout of rtl/cam_core.v.
    STATUS = {seq[31:16], tag_count[15:8], init_done[3], tpu_busy[2], res_bank[1], res_valid[0]}."""
    def __init__(self):
        self.regs = {}
        self.banks = [[0] * (16 + 16 * 31) for _ in range(2)]
        self.seq = 0
        self.res_bank = 0
        self.res_valid = 0
        self.count = 0
        self.frame_id = 0
        self.init_done = 1
        self.tpu_busy = 0
        self.i2c_log = []              # (reg, value)
        self.sensor_regs = {}
        self.i2c_busy_polls = 0
        self.frame_sum = 0
        self.time_us = 0               # device clock; tests set it or let time_fn drive it (callable(fpga) -> us)
        self.time_fn = None
        self.ft = [0, 0]               # frame start timestamp per capture bank
        self._time_hi = 0
        self.frame_sum_fn = None       # callable(fpga) -> int, overrides frame_sum
        self.on_sensor_write = None    # callable(fpga, reg) after each I2C write
        self.counters = {0x28: 0x00190008, 0x30: 0, 0x34: 0, 0x38: 0}
        self.torn_hook = None          # callable(fpga) invoked once after the next result-bank read
        self.torn_always = None        # callable(fpga) invoked after every result-bank read
        self.fail_reads = 0            # next N reads fail (return nonzero)
        self.read_log = []
        self._i2c_data = 0

    def status(self):
        return ((self.seq & 0xFFFF) << 16) | ((self.count & 0xFF) << 8) | (self.init_done << 3) | (self.tpu_busy << 2) | \
               (self.res_bank << 1) | self.res_valid

    def publish(self, tags, frame_id=None):
        """tags: iterable of (id, corners[4][2], ham=0, rot=0) or dicts {id, corners, ham}.  Writes the inactive bank, then flips."""
        recs = []
        for t in tags:
            if isinstance(t, dict):
                recs.append((t['id'], t['corners'], t.get('ham', 0), t.get('rot', 0)))
            else:
                t = tuple(t)
                recs.append((t[0], t[1], t[2] if len(t) > 2 else 0, t[3] if len(t) > 3 else 0))
        bank = (self.res_bank ^ 1) if self.res_valid else 0
        fid = (frame_id if frame_id is not None else self.frame_id + 1) & 0xFFFFFFFF
        w = [0] * (16 + 16 * 31)
        recs = recs[:31]
        w[0] = len(recs)
        for i, (tid, cs, ham, rot) in enumerate(recs):
            base = 16 + 16 * i
            w[base] = 0x80000000 | (ham & 63) << 12 | (rot & 3) << 10 | (tid & 0x3FF)
            for c in range(4):
                w[base + 1 + 2 * c] = q16(cs[c][0])
                w[base + 2 + 2 * c] = q16(cs[c][1])
            w[base + 9] = i + 1
            w[base + 10] = 1000
            w[base + 11] = fid
        self.banks[bank] = w
        self.frame_id = fid
        self.seq = (self.seq + 1) & 0xFFFF
        self.res_bank = bank
        self.ft[bank] = self.time_fn(self) if self.time_fn else self.time_us
        self.res_valid = 1
        self.count = len(recs)

    def read(self, addr, n):
        if self.fail_reads:
            self.fail_reads -= 1
            return None
        self.read_log.append((addr, n))
        out = []
        in_bank = False
        for i in range(n):
            a = addr + 4 * i
            if BANK0 <= a < BANK0 + 0x1000:
                out.append(self.banks[0][(a - BANK0) // 4] if (a - BANK0) // 4 < len(self.banks[0]) else 0)
                in_bank = True
            elif BANK1 <= a < BANK1 + 0x1000:
                out.append(self.banks[1][(a - BANK1) // 4] if (a - BANK1) // 4 < len(self.banks[1]) else 0)
                in_bank = True
            else:
                out.append(self._reg(a))
        if in_bank:
            if self.torn_hook:
                h, self.torn_hook = self.torn_hook, None
                h(self)
            if self.torn_always:
                self.torn_always(self)
        return out

    def _reg(self, a):
        if a == REG_ID:
            return FPGA_ID
        if a == REG_STATUS:
            return self.status()
        if a == REG_FRAME:
            return self.frame_id
        if a == REG_TIME_LO:
            t = (self.time_fn(self) if self.time_fn else self.time_us) & 0xFFFFFFFFFFFFFFFF
            self._time_hi = t >> 32
            return t & 0xFFFFFFFF
        if a == REG_TIME_HI:
            return self._time_hi
        if REG_FT0 <= a < REG_FT0 + 16:
            i = (a - REG_FT0) // 8
            return (self.ft[i] >> (32 * (((a - REG_FT0) // 4) & 1))) & 0xFFFFFFFF
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
                ('fpga_read', 'fpga_write', 'flash_read', 'flash_erase', 'flash_write', 'tx', 'micros')]


_FPGA_READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_size_t)
_FPGA_WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint32)
_FLASH_READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p, C.c_size_t)
_FLASH_ERASE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int)
_FLASH_WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_uint32, C.c_void_p, C.c_size_t)
_TX = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(C.c_uint8), C.c_size_t)
_MICROS = C.CFUNCTYPE(C.c_uint32, C.c_void_p)

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

        self._cb = [_FPGA_READ(guard(fpga_read, -1)), _FPGA_WRITE(guard(fpga_write, -1)), _FLASH_READ(guard(flash_read, -1)),
                    _FLASH_ERASE(guard(flash_erase, -1)), _FLASH_WRITE(guard(flash_write, -1)), _TX(guard(tx, None)),
                    _MICROS(guard(micros, 0))]
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
