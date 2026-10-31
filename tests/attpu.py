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
