"""Blender helper for render_part_thumbs.py (do not run by hand):
  blender -b -P render/_thumbs_bl.py -- <work_dir> <out_dir> <key,key,...|all> [--spp N] [--res N]
Builds every part from (a) the KiCad STEP meshes + face colours dumped by _thumbs_fc.py (work/thumbs/<key>.json) or
(b) a parametric model for the things the KiCad library does not have; renders it on a transparent background with a
soft contact-shadow catcher, consistent camera angle, 3-light studio rig, auto-framed.
Custom models from render/models/<key>.(obj|glb|stl) (e.g. real OV9281 / M12 models from another agent) win over the
parametric fall-backs when present."""
import bpy, bmesh, sys, os, json, math
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

argv = sys.argv[sys.argv.index('--') + 1:]
WORK, OUT, KEYS = argv[0], argv[1], argv[2]
def opt(n, d): return argv[argv.index(n) + 1] if n in argv else d
SPP = int(opt('--spp', 96)); RES = int(opt('--res', 512))
MODELS = os.path.join(os.path.dirname(WORK), 'models')
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------ materials
_mc = {}
def mat(name, base, rough=0.4, metal=0.0, **kw):
    if name in _mc: return _mc[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1); b.inputs['Roughness'].default_value = rough; b.inputs['Metallic'].default_value = metal
    for k, v in kw.items():
        try: b.inputs[k.replace('_', ' ')].default_value = v
        except Exception: pass
    _mc[name] = m; return m

def M(n):
    return {
        'black':  lambda: mat('black', (0.018, 0.018, 0.02), 0.34, 0, **{'Coat_Weight': 0.15, 'Coat_Roughness': 0.2}),
        'dgrey':  lambda: mat('dgrey', (0.05, 0.05, 0.055), 0.45),
        'silver': lambda: mat('silver', (0.36, 0.37, 0.40), 0.4, 1.0),
        'steel':  lambda: mat('steel', (0.30, 0.31, 0.34), 0.42, 1.0),
        'gold':   lambda: mat('gold', (1.0, 0.72, 0.30), 0.26, 1.0),
        'brass':  lambda: mat('brass', (0.86, 0.60, 0.22), 0.30, 1.0),
        'tan':    lambda: mat('tan', (0.62, 0.45, 0.28), 0.5),
        'ledred': lambda: mat('ledred', (0.9, 0.05, 0.04), 0.25, 0, **{'Transmission_Weight': 0.35, 'Emission_Color': (1, 0.1, 0.05, 1), 'Emission_Strength': 0.6}),
        'white':  lambda: mat('white', (0.85, 0.85, 0.82), 0.6),
        'cream':  lambda: mat('cream', (0.89, 0.88, 0.80), 0.5),
        'green':  lambda: mat('green', (0.03, 0.30, 0.12), 0.4, 0, **{'Coat_Weight': 0.3}),
        'glass':  lambda: mat('glass', (0.2, 0.3, 0.5), 0.05, 0.0, **{'Coat_Weight': 1.0, 'Coat_Roughness': 0.02}),
        'sensor': lambda: mat('sensor', (0.10, 0.07, 0.28), 0.12, 0.3, **{'Coat_Weight': 1.0, 'Coat_Roughness': 0.03}),
        'kraft':  lambda: mat('kraft', (0.55, 0.40, 0.25), 0.8),
        'pla':    lambda: mat('pla', (0.025, 0.025, 0.028), 0.5, 0, **{'Sheen_Weight': 0.3}),
    }[n]()

def classify(rgb, key):
    r, g, b = rgb; lum = 0.3 * r + 0.59 * g + 0.11 * b
    if key.startswith('c0') and abs(r - 0.38) < .05 and abs(g - .27) < .05: return 'tan'
    if key == 'led0603' and lum > 0.85: return 'ledred'
    if key == 'xtal' and lum < 0.2: return 'steel'
    if key in ('l0603', 'l1008') and lum < 0.3: return 'dgrey'
    if lum < 0.2: return 'black'
    if r > 0.8 and b < 0.6 and r - b > 0.2: return 'gold'
    if lum > 0.8 and (r - b) < 0.15: return 'silver'
    if lum > 0.45: return 'steel'
    return 'dgrey'

