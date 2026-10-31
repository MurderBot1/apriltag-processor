"""ctypes binding of firmware/core/attpu.c (the TPU algorithm in C) compiled for the PC, plus a few helpers to feed it like the FPGA does."""
import ctypes as C, os, subprocess, shutil, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import geom
ROOT = geom.ROOT
SRC = os.path.join(ROOT, 'firmware', 'core', 'attpu.c')


class Tag(C.Structure):
    _fields_ = [('id', C.c_uint16), ('ham', C.c_uint8), ('rot', C.c_uint8), ('c', C.c_int32 * 8),
                ('label', C.c_uint32), ('area', C.c_uint32), ('frame', C.c_uint32), ('quad_area', C.c_uint32)]


def _gcc():
    g = shutil.which('gcc')
    if g:
        return g
    return r'C:\msys64\mingw64\bin\gcc.exe'


def build(force=False):
    d = os.path.join(ROOT, 'sim'); os.makedirs(d, exist_ok=True)
    dll = os.path.join(d, 'libattpu.dll' if os.name == 'nt' else 'libattpu.so')
    hdr = os.path.join(ROOT, 'firmware', 'core', 'attpu.h')
    codes = os.path.join(ROOT, 'firmware', 'core', 'tag36h11_codes.h')
    if force or not os.path.exists(dll) or os.path.getmtime(dll) < max(os.path.getmtime(p) for p in (SRC, hdr, codes)):
        env = dict(os.environ); gcc = _gcc()
        env['PATH'] = os.path.dirname(gcc) + os.pathsep + env.get('PATH', '')
        subprocess.check_call([gcc, '-O2', '-Wall', '-Wextra', '-shared', '-fPIC', '-o', dll, SRC], env=env)
    return dll


class Attpu:
    def __init__(self):
        dll = build()
        if os.name == 'nt':
            try:
                os.add_dll_directory(os.path.dirname(_gcc()))
            except (AttributeError, OSError):
                pass
        self.lib = L = C.CDLL(dll)
        L.attpu_init.argtypes = []
        L.attpu_run.argtypes = [C.c_void_p, C.c_void_p, C.c_uint, C.c_uint32, C.c_uint, C.POINTER(Tag)]
        L.attpu_run.restype = C.c_int
        L.attpu_divq.argtypes = [C.c_int32, C.c_int32]; L.attpu_divq.restype = C.c_int32
        L.attpu_muls.argtypes = [C.c_int32, C.c_int32, C.c_uint]; L.attpu_muls.restype = C.c_int32
        L.attpu_match.argtypes = [C.c_uint32, C.c_uint32, C.c_uint]; L.attpu_match.restype = C.c_int32
        L.attpu_pack_results.argtypes = [C.POINTER(Tag), C.c_int, C.c_void_p]
        L.attpu_init()

    def run(self, fb_words, cand_words, count, frame_id=1, maxham=2):
        """fb_words: uint32[32000] (40 words per row), cand_words: uint32 list/array (16 per record).  Returns the 512-word result RAM image
        as produced by the old TPU plus the Tag array."""
        fb = np.ascontiguousarray(fb_words, dtype=np.uint32)
        cw = np.zeros(1024, np.uint32); cw[:len(cand_words)] = np.asarray(cand_words, dtype=np.uint64) & 0xFFFFFFFF
        out = (Tag * 31)()
        n = self.lib.attpu_run(fb.ctypes.data, cw.ctypes.data, count, frame_id, maxham, out)
        res = np.zeros(512, np.uint32)
        self.lib.attpu_pack_results(out, n, res.ctypes.data)
        return [int(x) for x in res], n, out


# ---------------------------------------------------------------------------------------------- FPGA frame packet (rtl/mask_stream.v)
MAGIC = 0x4D335441
PKT_WORDS = 4 + 32000 + 4 + 1024
PKT_BYTES = 4 * PKT_WORDS


def parse_packet(words):
    """33032 little-endian words of one packet -> dict(seq, ts, mask (uint32[32000]), cand (uint32[1024]), cand_count, ccl_flags, status, frame_sum,
    max_row_cycles, ok).  `status` bits: 0 CSI frame bad, 1 threshold busy error, 2 FIFO overflow, 3 short mask, 4 labeller timeout."""
    w = np.asarray(words, dtype=np.uint32)
    assert w.size == PKT_WORDS, w.size
    t = w[32004:32008]
    return dict(ok=bool(w[0] == MAGIC and t[3] == (~w[1] & 0xFFFFFFFF)), seq=int(w[1]), ts=int(w[2]) | (int(w[3]) << 32), mask=w[4:32004], cand=w[32008:],
                cand_count=int((t[0] >> 16) & 0xFF), ccl_flags=int((t[0] >> 8) & 15), status=int(t[0] & 0xFF), frame_sum=int(t[1]), max_row_cycles=int(t[2] & 0xFFFF))


def load_packet_hex(path):
    return np.array([int(x, 16) for x in open(path).read().split()], dtype=np.uint32)


_A = None


def detect(pkt, frame_id=None, maxham=2):
    """Run the C tag unit on a parsed packet.  Returns (512-word result image like the old result RAM, number of tags)."""
    global _A
    if _A is None:
        _A = Attpu()
    res, n, _ = _A.run(pkt['mask'], pkt['cand'][:16 * 64], min(pkt['cand_count'], 64), pkt['seq'] if frame_id is None else frame_id, maxham)
    return res, n
