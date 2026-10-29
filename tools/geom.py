"""Shared geometry / camera / tag-map helpers (single source of truth for tests).

Conventions
-----------
* World: right handed, Z up.
* Tag frame: x right, y up, z out of the printed face (as seen by a viewer).
  Corner order everywhere (GT, firmware, host): TL, TR, BR, BL as seen from the front.
* Camera frame: OpenCV (x right, y down, z forward).
* Pixel coords: OpenCV convention, centre of the top-left pixel is (0,0).
* Pose of camera is reported as camera->world (R_wc, t_wc): p_w = R_wc p_c + t_wc.
"""
import json, math, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1280, 800
HFOV_DEG = 90.0
FX = FY = (W / 2.0) / math.tan(math.radians(HFOV_DEG / 2))   # 640 px
CX, CY = W / 2.0 - 0.5, H / 2.0 - 0.5                           # 639.5, 399.5
TAG_SIZE = 0.1651                                               # 6.5in (FRC)

# Lens distortion used for the test set (OpenCV k1 k2 p1 p2 k3) - plausible M12 90deg lens
DIST_TRUE = np.array([-0.18, 0.045, 0.0004, -0.0003, 0.0])


def K_matrix(fx=FX, fy=FY, cx=CX, cy=CY):
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]])


def quat_to_R(q):
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def R_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        q = [0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s]
    else:
        s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    return q / np.linalg.norm(q) * (1 if q[0] >= 0 else -1)


def rot_angle_deg(Ra, Rb):
    c = (np.trace(Ra.T @ Rb) - 1) / 2
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def tag_corners_local(size=TAG_SIZE):
    h = size / 2
    return np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]])  # TL TR BR BL


# ---------------------------------------------------------------- tag map
def _wall(xs, zs):
    # wall at y=0 whose printed face looks toward +Y
    R = np.array([[-1, 0, 0], [0, 0, 1], [0, 1, 0]], float)  # columns = tag x,y,z in world
    return [(np.array([x, 0.0, z]), R) for z in zs for x in xs]


def default_tag_map():
    """12 tags: 8 on the back wall (y=0), 2 on a side wall (x=-2.5), 2 on the floor."""
    tags = []
    tid = 0
    for pos, R in _wall([-1.2, -0.4, 0.4, 1.2], [1.6, 0.8]):
        tags.append((tid, pos, R)); tid += 1
    Rs = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)  # side wall at x=-2.5, face toward +X
    # tag x = +Y? viewer at +x looking -x, up z, right = (-x)x(z) = +y  -> x_tag=+Y, y_tag=+Z, z_tag=+X
    Rs = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float)
    for pos in ([-2.5, 1.0, 1.2], [-2.5, 2.0, 0.9]):
        tags.append((tid, np.array(pos), Rs)); tid += 1
    Rf = np.eye(3)  # floor tag: x=+X, y=+Y, z=+Z (face up)
    for pos in ([0.0, 1.5, 0.0], [-1.0, 2.5, 0.0]):
        tags.append((tid, np.array(pos), Rf)); tid += 1
    # use ids spread over the 36h11 family so decoding is not trivially low ids
    ids = [3, 17, 42, 58, 77, 101, 133, 202, 250, 311, 404, 515]
    return [(ids[i], p, R) for i, (_, p, R) in enumerate(tags)]


def tag_map_json(tags=None, size=TAG_SIZE):
    tags = tags if tags is not None else default_tag_map()
    return {
        "family": "tag36h11",
        "tags": [{"id": int(i), "size": size, "position": [float(v) for v in p],
                  "quat_wxyz": [float(v) for v in R_to_quat(R)]} for i, p, R in tags]}


def load_tag_map(path=None):
    path = path or os.path.join(ROOT, "config", "tag_map.json")
    with open(path) as f:
        j = json.load(f)
    out = {}
    for t in j["tags"]:
        out[t["id"]] = (np.array(t["position"], float), quat_to_R(t["quat_wxyz"]), t.get("size", TAG_SIZE))
    return out


def tag_corners_world(tmap, tid):
    p, R, s = tmap[tid]
    return (R @ tag_corners_local(s).T).T + p


# --------------------------------------------------------------- projection
def project(pts_w, R_wc, t_wc, K=None, dist=None):
    """world points -> pixels using camera->world pose; dist = OpenCV (k1,k2,p1,p2,k3)."""
    K = K_matrix() if K is None else K
    pc = (R_wc.T @ (np.asarray(pts_w) - t_wc).T).T
    z = pc[:, 2]
    x, y = pc[:, 0] / z, pc[:, 1] / z
    if dist is not None:
        k1, k2, p1, p2, k3 = dist
        r2 = x * x + y * y
        rad = 1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
        xd = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        yd = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        x, y = xd, yd
    return np.stack([K[0, 0] * x + K[0, 2], K[1, 1] * y + K[1, 2]], 1), z


def look_at(eye, target, up=(0, 0, 1)):
    """camera->world rotation (OpenCV axes) for a camera at eye looking at target."""
    f = np.asarray(target, float) - np.asarray(eye, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, up); r /= np.linalg.norm(r)
    d = np.cross(f, r)
    return np.stack([r, d, f], 1)


def roll(R, deg):
    a = math.radians(deg)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return R @ Rz