# ------------------------------------------------------------------ geometry helpers
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _mc.clear()
    return bpy.context.scene

def link(o):
    bpy.context.scene.collection.objects.link(o); return o

def mesh_obj(name, verts, faces, mats=None, midx=None, smooth=True, angle=35):
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
    o = bpy.data.objects.new(name, me); link(o)
    for m in (mats or []): me.materials.append(m)
    if midx:
        for p, i in zip(me.polygons, midx): p.material_index = i
    if smooth:
        bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4); bm.to_mesh(me); bm.free()
        for p in me.polygons: p.use_smooth = True
        try: bpy.context.view_layer.objects.active = o; o.select_set(True); bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))
        except Exception: pass
        o.select_set(False)
    return o

def box(name, size, loc, m, bevel=0.0, rot=None):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts: v.co.x *= size[0]; v.co.y *= size[1]; v.co.z *= size[2]
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); link(o); o.location = loc; me.materials.append(m)
    if rot: o.rotation_euler = rot
    if bevel:
        b = o.modifiers.new('bv', 'BEVEL'); b.width = bevel; b.segments = 3; b.limit_method = 'ANGLE'
    for p in me.polygons: p.use_smooth = True
    return o

def revolve(name, prof, m, segs=64, loc=(0, 0, 0), smooth=True, angle=40):
    """prof: [(r, z), ...] polyline revolved around Z."""
    verts, faces = [], []
    n = len(prof)
    for s in range(segs):
        a = 2 * math.pi * s / segs
        for r, z in prof: verts.append((r * math.cos(a), r * math.sin(a), z))
    for s in range(segs):
        s2 = (s + 1) % segs
        for i in range(n - 1):
            a, b, c, d = s * n + i, s * n + i + 1, s2 * n + i + 1, s2 * n + i
            faces.append((a, d, c, b) if False else (a, b, c, d))
    o = mesh_obj(name, verts, faces, [m], smooth=smooth, angle=angle); o.location = loc
    bm = bmesh.new(); bm.from_mesh(o.data); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(o.data); bm.free()
    return o

def cyl(name, r, h, loc, m, segs=48, bevel=0.0):
    o = revolve(name, [(0, 0), (r, 0), (r, h), (0, h)], m, segs, loc)
    if bevel:
        b = o.modifiers.new('bv', 'BEVEL'); b.width = bevel; b.segments = 3; b.limit_method = 'ANGLE'
    return o

def label(text, top_z, center, size, m=None, rot=0.0):
    cu = bpy.data.curves.new('lbl', 'FONT'); cu.body = text; cu.size = size; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'; cu.extrude = size * 0.01; cu.space_line = 0.95
    o = bpy.data.objects.new('lbl', cu); link(o); o.location = (center[0], center[1], top_z + size * 0.02); o.rotation_euler = (0, 0, rot)
    cu.materials.append(m or mat('mark', (0.72, 0.72, 0.7), 0.55)); return o

def top_and_center():
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for o in bpy.context.scene.objects:
        if o.type != 'MESH': continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c); mn = Vector(map(min, mn, w)); mx = Vector(map(max, mx, w))
    return mn, mx

# ------------------------------------------------------------------ STEP-derived parts
def from_json(key, mapkey=None, text=None, tsize=None):
    data = json.load(open(os.path.join(WORK, 'thumbs', key + '.json')))
    mapkey = mapkey or key
    for si, s in enumerate(data):
        verts, faces, midx, mats = [], [], [], []
        for fd in s['faces']:
            n = fd['rgb'] and classify(fd['rgb'], mapkey) or 'steel'
            m = M(n)
            if m not in mats: mats.append(m)
            mi = mats.index(m); base = len(verts); v = fd['v']
            for i in range(0, len(v), 3): verts.append((v[i], v[i + 1], v[i + 2]))
            f = fd['f']
            for i in range(0, len(f), 3): faces.append((base + f[i], base + f[i + 1], base + f[i + 2])); midx.append(mi)
        mesh_obj('%s_%d' % (key, si), verts, faces, mats, midx, True, 30)
    if text:
        mn, mx = top_and_center()
        size = tsize or min(mx.x - mn.x, mx.y - mn.y) * 0.16
        label(text, mx.z, ((mn.x + mx.x) / 2, (mn.y + mx.y) / 2), size)

