"""ctypes binding of the firmware pose solver (float build = what runs on the MCU, double build = reference)."""
import ctypes as C, os, numpy as np, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import geom
ROOT = geom.ROOT
MAXT, MAXM = 64, 16

def structs(real):
    class Calib(C.Structure): _fields_ = [(n, real) for n in 'fx fy cx cy k1 k2 p1 p2 k3'.split()]
    class Tag(C.Structure): _fields_ = [('id', C.c_uint16), ('size', real), ('pos', real * 3), ('R', real * 9)]
    class Field(C.Structure): _fields_ = [('cal', Calib), ('ntags', C.c_uint16), ('tags', Tag * MAXT)]
    class Meas(C.Structure): _fields_ = [('id', C.c_uint16), ('c', (real * 2) * 4)]
    class Pose(C.Structure): _fields_ = [('R', real * 9), ('t', real * 3), ('rms_px', real), ('ntags', C.c_uint8), ('flags', C.c_uint8)]
    return Calib, Tag, Field, Meas, Pose

class Solver:
    def __init__(self, double=False):
        dll = os.path.join(ROOT, 'firmware', 'tests', 'libatcore_d.dll' if double else 'libatcore.dll')
        if os.name != 'nt':                 # Linux / CI: build the shared object from the firmware sources (the .dll files are Windows builds)
            import subprocess
            dll = os.path.join(ROOT, 'sim', 'libatcore_d.so' if double else 'libatcore.so'); os.makedirs(os.path.dirname(dll), exist_ok=True)
            src = os.path.join(ROOT, 'firmware', 'core', 'atpose.c')
            if not os.path.exists(dll) or os.path.getmtime(dll) < os.path.getmtime(src):
                subprocess.check_call(['gcc', '-O2', '-shared', '-fPIC'] + (['-DAT_REAL=double'] if double else []) + ['-o', dll, src, '-lm'])
        self.lib = C.CDLL(dll)
        real = C.c_double if double else C.c_float
        self.Calib, self.Tag, self.Field, self.Meas, self.Pose = structs(real)
        self.lib.at_solve.argtypes = [C.POINTER(self.Field), C.POINTER(self.Meas), C.c_int, C.POINTER(self.Pose)]
        self.lib.at_solve.restype = C.c_int
        self.field = None

    def set_field(self, tag_map, K=None, dist=None):
        f = self.Field()
        K = geom.K_matrix() if K is None else K
        d = geom.DIST_TRUE if dist is None else dist
        f.cal = self.Calib(K[0, 0], K[1, 1], K[0, 2], K[1, 2], *d)
        for i, (tid, (p, R, s)) in enumerate(tag_map.items()):
            f.tags[i].id = tid; f.tags[i].size = s
            for k in range(3): f.tags[i].pos[k] = p[k]
            for k in range(9): f.tags[i].R[k] = R.reshape(-1)[k]
        f.ntags = len(tag_map)
        self.field = f

    def solve(self, meas):
        """meas: list of (id, 4x2 corners) -> (R_wc, t_wc, rms, ntags, flags) or None"""
        arr = (self.Meas * max(len(meas), 1))()
        for i, (tid, c) in enumerate(meas):
            arr[i].id = tid
            for a in range(4):
                for b in range(2): arr[i].c[a][b] = float(c[a][b])
        out = self.Pose()
        rc = self.lib.at_solve(C.byref(self.field), arr, len(meas), C.byref(out))
        if rc: return None
        return (np.array(out.R[:]).reshape(3, 3), np.array(out.t[:]), out.rms_px, out.ntags, out.flags)
