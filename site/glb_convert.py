"""KiCad GLB (kicad-cli pcb export glb) -> parts.json used by the site viewers and the Blender renders.
Every footprint node of the GLB is named by its reference designator, so no position matching is needed.
Output: list of dict(ref, name, col=[r,g,b] (sRGB 0-1), bb=[x0,y0,z0,x1,y1,z1], v=[...], f=[...]) in the STEP frame
(mm, x = KiCad x, y = -KiCad y, z up, z=0 is the bottom of the board).  One entry per (ref, colour).
Usage: py -3.12 glb_convert.py in.glb out.json"""
import sys, json, struct
import numpy as np

def srgb(c): return [(v ** (1 / 2.2)) for v in c]

def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0], [0, 0, 0, 1]])

def load(path):
    d = open(path, 'rb').read()
    jl = struct.unpack('<I', d[12:16])[0]; j = json.loads(d[20:20 + jl])
    bin_ = d[20 + jl + 8:]
    def acc(i):
        a = j['accessors'][i]; bv = j['bufferViews'][a['bufferView']]
        n = {'SCALAR': 1, 'VEC3': 3}[a['type']]; dt = {5126: '<f4', 5125: '<u4', 5123: '<u2'}[a['componentType']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        return np.frombuffer(bin_, dtype=dt, count=a['count'] * n, offset=off).reshape(-1, n) if n > 1 else np.frombuffer(bin_, dtype=dt, count=a['count'], offset=off)
    return j, acc

def convert(path, scale_mm=1000.0):
    j, acc = load(path); nodes = j['nodes']; out = []
    def local(n):
        m = np.eye(4)
        if 'matrix' in n: m = np.array(n['matrix']).reshape(4, 4).T
        else:
            if 'rotation' in n: m = quat_mat(n['rotation']) @ m
            if 'scale' in n: m = np.diag(list(n['scale']) + [1]) @ m
            if 'translation' in n: t = np.eye(4); t[:3, 3] = n['translation']; m = t @ m
        return m
    def walk(i, M, ref):
        n = nodes[i]; M = M @ local(n)
        if ref is None and n.get('name') and 'mesh' not in n and n['name'] != '' and not n['name'].startswith('=>'): ref = n['name']
        if 'mesh' in n:
            for p in j['meshes'][n['mesh']]['primitives']:
                P = acc(p['attributes']['POSITION']).astype(np.float64); F = acc(p['indices']).reshape(-1, 3)
                P = (np.c_[P, np.ones(len(P))] @ M.T)[:, :3] * scale_mm
                # glTF (X, Y=up, Z) -> STEP (x, y, z): x=X, y=-Z, z=Y   (KiCad GLB uses Z = +y_kicad)
                S = np.c_[P[:, 0], -P[:, 2], P[:, 1]]
                mt = j['materials'][p['material']]['pbrMetallicRoughness']['baseColorFactor']
                out.append(dict(ref=ref or 'board', name=n.get('name', ''), col=[round(v, 3) for v in srgb(mt[:3])], alpha=mt[3], S=S, F=F))
        for c in n.get('children', []): walk(c, M, ref)
    walk(j['scenes'][0]['nodes'][0], np.eye(4), None)
    # merge per (ref, colour)
    groups = {}
    for o in out: groups.setdefault((o['ref'], tuple(o['col'])), []).append(o)
    res = []
    for (ref, col), lst in groups.items():
        V = []; Fs = []; off = 0
        for o in lst: V.append(o['S']); Fs.append(o['F'] + off); off += len(o['S'])
        V = np.vstack(V); Fs = np.vstack(Fs)
        res.append(dict(ref=ref, name=ref, col=list(col), bb=[round(float(x), 3) for x in list(V.min(0)) + list(V.max(0))],
                        v=[round(float(c), 3) for c in V.ravel()], f=[int(i) for i in Fs.ravel()]))
    return res

if __name__ == '__main__':
    r = convert(sys.argv[1]); json.dump(r, open(sys.argv[2], 'w'))
    refs = sorted(set(p['ref'] for p in r)); print('groups', len(r), 'refs', len(refs))