# ------------------------------------------------------------------ parametric parts
def build_bga():       # Lattice ECP5 caBGA-381 17x17 (no KiCad 3D model for this footprint)
    box('sub', (17, 17, 1.0), (0, 0, 0.5), M('dgrey'), 0.15)
    box('lid', (16.4, 16.4, 0.45), (0, 0, 1.2), M('black'), 0.25)
    box('lid2', (16.6, 16.6, 0.12), (0, 0, 1.0), M('black'), 0.04)
    label('LATTICE\nLFE5U-85F\n8BG381C\nECP5', 1.43, (0, 0.2), 1.5)
    cyl('dot', 0.45, 0.02, (-6.8, -6.8, 1.43), M('white'), 24)
    # solder-ball row visible along the underside edge
    for i in range(20):
        for j in (0, 19):
            for (x, y) in ((-7.6 + i * 0.8, -7.6 + j * 0.8), (-7.6 + j * 0.8, -7.6 + i * 0.8)):
                bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.25, location=(x, y, -0.18))
                o = bpy.context.object; o.scale.z = 0.8; o.data.materials.append(M('silver'))
                for p in o.data.polygons: p.use_smooth = True

def build_osc():       # 24 MHz 3.2x2.5 CMOS oscillator, 4-pad
    box('body', (3.2, 2.5, 0.85), (0, 0, 0.5), M('black'), 0.06)
    box('lid', (3.0, 2.3, 0.1), (0, 0, 0.97), M('steel'), 0.03)
    for sx in (-1, 1):
        for sy in (-1, 1): box('pad', (0.9, 0.7, 0.08), (sx * 1.15, sy * 0.85, 0.06), M('gold'))
    cyl('dot', 0.11, 0.02, (-1.2, -0.85, 1.03), M('white'), 16)
    label('24.000', 1.03, (0.15, 0), 0.4)

def build_ov9281():    # bare CSP image sensor die (placeholder look: silicon die + cover glass + ball grid)
    box('si', (3.9, 3.2, 0.65), (0, 0, 0.45), M('dgrey'), 0.04)
    box('glass', (3.5, 2.8, 0.45), (0, 0, 1.0), M('glass'), 0.03)
    box('active', (2.7, 1.7, 0.02), (0, 0, 1.235), M('sensor'))
    for i in range(7):
        for j in range(6):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=0.11, location=(-1.5 + i * 0.5, -1.25 + j * 0.5, 0.0))
            bpy.context.object.data.materials.append(M('silver'))

def build_holder():    # CLA021-LCP M12 lens holder 17x17 body, 7.4 mm tall, screw ears at 20 mm spacing
    box('plate', (17, 17, 2.6), (0, 0, 1.3), M('black'), 0.5)
    box('ears', (23, 6, 2.6), (0, 0, 1.3), M('black'), 0.5)
    ring = [(0, 2.6), (6.6, 2.6), (6.6, 6.4), (6.2, 6.8), (5.4, 6.8)]
    revolve('barrel', [(5.0, 0), (6.9, 0), (6.9, 4.4), (6.5, 4.9), (5.6, 4.9), (5.6, 4.9)], M('black'), 72, (0, 0, 2.5))
    revolve('bore', [(5.6, 4.9), (5.2, 4.7), (5.2, 0)], M('dgrey'), 72, (0, 0, 2.5))
    for sx in (-1, 1):
        revolve('hole', [(0.85, 2.62), (0.85, 0.0)], M('dgrey'), 24, (sx * 10.0, 0, 0))
        revolve('holering', [(0.85, 2.62), (1.5, 2.62)], M('dgrey'), 24, (sx * 10.0, 0, 0))

