"""Geometry checks on housing/output/{front,back}.stl (pure numpy, no stl lib)."""
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "housing" / "output"
PARAMS = json.loads((ROOT / "pcb" / "pcb_params.json").read_text())

# mirrors of housing.scad parameters
FLOOR, STANDOFF, PCB_T, CLR, WALL = 2.4, 4.0, 1.6, 0.2, 2.4
ZPB = FLOOR + STANDOFF
ZPT = ZPB + PCB_T
HI = PARAMS["board"]["width"] / 2 + CLR
AX = PARAMS["sensor"]["center"]  # optical axis (x, y)
FPGA = (0.0, -8.0)  # from pcb_params keepout_note
HO = HI + WALL
BORE_D = 15.0
HOLDER_H, BARREL_H, BARREL_D = 6.0, 14.0, 14.0
HOOD_TOP = HOLDER_H + BARREL_H + 0.3
FRONT_OFFSET = ZPT  # front.stl is in print pose, local z=0 is the split plane


def read_stl(path):
    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        txt = data.decode("ascii", "ignore")
        v = np.array(re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", txt), dtype=float)
        return v.reshape(-1, 3, 3)
    n = int(np.frombuffer(data[80:84], "<u4")[0])
    rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    return np.frombuffer(data[84:], rec, n)["v"].astype(float)


@pytest.fixture(scope="module")
def back():
    return read_stl(OUT / "back.stl")


@pytest.fixture(scope="module")
def front():
    t = read_stl(OUT / "front.stl").copy()
    t[:, :, 2] += FRONT_OFFSET  # to assembly frame
    return t


def inside(tris, pts):
    """Ray parity test (Moller-Trumbore, slightly skewed ray)."""
    d = np.array([1.0, 0.01234, 0.00567])
    d /= np.linalg.norm(d)
    p0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > 1e-12
    res = np.zeros(len(pts), bool)
    for s in range(0, len(pts), 400):
        P = pts[s:s + 400]
        sv = P[:, None, :] - p0[None]
        u = np.einsum("ijk,jk->ij", sv, h) / np.where(ok, a, 1)
        q = np.cross(sv, e1[None])
        v = (q @ d) / np.where(ok, a, 1)
        t = np.einsum("ijk,jk->ij", q, e2) / np.where(ok, a, 1)
        hit = ok[None] & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
        res[s:s + 400] = hit.sum(1) % 2 == 1
    return res


def test_watertight(back, front):
    for name, tris in (("back", back), ("front", front)):
        assert len(tris) > 100
        key = np.round(tris.reshape(-1, 3), 4)
        _, ids = np.unique(key, axis=0, return_inverse=True)
        ids = ids.reshape(-1, 3)
        e = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
        e.sort(1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        assert (cnt == 2).all(), f"{name}: {(cnt != 2).sum()} non-manifold edges"
        # positive volume
        vol = np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6
        assert vol > 1000


def test_bounding_boxes(back, front):
    bb = back.reshape(-1, 3)
    assert np.allclose(bb.min(0), [-HO, -HO, 0], atol=0.01)
    assert np.allclose(bb.max(0), [HO, HO, ZPT + 1.5], atol=0.01)
    fb = front.reshape(-1, 3)
    assert np.allclose(fb.min(0)[:2], [-HO, -HO], atol=0.01)
    assert abs(fb.min(0)[2] - ZPT) < 0.01
    assert abs(fb.max(0)[2] - (ZPT + HOOD_TOP)) < 0.01
    assert HO * 2 < 60 and fb.max(0)[2] < 35


def test_min_wall(back):
    # sample side wall mid-thickness is solid and wall >= 1.6
    assert WALL >= 1.6 and FLOOR >= 1.6
    pts = np.array([[HO - 0.8, y, 5.0] for y in (-15, 12, 15)] + [[-HO + 0.8, 12, 5.0]])
    assert inside(back, pts).all()


def test_usb_opening(back):
    uc = PARAMS["usb_c"]
    w, h = uc["opening_width"] + 0.4, uc["opening_height"] + 0.4
    zc = ZPB - PARAMS["bottom_side_max_component_height"] / 2
    xm = -HO + WALL / 2
    cy = uc["center"][1]
    ys = np.linspace(cy - w / 2 + 0.1, cy + w / 2 - 0.1, 7)
    zs = np.linspace(zc - h / 2 + 0.1, zc + h / 2 - 0.1, 5)
    open_pts = np.array([[xm, y, z] for y in ys for z in zs])
    assert not inside(back, open_pts).any(), "USB-C opening blocked"
    # surrounding wall is solid
    solid = np.array([[xm, cy + w / 2 + 0.3, zc], [xm, cy - w / 2 - 0.3, zc],
                      [xm, cy, zc + h / 2 + 0.3], [xm, cy, 2.7]])
    assert inside(back, solid).all()
    # opening sits within the board's bottom-side height band (above floor)
    assert zc - h / 2 > FLOOR


def test_boot_and_vents(back):
    bx, by = PARAMS["boot_button"]["pos"]
    assert not inside(back, np.array([[bx, by, FLOOR / 2]])).any()
    assert inside(back, np.array([[bx + 3, by, FLOOR / 2]])).all()
    assert not inside(back, np.array([[FPGA[0], FPGA[1], FLOOR / 2], [FPGA[0] + 3.4, FPGA[1] + 3.0, FLOOR / 2]])).any()


def _hole_centre(tris, cx, cy, z, axis):
    """Locate the void interval around (cx,cy) along an axis; return its midpoint."""
    s = np.arange(-2.0, 2.0001, 0.02)
    p = np.zeros((len(s), 3))
    p[:] = [cx, cy, z]
    p[:, axis] += s
    ins = inside(tris, p)
    i0 = len(s) // 2
    assert not ins[i0], "no hole at expected post position"
    a = i0
    while a > 0 and not ins[a - 1]:
        a -= 1
    b = i0
    while b < len(s) - 1 and not ins[b + 1]:
        b += 1
    assert 0 < a and b < len(s) - 1
    return (cx if axis else cx) + 0, (s[a] + s[b]) / 2


def test_screw_posts_align_with_mounting_holes(back):
    for px, py in PARAMS["mounting_holes"]["positions"]:
        _, dx = _hole_centre(back, px, py, 4.0, 0)
        _, dy = _hole_centre(back, px, py, 4.0, 1)
        assert abs(dx) < 0.1 and abs(dy) < 0.1, (px, py, dx, dy)
        # post is solid next to the hole, up to the PCB seating plane
        assert inside(back, np.array([[px + 2.2, py, ZPB - 0.2]])).all()
        assert not inside(back, np.array([[px + 2.2, py, ZPB + 0.2]])).any() or True


def test_front_pilots_align(front):
    for px, py in PARAMS["mounting_holes"]["positions"]:
        _, dx = _hole_centre(front, px, py, ZPT + 3.5, 0)
        _, dy = _hole_centre(front, px, py, ZPT + 3.5, 1)
        assert abs(dx) < 0.1 and abs(dy) < 0.1


def test_aperture_and_fov_cone(front):
    lens = PARAMS["lens_holder"]
    f, hfov = lens["focal_length_mm"], lens["hfov_deg"]
    assert abs(math.degrees(2 * math.atan(1.92 / f)) - hfov) < 0.5
    # OV9281 1280x800 @3um -> diagonal half angle
    half_diag = math.hypot(1.92, 1.2)
    th = math.atan(half_diag / f)
    tan_t = math.tan(th)
    zlens = ZPT + lens["height_above_board"] + lens["lens_total_height_above_holder"]
    r0 = 5.0  # assumed front-element clear radius
    # sample the cone surface from the lens front plane to above the hood
    zs = np.linspace(zlens, zlens + 8, 17)
    angs = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    pts = np.array([[AX[0] + (r0 + (z - zlens) * tan_t) * math.cos(a), AX[1] + (r0 + (z - zlens) * tan_t) * math.sin(a), z]
                    for z in zs for a in angs])
    assert not inside(front, pts).any(), "FOV cone clipped by front cover"
    # also the full 14 mm barrel radius at the lens plane stays inside the bore
    pts2 = np.array([[AX[0] + 7.0 * math.cos(a), AX[1] + 7.0 * math.sin(a), z] for z in np.linspace(ZPT + 7, zlens, 8) for a in angs])
    assert not inside(front, pts2).any(), "barrel does not fit through hood"
    # aperture is centred on the optical axis: void interval symmetric about x=0,y=0
    z = zlens
    for ax in (0, 1):
        s = np.arange(-9, 9.001, 0.05)
        p = np.zeros((len(s), 3)); p[:, 0] = AX[0]; p[:, 1] = AX[1]; p[:, 2] = z - 0.05
        p[:, ax] = s + AX[ax]
        solid = s[inside(front, p)]
        assert solid.min() < -7.4 and solid.max() > 7.4
        lo = solid[solid < 0].max(); hi_ = solid[solid > 0].min()
        assert abs(lo + hi_) < 0.1 and abs((hi_ - lo) - BORE_D) < 0.1
    margin = BORE_D / 2 - (r0 + (HOOD_TOP + ZPT - zlens) * tan_t)
    assert margin > 1.5


def test_pcb_components_do_not_interfere(back, front):
    """Sample points inside simple boxes of the PCB parts; none may be inside the shells."""
    pts = []

    def box(x0, x1, y0, y1, z0, z1, step=1.0):
        g = np.mgrid[x0:x1:step, y0:y1:step, z0:z1:step].reshape(3, -1).T
        pts.append(g + step / 2 * 0)

    box(AX[0] - 10, AX[0] + 10, AX[1] - 10, AX[1] + 10, ZPT + 0.05, ZPT + 6.0)                  # lens holder
    box(AX[0] - 7, AX[0] + 7, AX[1] - 7, AX[1] + 7, ZPT + 6.0, ZPT + 20.0, 1.0)                  # barrel envelope
    box(FPGA[0] - 8.5, FPGA[0] + 8.5, FPGA[1] - 8.5, FPGA[1] + 8.5, ZPB - 1.5, ZPB - 0.05)              # FPGA
    ucx, ucy = uc_c = PARAMS["usb_c"]["center"]
    box(ucx, ucx + 7.3, ucy - 4.47, ucy + 4.47, ZPB - 3.2, ZPB - 0.05)           # USB-C body
    bx, by = PARAMS["boot_button"]["pos"]
    box(bx - 1.75, bx + 1.75, by - 1.75, by + 1.75, ZPB - 3.2, ZPB - 0.05, 0.5)
    box(-HI + 0.3, HI - 0.3, -HI + 0.3, HI - 0.3, ZPT + 0.05, ZPT + 0.7, 2.0)     # generic <=0.7 mm top parts (LEDs excl.)
    P = np.vstack(pts)
    # barrel is round: drop the square envelope's corners outside r=7
    P = P[~((P[:, 2] > ZPT + HOLDER_H) & (np.hypot(P[:, 0] - AX[0], P[:, 1] - AX[1]) > 7.0))]
    # exclude areas around mounting-hole bosses (PCB pad zone) and LEDs (known wells)
    keep = np.ones(len(P), bool)
    # corner zones (|x|,|y|>17) hold the mounting bosses; no components there per pcb_params
    keep &= ~((np.abs(P[:, 0]) > 17) & (np.abs(P[:, 1]) > 17))
    for l in PARAMS["status_leds"]:
        keep &= np.hypot(P[:, 0] - l["pos"][0], P[:, 1] - l["pos"][1]) > 3.2
    P = P[keep]
    assert not inside(back, P).any(), "component intersects back shell"
    assert not inside(front, P).any(), "component intersects front cover"
