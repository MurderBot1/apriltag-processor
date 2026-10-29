"""Bit-exact golden models of the FPGA blocks (used by the RTL regression + firmware tests).

binarize()   : 2x2 binning -> 8x8-pixel tiles -> 3x3 tile min/max -> per-pixel black mask
components(): 4-connected black components + area / bbox / 8 directional extremes
csi2_*       : CSI-2 packet builder (ECC / CRC16) used by the sensor model in the testbenches
"""
import numpy as np
from scipy import ndimage

W, H = 1280, 800
DIFF_MIN_DEFAULT = 24
ABS_BLACK_DEFAULT = 64
MIN_AREA_DEFAULT = 100
MAX_AREA_DEFAULT = 400000
MIN_DIM_DEFAULT = 10
MAX_CAND = 64
MAX_LABELS = 4096
MAX_RUNS_ROW = 96


# ------------------------------------------------------------------ threshold
def binarize(img, diff_min=DIFF_MIN_DEFAULT, abs_black=ABS_BLACK_DEFAULT):
    p = img.astype(np.int32)
    h, w = p.shape
    b = (p[0::2, 0::2] + p[0::2, 1::2] + p[1::2, 0::2] + p[1::2, 1::2] + 2) >> 2
    th, tw = h // 8, w // 8
    t = b.reshape(th, 4, tw, 4)
    tmin, tmax = t.min(axis=(1, 3)), t.max(axis=(1, 3))
    nmin = ndimage.minimum_filter(tmin, size=3, mode='nearest')
    nmax = ndimage.maximum_filter(tmax, size=3, mode='nearest')
    diff = nmax - nmin
    hi = (diff >= diff_min) & (2 * diff >= nmax)
    thr = (nmin + nmax) >> 1
    hi8 = np.kron(hi, np.ones((8, 8), bool))
    thr8 = np.kron(thr, np.ones((8, 8), np.int32))
    black = np.where(hi8, p <= thr8, p < abs_black)
    return black


def despeckle(mask):
    """3x3 majority (>=4 of 9 incl. centre, zero padding) - matches rtl/despeckle.v"""
    s = ndimage.convolve(mask.astype(np.int32), np.ones((3, 3), np.int32), mode='constant', cval=0)
    return s >= 4


def binarize_clean(img, diff_min=DIFF_MIN_DEFAULT, abs_black=ABS_BLACK_DEFAULT):
    return despeckle(binarize(img, diff_min, abs_black))


# -------------------------------------------------------------------- CCL
def run_scores(x, y):
    return np.array([x, -x, y, -y, x + y, -(x + y), x - y, y - x])


def components(black, min_area=MIN_AREA_DEFAULT, max_area=MAX_AREA_DEFAULT, min_dim=MIN_DIM_DEFAULT,
               reject_border=True):
    """returns list of dict(area, xmin..., scores[8]) for all components passing the HW filter,
    plus the full label image and a list of all components (unfiltered)."""
    lab, n = ndimage.label(black, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    h, w = black.shape
    ys, xs = np.nonzero(lab)
    ls = lab[ys, xs]
    out = {}
    for L in range(1, n + 1):
        pass
    # vectorised per-label reductions
    area = np.bincount(ls, minlength=n + 1)
    comps = []
    order = np.argsort(ls, kind='stable')
    ls_o, xs_o, ys_o = ls[order], xs[order], ys[order]
    bounds = np.searchsorted(ls_o, np.arange(1, n + 2))
    for L in range(1, n + 1):
        a, b = bounds[L - 1], bounds[L]
        x, y = xs_o[a:b], ys_o[a:b]
        sc = np.array([x.max(), -x.min(), y.max(), -y.min(), (x + y).max(), -(x + y).min(),
                       (x - y).max(), (y - x).max()])
        comps.append(dict(label=L, area=int(b - a), scores=sc, x0=int(x.min()), x1=int(x.max()),
                          y0=int(y.min()), y1=int(y.max())))
    keep = []
    for c in comps:
        bw, bh = c['x1'] - c['x0'] + 1, c['y1'] - c['y0'] + 1
        if c['area'] < min_area or c['area'] > max_area or bw < min_dim or bh < min_dim:
            continue
        if reject_border and (c['x0'] == 0 or c['y0'] == 0 or c['x1'] == w - 1 or c['y1'] == h - 1):
            continue
        keep.append(c)
    return keep, lab, comps


def extreme_points(sc):
    """8 scores -> 8 (x,y) points in the geometry of the scores (any pixel attaining the extreme)."""
    return sc


# ----------------------------------------------------------------- CSI-2
def csi2_ecc(di, wc):
    d = di | (wc << 8)
    g = lambda *bits: sum((d >> b) & 1 for b in bits) & 1
    p5 = g(10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23)
    p4 = g(4, 5, 6, 7, 8, 9, 16, 17, 18, 19, 20, 22, 23)
    p3 = g(1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 20, 21, 23)
    p2 = g(0, 2, 3, 5, 6, 9, 11, 12, 15, 18, 20, 21, 22)
    p1 = g(0, 1, 3, 4, 6, 8, 10, 12, 14, 17, 20, 21, 22, 23)
    p0 = g(0, 1, 2, 4, 5, 7, 10, 11, 13, 16, 20, 21, 22, 23)
    return (p5 << 5) | (p4 << 4) | (p3 << 3) | (p2 << 2) | (p1 << 1) | p0


def csi2_crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return c


def csi2_short(di, wc=0):
    return bytes([di, wc & 255, wc >> 8, csi2_ecc(di, wc)])


def csi2_long(di, payload, bad_crc=False):
    wc = len(payload)
    crc = csi2_crc16(payload) ^ (0x5A5A if bad_crc else 0)
    return bytes([di, wc & 255, wc >> 8, csi2_ecc(di, wc)]) + bytes(payload) + bytes([crc & 255, crc >> 8])


def csi2_frame_packets(img, frame_no=0):
    """list of packets (bytes) for one RAW8 frame: FS, 800 lines, FE"""
    pk = [csi2_short(0x00, frame_no)]
    for y in range(img.shape[0]):
        pk.append(csi2_long(0x2A, img[y].tobytes()))
    pk.append(csi2_short(0x01, frame_no))
    return pk


# --------------------------------------------------------- candidate record packing (matches run_ccl.v)
def pack_records(keep, lab):
    """golden components -> list of 16-word RTL-format candidate records (aux taken from first raster pixel
    attaining each extreme; any attaining pixel is equally valid)."""
    words = []
    for c in keep:
        ys, xs = np.nonzero(lab == c['label'])
        sc = [xs, -xs, ys, -ys, xs + ys, -(xs + ys), xs - ys, ys - xs]
        rec = [0] * 16
        rec[0] = c['area']
        for k in range(8):
            i = int(np.argmax(sc[k]))
            x, y = int(xs[i]), int(ys[i])
            aux = y if k in (0, 1) else x
            rec[1 + k] = (aux << 16) | (int(sc[k][i]) & 0xFFFF)
        rec[9] = c['label']
        rec[10] = c['x0'] | (c['x1'] << 16)
        rec[11] = c['y0'] | (c['y1'] << 16)
        words += rec
    return words