def build_lens():      # M12 lens (representative, CIL023 f=2.2 mm class) (barrel + glass front element + lock ring)
    revolve('thread', [(5.7, 0), (6.0, 0.0), (6.0, 9.0), (5.7, 9.0)], M('steel'), 72, (0, 0, 0))
    prof = []
    for i in range(18): prof += [(5.85, 0.4 + i * 0.5), (6.0, 0.4 + i * 0.5 + 0.25)]
    revolve('thr2', prof, M('black'), 72, (0, 0, 0))
    revolve('lock', [(5.5, 4.2), (7.4, 4.2), (7.4, 6.4), (5.5, 6.4)], M('black'), 8, (0, 0, 0), smooth=False)
    revolve('body', [(0, 9), (5.2, 9), (5.2, 17), (4.4, 18), (0, 18)], M('black'), 72, (0, 0, 0))
    revolve('rim', [(2.6, 18.0), (4.4, 18.0), (4.4, 18.05), (2.6, 18.05)], M('dgrey'), 48)
    revolve('front', [(0, 18.5), (1.0, 18.45), (2.0, 18.2), (2.6, 17.7), (2.6, 17.0), (0, 17.0)], M('glass'), 48)
    revolve('ring2', [(2.6, 17.0), (3.0, 17.0), (3.0, 18.4), (2.6, 18.4)], M('steel'), 48)

def build_screw():     # M2 x 10 stainless pan head, cross recess, thread rings
    prof = [(0, 10.0)]
    prof += [(1.0, 10.0), (1.0, 0.4), (0.7, 0.0), (0, 0.0)][::-1][::-1]
    th = [(0, 0.0), (0.72, 0.0), (0.98, 0.35)]
    z = 0.35
    while z < 9.6:
        th += [(0.86, z + 0.16), (1.0, z + 0.32)]; z += 0.32
    th += [(1.0, 10.0)]
    revolve('shank', th, M('steel'), 40, (0, 0, 0.0))
    revolve('head', [(0, 10.0), (1.0, 10.0), (1.6, 10.2), (2.0, 10.8), (1.9, 11.5), (1.4, 11.9), (0.8, 12.0), (0, 12.0)], M('steel'), 56)
    box('slot1', (2.4, 0.4, 0.55), (0, 0, 11.85), M('black')); box('slot2', (0.4, 2.4, 0.55), (0, 0, 11.85), M('black'))

def build_insert():    # M2 brass heat-set insert OD3.2 x 4
    prof = [(1.0, 0.0), (1.45, 0.0), (1.6, 0.25)]
    z = 0.25
    while z < 3.5:
        prof += [(1.42, z + 0.2), (1.6, z + 0.4)]; z += 0.4
    prof += [(1.7, 3.55), (1.7, 4.0), (1.0, 4.0)]
    revolve('insert', prof, M('brass'), 48)
    revolve('bore', [(1.0, 4.0), (1.0, 0.0)], M('dgrey'), 32)
    box('x', (0.1, 0.1, 0.1), (0, 0, 0), M('dgrey'))

def build_filament():  # 1 kg 1.75 mm filament spool, black filament on kraft flanges
    revolve('f1', [(26, 0), (100, 0), (100, 2.5), (26, 2.5)], M('kraft'), 96, (0, 0, 0))
    revolve('f2', [(26, 0), (100, 0), (100, 2.5), (26, 2.5)], M('kraft'), 96, (0, 0, 55))
    revolve('hub', [(26, 0), (26, 57.5), (30, 57.5), (30, 0)], M('kraft'), 64)
    prof = []
    for i in range(30):
        z = 2.5 + i * (50 / 30.0)
        prof += [(78, z), (80.0, z + 0.9), (78, z + 1.7)]
    prof = [(32, 2.5)] + [(78, 2.5)] + prof + [(78, 52.5), (32, 52.5)]
    revolve('coil', prof, M('pla'), 96, (0, 0, 0), True, 30)
    # a few strands hanging loose from the coil
    bpy.ops.mesh.primitive_torus_add(major_radius=60, minor_radius=1.0, major_segments=64, minor_segments=8, location=(0, 0, 53.5)); bpy.context.object.data.materials.append(M('pla'))

def build_pcb():       # bare 48x48x1.6 board with the real routed top copper as texture
    o = box('board', (48, 48, 1.6), (0, 0, 0.8), M('green'), 0.2)
    tex = os.path.join(os.path.dirname(WORK), 'out', 'pcb_layers', 'pcb_top_8192.png')
    if os.path.exists(tex):
        top = box('top', (47.9, 47.9, 0.02), (0, 0, 1.61), mat('pcbtex', (1, 1, 1), 0.38), 0)
        m = top.data.materials[0]; nt = m.node_tree; b = nt.nodes['Principled BSDF']
        t = nt.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(tex); t.interpolation = 'Smart'
        nt.links.new(t.outputs['Color'], b.inputs['Base Color'])
        # unwrap: map object XY -> UV
        tc = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping')
        mp.inputs['Location'].default_value = (0.5, 0.5, 0); mp.inputs['Scale'].default_value = (1 / 47.9, 1 / 47.9, 1)
        nt.links.new(tc.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], t.inputs['Vector'])

BUILDERS = {
    'ecp5': build_bga, 'osc': build_osc, 'ov9281': build_ov9281, 'holder': build_holder, 'lens': build_lens,
    'screw': build_screw, 'insert': build_insert, 'filament': build_filament, 'pcb': build_pcb,
}
# key -> (json key, text) for STEP-derived
STEP_PARTS = {
    'rp2350': ('qfn60', 'RP2350\nA  2543', None), 'ecp5': ('ecp5', 'LATTICE\nLFE5U-85F\n8BG381C\nECP5', 1.5), 'osc': ('osc', '24.000', 0.4),
    'ov9281': ('ov9281', None, None), 'holder': ('m12', None, None), 'flash': ('wson8', 'W25Q128\nJVIQ', None),
    'tlv62569': ('sot235', 'TLV\n62569', 0.5), 'tlv75525': ('sot235', 'TLV\n75525', 0.5), 'tlv75518': ('sot235', 'TLV\n75518', 0.5),
    'tlv75528': ('sot235', 'TLV\n75528', 0.5), 'tlv75512': ('sot235', 'TLV\n75512', 0.5), 'usblc6': ('sot236', 'USBLC6\n-2SC6', 0.5),
    'xtal': ('xtal', None, None), 'usbc': ('usbc_hro', None, None), 'hdr': ('hdr', None, None), 'sw': ('sw', None, None), 'led': ('led0603', None, None),
    'c0402': ('c0402', None, None), 'c0603': ('c0603', None, None), 'c0805': ('c0805', None, None), 'r0402': ('r0402', None, None),
    'l0603': ('l0603', None, None), 'l1008': ('l1008', None, None),
}
ALL = list(dict.fromkeys(list(STEP_PARTS) + list(BUILDERS)))

# ------------------------------------------------------------------ scene
def studio(sc, key, mn, mx):
    # normalise: move bbox centre to origin, scale radius to 1, rest on z=0
    root = bpy.data.objects.new('root', None); link(root)
    objs = [o for o in sc.objects if o is not root]
    c = (mn + mx) / 2; r = max((mx - mn).length / 2, 1e-3)
    for o in objs: o.parent = root
    s = 1.0 / r
    root.scale = (s, s, s); root.location = (-c.x * s, -c.y * s, -mn.z * s)
    bpy.context.view_layer.update()
    height = (mx.z - mn.z) * s
    # shadow catcher floor
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0)); fl = bpy.context.object; fl.is_shadow_catcher = True
    # world: soft neutral
    w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
    bg = w.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (0.9, 0.92, 0.95, 1); bg.inputs['Strength'].default_value = 0.65
    def area(name, loc, size, power, col=(1, 1, 1)):
        d = bpy.data.lights.new(name, 'AREA'); d.energy = power; d.size = size; d.color = col
        o = bpy.data.objects.new(name, d); link(o); o.location = loc
        t = o.constraints.new('TRACK_TO'); t.target = tgt; t.track_axis = 'TRACK_NEGATIVE_Z'; t.up_axis = 'UP_Y'
    tgt = bpy.data.objects.new('tgt', None); link(tgt); tgt.location = (0, 0, height / 2)
    area('key', (-4.5, -3.5, 6.0), 5.0, 900, (1.0, 0.97, 0.93))
    area('fill', (5.5, -2.0, 3.0), 6.0, 260, (0.9, 0.95, 1.0))
    area('rim', (1.0, 6.0, 4.0), 4.0, 420)
    area('top', (0, 0, 8.0), 6.0, 300)
    # camera: fixed angle, auto-framed
    cd = bpy.data.cameras.new('cam'); cd.lens = 85; cd.sensor_width = 36
    cam = bpy.data.objects.new('cam', cd); link(cam); sc.camera = cam
    az, el = math.radians(-38), math.radians(30)
    d = 9.0
    def place(dist, shx=0, shy=0):
        cam.location = (tgt.location.x + dist * math.cos(el) * math.sin(az) * -1, tgt.location.y - dist * math.cos(el) * math.cos(az), tgt.location.z + dist * math.sin(el))
        t = cam.constraints.get('t') or cam.constraints.new('TRACK_TO'); t.name = 't'; t.target = tgt; t.track_axis = 'TRACK_NEGATIVE_Z'; t.up_axis = 'UP_Y'
        cd.shift_x, cd.shift_y = shx, shy
        bpy.context.view_layer.update()
    pts = []
    for o in objs:
        if o.type in ('MESH', 'CURVE', 'FONT'):
            for cc in o.bound_box: pts.append(o.matrix_world @ Vector(cc))
    shx = shy = 0.0; dist = d
    for _ in range(6):
        place(dist, shx, shy)
        xs, ys = [], []
        for p in pts:
            v = world_to_camera_view(sc, cam, p); xs.append(v.x); ys.append(v.y)
        w_, h_ = max(xs) - min(xs), max(ys) - min(ys)
        ext = max(w_, h_); fill = 0.74
        dist *= max(0.2, ext / fill) ** 0.9 if ext > 0 else 1
        shx += ((min(xs) + max(xs)) / 2 - 0.5) * 0.9; shy += ((min(ys) + max(ys)) / 2 - 0.5) * 0.9 - 0.0
    place(dist, shx, shy)

def render(key):
    sc = reset()
    if key in STEP_PARTS and os.path.exists(os.path.join(WORK, 'thumbs', STEP_PARTS[key][0] + '.json')):
        jk, txt, ts = STEP_PARTS[key]; from_json(jk, jk, txt, ts)
        if key == 'led': pass
    else:
        BUILDERS[key]()
    custom = [os.path.join(MODELS, key + e) for e in ('.glb', '.obj', '.stl') if os.path.exists(os.path.join(MODELS, key + e))]
    if custom:
        for o in list(sc.objects): bpy.data.objects.remove(o)
        p = custom[0]
        if p.endswith('.glb'): bpy.ops.import_scene.gltf(filepath=p)
        elif p.endswith('.obj'): bpy.ops.wm.obj_import(filepath=p)
        else: bpy.ops.wm.stl_import(filepath=p)
    bpy.context.view_layer.update()
    sc.render.resolution_x = sc.render.resolution_y = RES
    mn, mx = top_and_center()
    studio(sc, key, mn, mx)
    sc.render.engine = 'CYCLES'; cy = sc.cycles
    cy.samples = SPP; cy.use_denoising = True; cy.denoiser = 'OPENIMAGEDENOISE'; cy.max_bounces = 8; cy.sample_clamp_indirect = 3.0
    dev = os.environ.get('RENDER_DEVICE', 'CPU'); cy.device = 'CPU'
    if dev != 'CPU':
        try:
            p = bpy.context.preferences.addons['cycles'].preferences; p.compute_device_type = dev; p.get_devices()
            for d in p.devices: d.use = d.type != 'CPU'
            cy.device = 'GPU'
        except Exception as e: print('GPU setup failed, CPU:', e)
    sc.render.resolution_x = sc.render.resolution_y = RES; sc.render.film_transparent = True
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'
    try: sc.view_settings.view_transform = 'Khronos PBR Neutral'
    except Exception: sc.view_settings.view_transform = 'Standard'
    sc.render.filepath = os.path.join(OUT, key + '.png')
    bpy.ops.render.render(write_still=True)
    print('RENDERED', key)

for k in (ALL if KEYS == 'all' else KEYS.split(',')):
    try: render(k)
    except Exception:
        import traceback; traceback.print_exc(); print('FAILED', k)
