"""Photoreal-ish Blender (Cycles) renders of the AprilTag camera hardware.

Run (headless):  blender.exe -b -P render/render_hardware.py -- <shot> [--spp N] [--out DIR] [--res WxH]
  shot = hero | exploded | pcb_top | pcb_bottom | section | turntable | all (all stills)

Inputs (read-only):  housing/output/front.stl, back.stl   (printable parts)
                     render/work/parts.json                (PCB STEP -> meshes, from FreeCAD: render/run_all.py / site/fc_convert.py)
                     render/work/tex_{top,bottom}_*.png    (PCB textures built from the kicad-cli layer export: make_pcb_textures.py)
Frame: board centre at the origin, +Z toward the lens, z=0 = outside bottom of the back shell (housing.scad).
Modelling is in mm; objects are scaled 0.001 so lights/cameras use metres and normal wattages.
Every footprint carries a REAL 3D model (KiCad 10 official library, or the dimensioned parametric models in render/models);
render/work/parts.json is made from the full-assembly GLB (render/out/apriltag_cam_full.glb, kicad-cli) by site/glb_convert.py, one entry
per (reference designator, colour) with the model's own colours.  The board textures contain only copper/mask/silk that exist
in the layout (the routed board: all copper tracks/vias are in the textures; nothing is drawn that is not in the file).
"""
import bpy, bmesh, sys, os, json, math, re, time
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, 'work')
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
SHOT = argv[0] if argv else 'hero'
def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
SPP = int(opt('--spp', 128)); OUT = opt('--out', os.path.join(HERE, 'out'))
RES = [int(v) for v in opt('--res', '1920x1080').split('x')]
os.makedirs(OUT, exist_ok=True)
MM = 0.001
LK = float(opt('--lk', 0.08))
PCB_DZ = 6.5            # STEP z=0 (board bottom) -> assembled z (board top lands on the split plane z=8.0)
AXIS = (0.0, 9.0)       # lens / sensor axis (pcb_params.json sensor.center)
ZS = 8.0                # split plane

# ------------------------------------------------------------------ helpers
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
COLL = sc.collection

def mat(name, base=(0.5, 0.5, 0.5), rough=0.5, metal=0.0, **kw):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1)
    b.inputs['Roughness'].default_value = rough; b.inputs['Metallic'].default_value = metal
    for k, v in kw.items(): b.inputs[k.replace('_', ' ')].default_value = v
    return m

def pla_mat(name, col, rough=0.55):
    """Matte printed plastic: faint layer lines (0.2 mm) + micro noise via bump."""
    m = mat(name, col, rough)
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    tc = nt.nodes.new('ShaderNodeTexCoord')
    w = nt.nodes.new('ShaderNodeTexWave'); w.wave_type = 'BANDS'; w.bands_direction = 'Z'; w.wave_profile = 'SIN'
    w.inputs['Scale'].default_value = 5.0; w.inputs['Distortion'].default_value = 0.4; w.inputs['Detail'].default_value = 0
    n = nt.nodes.new('ShaderNodeTexNoise'); n.inputs['Scale'].default_value = 60; n.inputs['Detail'].default_value = 4
    mix = nt.nodes.new('ShaderNodeMath'); mix.operation = 'ADD'
    nt.links.new(tc.outputs['Object'], w.inputs['Vector']); nt.links.new(tc.outputs['Object'], n.inputs['Vector'])
    nt.links.new(w.outputs['Fac'], mix.inputs[0]); nt.links.new(n.outputs['Fac'], mix.inputs[1])
    bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.07; bump.inputs['Distance'].default_value = 0.05
    nt.links.new(mix.outputs['Value'], bump.inputs['Height']); nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m

def emit_mat(name, col, strength, alpha=1.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    e = nt.nodes.new('ShaderNodeEmission'); e.inputs['Color'].default_value = (*col, 1); e.inputs['Strength'].default_value = strength
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    if alpha < 1:
        t = nt.nodes.new('ShaderNodeBsdfTransparent'); mx = nt.nodes.new('ShaderNodeMixShader'); mx.inputs['Fac'].default_value = alpha
        nt.links.new(t.outputs[0], mx.inputs[1]); nt.links.new(e.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs['Surface'])
    else:
        nt.links.new(e.outputs[0], out.inputs['Surface'])
    return m

def tex_pcb_mat(side):
    m = bpy.data.materials.new('pcb_' + side); m.use_nodes = True; nt = m.node_tree; b = nt.nodes['Principled BSDF']
    def img(kind, cs):
        n = nt.nodes.new('ShaderNodeTexImage'); n.image = bpy.data.images.load(os.path.join(WORK, 'tex_%s_%s.png' % (side, kind)))
        n.image.colorspace_settings.name = cs; n.extension = 'EXTEND'; n.interpolation = 'Cubic'; return n
    c = img('color', 'sRGB'); r = img('rough', 'Non-Color'); mt = img('metal', 'Non-Color'); bu = img('bump', 'Non-Color')
    nt.links.new(c.outputs['Color'], b.inputs['Base Color']); nt.links.new(r.outputs['Color'], b.inputs['Roughness'])
    nt.links.new(mt.outputs['Color'], b.inputs['Metallic'])
    bp = nt.nodes.new('ShaderNodeBump'); bp.inputs['Strength'].default_value = 0.5; bp.inputs['Distance'].default_value = 0.02
    nt.links.new(bu.outputs['Color'], bp.inputs['Height']); nt.links.new(bp.outputs['Normal'], b.inputs['Normal'])
    b.inputs['Coat Weight'].default_value = 0.25; b.inputs['Coat Roughness'].default_value = 0.15   # glossy soldermask
    return m

def glass_mat(name, tint=(0.9, 1.0, 0.95), coat=None):
    m = mat(name, tint, 0.0, 0.0, IOR=1.52, Transmission_Weight=1.0)
    return m

def add_obj(name, verts, faces, material=None, smooth=False, mat_idx=None):
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
    ob = bpy.data.objects.new(name, me); COLL.objects.link(ob)
    if material is not None:
        for mm_ in (material if isinstance(material, (list, tuple)) else [material]): me.materials.append(mm_)
    if mat_idx is not None: me.polygons.foreach_set('material_index', mat_idx)
    if smooth: me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    ob.scale = (MM, MM, MM)
    return ob

def box(name, c, size, material, bevel=0.0):
    cx, cy, cz = c; sx, sy, sz = [s / 2 for s in size]
    v = [(cx + a * sx, cy + b * sy, cz + d * sz) for a in (-1, 1) for b in (-1, 1) for d in (-1, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    ob = add_obj(name, v, f, material)
    if bevel > 0:
        md = ob.modifiers.new('bev', 'BEVEL'); md.width = bevel / MM * MM; md.segments = 3; md.limit_method = 'ANGLE'
    return ob

def lathe(name, prof, material, axis=AXIS, seg=96, a0=0.0, a1=2 * math.pi, closed=True, smooth=True):
    """Solid/shell of revolution about the vertical axis at `axis`. prof = [(r, z), ...] (closed polygon if closed)."""
    n = len(prof); full = abs((a1 - a0) - 2 * math.pi) < 1e-6
    ns = seg if full else seg + 1
    verts = []
    for i in range(ns):
        a = a0 + (a1 - a0) * i / seg
        ca, sa = math.cos(a), math.sin(a)
        for r, z in prof: verts.append((axis[0] + r * ca, axis[1] + r * sa, z))
    faces = []
    m = n if closed else n - 1
    for i in range(seg if full else seg):
        i2 = (i + 1) % ns
        for j in range(m):
            j2 = (j + 1) % n
            faces.append((i * n + j, i2 * n + j, i2 * n + j2, i * n + j2))
    return add_obj(name, verts, faces, material, smooth=smooth)

def lens_prof(R, zc, t, c1, c2, n=14):
    """biconvex-ish element: front surface sag c1, back surface sag c2 (mm), centre thickness t, centre z zc."""
    top = [(R * k / n, zc + t / 2 + c1 * (1 - (k / n) ** 2)) for k in range(n + 1)]
    bot = [(R * k / n, zc - t / 2 - c2 * (1 - (k / n) ** 2)) for k in range(n, -1, -1)]
    return top + bot

# ------------------------------------------------------------------ materials
M = dict(
    pla_front=pla_mat('pla_front', (0.0035, 0.0035, 0.004), 0.62),
    pla_back=pla_mat('pla_back', (0.0035, 0.0035, 0.004), 0.64),
    anod=mat('anodised', (0.035, 0.036, 0.042), 0.2, 1.0),
    anod_rough=mat('anod_grip', (0.010, 0.010, 0.012), 0.55, 0.85),
    holder=mat('holder', (0.025, 0.025, 0.028), 0.45, 0.2),
    glass=glass_mat('glass'), glass2=glass_mat('glass2', (0.8, 0.95, 1.0)),
    flock=mat('flock', (0.004, 0.004, 0.004), 0.95),
    ic=mat('ic', (0.012, 0.012, 0.014), 0.38, 0.0, Coat_Weight=0.1),
    cap=mat('cap', (0.40, 0.26, 0.11), 0.45),
    res=mat('res', (0.015, 0.015, 0.016), 0.5),
    ind=mat('ind', (0.10, 0.10, 0.11), 0.4, 0.3),
    led=mat('led', (0.85, 0.78, 0.55), 0.25),
    header=mat('header', (0.012, 0.012, 0.012), 0.5),
    metal=mat('metal', (0.62, 0.63, 0.65), 0.28, 1.0),
    sw_body=mat('switch', (0.55, 0.56, 0.58), 0.3, 1.0),
    black=mat('black', (0.004, 0.004, 0.004), 0.7),
    edge=mat('fr4_edge', (0.30, 0.31, 0.16), 0.6),
    white=mat('sensor_white', (0.6, 0.6, 0.58), 0.4),
)
M['top'] = tex_pcb_mat('top'); M['bottom'] = tex_pcb_mat('bottom')

# ------------------------------------------------------------------ geometry builders
def build_housing():
    out = {}
    for nme in ('front', 'back'):
        bpy.ops.wm.stl_import(filepath=os.path.join(ROOT, 'housing', 'output', nme + '.stl'))
        ob = bpy.context.selected_objects[0]; ob.name = nme
        ob.data.materials.append(M['pla_' + nme]); ob.scale = (MM, MM, MM)
        out[nme] = ob
        bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True); bpy.context.view_layer.objects.active = ob
        try: bpy.ops.object.shade_auto_smooth(use_auto_smooth=True, angle=math.radians(35))
        except Exception as e: print('auto smooth failed', e)
    return out

PARTS = None
def load_parts():
    global PARTS
    if PARTS is None: PARTS = json.load(open(os.path.join(WORK, 'parts.json')))
    return PARTS

def cat_of_ref(ref):
    m = re.match(r'[A-Za-z]+', ref); p = m.group(0).upper() if m else ''
    return {'C': 'cap', 'R': 'res', 'L': 'ind', 'FB': 'ind', 'D': 'led', 'U': 'ic', 'J': 'conn', 'SW': 'sw', 'Y': 'ic', 'TP': 'tp', 'LH': 'lens'}.get(p, 'ic')

_MC = {}
def mat_col(col, cat, tag=''):
    """Material from the model's own sRGB colour (STEP/GLB), roughness / metalness by what the colour looks like."""
    k = (tuple(round(c, 2) for c in col), cat, tag)
    if k in _MC: return _MC[k]
    lin_ = [c ** 2.2 for c in col]; lum = sum(col) / 3; sat = max(col) - min(col)
    if cat == 'lens' and tag == 'glass':
        m = glass_mat('lensglass_%d' % len(_MC), tuple(min(1.0, 0.55 + c * 0.5) for c in lin_))
    elif tag == 'sensorglass':
        m = glass_mat('sensorglass', (0.75, 0.9, 1.0))
    elif lum > 0.55 and sat < 0.30:                     # tin / silver / steel
        m = mat('mt_%d' % len(_MC), lin_, 0.26, 1.0)
    elif sat > 0.30 and lum > 0.55:                     # gold
        m = mat('au_%d' % len(_MC), lin_, 0.22, 1.0)
    elif cat == 'lens':
        m = mat('lensbody_%d' % len(_MC), lin_, 0.32, 0.6)
    elif cat in ('ic', 'led'):
        m = mat('ic_%d' % len(_MC), lin_, 0.38, 0.0, Coat_Weight=0.12)
    else:
        m = mat('dc_%d' % len(_MC), lin_, 0.48, 0.0)
    _MC[k] = m; return m

LENS_TAGS = [(0.098, 'holder'), (0.545, 'nut'), (0.063, 'barrel'), (0.141, 'bezel'), (0.352, 'glass'), (0.039, 'spacer')]
def lens_tag(col):
    return min(LENS_TAGS, key=lambda t: abs(t[0] - col[0]))[1]

def board_info():
    parts = load_parts(); bp = [p for p in parts if p['ref'] == 'board']
    bb = [min(p['bb'][0] for p in bp), min(p['bb'][1] for p in bp), min(p['bb'][2] for p in bp), max(p['bb'][3] for p in bp), max(p['bb'][4] for p in bp), max(p['bb'][5] for p in bp)]
    return bp, bb

def build_lens(cut_x=None):
    """Real M12 holder + lens (LH1) and OV9281 CSP (U10) from the full-assembly model, in assembled coordinates.
    Returns the objects named lens_holder / lens_nut / lens_barrel / lens_bezel / lens_el* / lens_spacer / sensor*."""
    bp, b0 = board_info(); cx, cy = (b0[0] + b0[3]) / 2, (b0[1] + b0[4]) / 2
    obs = []
    for p in load_parts():
        if p['ref'] not in ('LH1', 'U10'): continue
        v = p['v']; V_ = [(v[i] - cx, v[i + 1] - cy, v[i + 2] + PCB_DZ) for i in range(0, len(v), 3)]
        F = [tuple(p['f'][i:i + 3]) for i in range(0, len(p['f']), 3)]
        if p['ref'] == 'LH1':
            tg = lens_tag(p['col']); name = 'lens_el' if tg == 'glass' else 'lens_' + tg
            ob = add_obj(name, V_, F, mat_col(p['col'], 'lens', tg), smooth=(tg in ('barrel', 'glass', 'bezel')))
        else:
            glassy = abs(p['col'][0] - 0.614) < 0.05 and p['col'][2] > 0.7
            ob = add_obj('sensor_' + ('glass' if glassy else 'part'), V_, F, mat_col(p['col'], 'ic', 'sensorglass' if glassy else ''))
        obs.append(ob)
    return obs

def build_pcb(cut_x=None):
    """Board + all component models (own colours) in assembled coordinates. cut_x: drop parts whose centre x>cut_x. Returns (objs, board_obj).
    LH1 / U10 are built by build_lens()."""
    parts = load_parts(); bp, b0 = board_info()
    cx, cy = (b0[0] + b0[3]) / 2, (b0[1] + b0[4]) / 2
    def tf(v):
        return [(v[i] - cx, v[i + 1] - cy, v[i + 2] + PCB_DZ) for i in range(0, len(v), 3)]
    objs = []
    board = bp[0]
    bv = tf(board['v']); bf = [tuple(board['f'][i:i + 3]) for i in range(0, len(board['f']), 3)]
    me = bpy.data.meshes.new('board'); me.from_pydata(bv, [], bf); me.update()
    ob = bpy.data.objects.new('board', me); COLL.objects.link(ob); ob.scale = (MM,) * 3
    for k in ('top', 'bottom'): me.materials.append(M[k])
    me.materials.append(M['edge'])
    idx = []
    for p in me.polygons:
        idx.append(0 if p.normal.z > 0.5 else (1 if p.normal.z < -0.5 else 2))
    me.polygons.foreach_set('material_index', idx)
    uv = me.uv_layers.new(name='UVMap')
    for p in me.polygons:
        for li in p.loop_indices:
            x, y, _ = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (x / 47.9806 + 0.5, y / 47.9806 + 0.5)
    objs.append(ob)
    groups = {}
    for p in parts:
        if p['ref'] in ('board', 'LH1', 'U10'): continue
        v = tf(p['v'])
        if cut_x is not None and sum(a[0] for a in v) / len(v) > cut_x: continue
        cat = cat_of_ref(p['ref'])
        g = groups.setdefault((cat, tuple(p['col'])), ([], []))
        base = len(g[0]); g[0].extend(v)
        g[1].extend((a + base, b + base, c + base) for a, b, c in [tuple(p['f'][i:i + 3]) for i in range(0, len(p['f']), 3)])
    for (cat, col), (v, f) in groups.items():
        o = add_obj('comp_%s_%d' % (cat, len(objs)), v, f, mat_col(col, cat)); objs.append(o)
    return objs, ob

# ------------------------------------------------------------------ scene / lighting / camera
def setup_render(w, h, spp):
    sc.render.engine = 'CYCLES'; cy = sc.cycles
    cy.samples = spp; cy.use_denoising = True; cy.denoiser = 'OPENIMAGEDENOISE'
    cy.use_adaptive_sampling = True; cy.adaptive_threshold = 0.02
    cy.max_bounces = 10; cy.glossy_bounces = 6; cy.transmission_bounces = 10; cy.transparent_max_bounces = 16
    cy.sample_clamp_indirect = 4.0; cy.caustics_reflective = False; cy.caustics_refractive = False; cy.blur_glossy = 0.5
    dev = os.environ.get('RENDER_DEVICE', 'CPU')
    if dev != 'CPU':
        try:
            p = bpy.context.preferences.addons['cycles'].preferences; p.compute_device_type = dev; p.get_devices()
            for d in p.devices: d.use = (d.type != 'CPU') and 'Radeon RX' in d.name
            cy.device = 'GPU'
        except Exception as e:
            print('GPU setup failed, CPU', e); cy.device = 'CPU'
    else:
        cy.device = 'CPU'
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_depth = '8'
    sc.render.film_transparent = False
    try: sc.view_settings.view_transform = 'Khronos PBR Neutral'
    except Exception: sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'; sc.view_settings.exposure = 0.0

def cyclorama(floor_z, col=(0.52, 0.53, 0.55), wall=0.5):
    """Floor + curved back wall (metres). floor_z in mm."""
    z0 = floor_z * MM
    prof = [(-1.5, 0)]
    prof += [(wall, 0)]
    R = 0.35
    for k in range(0, 13):
        a = math.pi / 2 * k / 12
        prof.append((wall + R * math.sin(a), R * (1 - math.cos(a))))
    prof.append((wall + R, 1.8))
    verts, faces = [], []
    for i, (y, z) in enumerate(prof):
        for xs in (-2.5, 2.5): verts.append((xs, y, z + z0))
        if i: faces.append((2 * i - 2, 2 * i - 1, 2 * i + 1, 2 * i))
    me = bpy.data.meshes.new('cyc'); me.from_pydata(verts, [], faces); me.update()
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    ob = bpy.data.objects.new('cyc', me); COLL.objects.link(ob)
    m = mat('cyc', col, 0.75); b = m.node_tree.nodes['Principled BSDF']; b.inputs['Specular IOR Level'].default_value = 0.25
    me.materials.append(m)
    return ob

def area(name, loc, target, size, power, col=(1, 1, 1), shape='RECTANGLE', sy=None):
    ld = bpy.data.lights.new(name, 'AREA'); ld.shape = shape; ld.size = size
    if sy: ld.size_y = sy
    ld.energy = power; ld.color = col; ld.use_shadow = True
    ob = bpy.data.objects.new(name, ld); COLL.objects.link(ob); ob.location = loc
    d = Vector(target) - Vector(loc); ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return ob

def studio(target, k=1.0):
    """Soft three-point rig + overhead softbox; target in metres."""
    t = Vector(target); k = k * LK
    area('key', t + Vector((-0.30, -0.38, 0.38)), t, 0.34, 95 * k, (1.0, 0.97, 0.93), 'RECTANGLE', 0.34)
    area('fill', t + Vector((0.45, -0.30, 0.18)), t, 0.40, 10 * k, (0.90, 0.95, 1.0), 'RECTANGLE', 0.30)
    area('rim', t + Vector((0.12, 0.45, 0.20)), t, 0.50, 40 * k, (1.0, 1.0, 1.0), 'RECTANGLE', 0.08)
    area('top', t + Vector((0.0, 0.0, 0.55)), t, 0.55, 30 * k, (1.0, 1.0, 1.0), 'RECTANGLE', 0.40)
    w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; bg = nt.nodes['Background']; bg.inputs['Color'].default_value = (0.42, 0.43, 0.45, 1); bg.inputs['Strength'].default_value = 0.35 * LK / 0.08 * 0.2

def camera(pos_dir, target, dist, lens=85.0, fstop=None, w=1920, h=1080):
    cam = bpy.data.cameras.new('cam'); cam.lens = lens; cam.sensor_width = 36; cam.clip_start = 0.01; cam.clip_end = 20
    ob = bpy.data.objects.new('cam', cam); COLL.objects.link(ob); sc.camera = ob
    d = Vector(pos_dir).normalized(); t = Vector(target)
    ob.location = t + d * dist
    ob.rotation_euler = (t - ob.location).to_track_quat('-Z', 'Y').to_euler()
    if fstop:
        cam.dof.use_dof = True; cam.dof.focus_distance = dist; cam.dof.aperture_fstop = fstop
    return ob

def world_min_z(objs):
    bpy.context.view_layer.update()
    zmin = 1e9
    for o in objs:
        if o.type != 'MESH': continue
        for c in o.bound_box:
            zmin = min(zmin, (o.matrix_world @ Vector(c)).z)
    return zmin / MM

def finalize_and_render(path):
    sc.render.filepath = path
    t0 = time.time(); bpy.ops.render.render(write_still=True)
    print('RENDERED', path, '%.1fs' % (time.time() - t0))

# ------------------------------------------------------------------ shots
def place_all(objs, dz=0.0, parent=None):
    for o in objs:
        o.location = (0, 0, dz * MM)
        if parent: o.parent = parent

def shot_hero(path, w, h, spp, turn=None):
    hs = build_housing(); lens = build_lens(); pcb, _ = build_pcb()
    root = bpy.data.objects.new('turn', None); COLL.objects.link(root)
    for o in list(hs.values()) + lens + pcb: o.parent = root
    hs['front'].location = (0, 0, ZS * MM)       # front.stl is modelled with z=0 at the split plane
    cyc = cyclorama(0.0, (0.34, 0.35, 0.37)); tgt = (0.002, 0.004, 0.011)
    studio(tgt)
    camera((-0.62, -0.78, 0.46), tgt, 0.34, 85, 16, w, h)
    if turn is None:
        finalize_and_render(path)
    return root

def shot_exploded(path, w, h, spp):
    hs = build_housing(); lens = build_lens(); pcb, _ = build_pcb()
    dz_pcb, dz_front = 24.0, 62.0
    hs['front'].location = (0, 0, (ZS + dz_front) * MM)
    for o in lens + pcb: o.location = (0, 0, dz_pcb * MM)
    # faint assembly guide lines through the four screw holes
    gl = mat('guide', (0.7, 0.7, 0.72), 0.5)
    for sx in (-20.5, 20.5):
        for sy in (-20.5, 20.5):
            o = add_obj('guide', [(sx + a * 0.12, sy + b * 0.12, z) for z in (2.4, 72.0) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))],
                        [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)], gl)
    cyclorama(0.0); tgt = (0, 0.005, 0.040)
    studio(tgt, 1.0)
    camera((-0.55, -0.80, 0.42), tgt, 0.52, 85, 11, w, h)
    finalize_and_render(path)

def shot_pcb(path, w, h, spp, side):
    pcb, _ = build_pcb(); lens = build_lens()
    objs = pcb + lens
    piv = Vector((0, 0, 7.25))
    g = bpy.data.objects.new('pcbg', None); COLL.objects.link(g); g.location = piv * MM
    for o in objs: o.parent = g; o.location = -piv * MM
    if side == 'bottom': g.rotation_euler = (math.pi, 0, math.radians(0))
    fz = world_min_z(objs) - (0 if side == 'top' else 0.0)
    cyclorama(fz - 0.5)
    tgt = (0, 0.0, (fz + (8 if side == 'top' else 12)) * MM) if side == 'top' else (0, 0, (fz + 12) * MM)
    tgt = (0, 0.0, 0.009 if side == 'top' else 0.0128 + fz * MM)
    studio(tgt, 1.0)
    if side == 'top':
        camera((-0.30, -0.62, 0.74), tgt, 0.27, 85, 11, w, h)
    else:
        camera((-0.30, -0.62, 0.74), tgt, 0.27, 85, 11, w, h)
    finalize_and_render(path)

def shot_section(path, w, h, spp):
    # keep x<=0 half; cutters carry a bold "cut face" colour
    CUTX = 0.0
    hs = build_housing(); lens = build_lens(); pcb, board = build_pcb(cut_x=CUTX - 0.5)
    hs['front'].location = (0, 0, ZS * MM)
    cut_cols = dict(front=(0.85, 0.22, 0.08), back=(0.85, 0.22, 0.08))
    targets = [(hs['front'], (0.80, 0.20, 0.07), 0.55, 0.0), (hs['back'], (0.80, 0.20, 0.07), 0.55, 0.0),
               (board, (0.05, 0.30, 0.12), 0.5, 0.0)]
    for o in lens:
        if o.name.startswith(('lens_holder', 'lens_nut', 'lens_barrel', 'lens_bezel', 'lens_spacer')):
            targets.append((o, (0.75, 0.55, 0.05), 0.35, 0.8))
        elif o.name.startswith('lens_el'): targets.append((o, None, 0, 0))
    for o, col, r, mt in targets:
        if col is None: continue
        cm = mat('cutface', col, r, mt)
        cob = box('cutter', (CUTX + 150, 0, 40), (300, 300, 300), cm)
        cob.hide_render = True; cob.display_type = 'WIRE'
        md = o.modifiers.new('cut', 'BOOLEAN'); md.operation = 'DIFFERENCE'; md.solver = 'EXACT'; md.object = cob
        try: md.material_mode = 'TRANSFER'
        except Exception: pass
    # glass elements: cut with a plain cutter (glass colour)
    gcut = box('cutter_g', (CUTX + 150, 0, 40), (300, 300, 300), M['glass'])
    gcut.hide_render = True; gcut.display_type = 'WIRE'
    for o in lens:
        if o.name.startswith('lens_el'):
            md = o.modifiers.new('cut', 'BOOLEAN'); md.operation = 'DIFFERENCE'; md.solver = 'EXACT'; md.object = gcut
    for o in lens:                      # sensor stays, half only
        if o.name.startswith('sensor'): o.modifiers.new('cut', 'BOOLEAN'); o.modifiers[-1].object = gcut; o.modifiers[-1].solver = 'EXACT'; o.modifiers[-1].operation = 'DIFFERENCE'
    # ---- HFOV cone: apex at the entrance pupil of the hood (lens top 22.0 above the split plane + 1.1, from housing.scad), half angle = rectilinear HFOV/2 from pcb_params.json
    _lp = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pcb', 'pcb_params.json')))['lens_holder']
    az = ZS + _lp['height_above_board'] + _lp['lens_total_height_above_holder'] + 1.1; L = 38.0; r = L * math.tan(math.radians(_lp['hfov_deg'] / 2))
    cm = emit_mat('fov', (1.0, 0.78, 0.25), 1.2, 0.16)
    cone = lathe('fov_cone', [(0.0, az), (r, az + L)], cm, a0=math.pi / 2, a1=3 * math.pi / 2, seg=64, closed=False, smooth=True)
    tri = add_obj('fov_plane', [(0, AXIS[1], az), (0, AXIS[1] - r, az + L), (0, AXIS[1] + r, az + L)], [(0, 1, 2)], emit_mat('fov2', (1.0, 0.8, 0.3), 1.0, 0.22))
    lm = emit_mat('fov_edge', (1.0, 0.85, 0.35), 6.0)
    def line(p0, p1, rad=0.22, mm=lm):
        d = Vector(p1) - Vector(p0); L_ = d.length; vs = []
        q = d.to_track_quat('Z', 'Y'); pts = [(math.cos(a) * rad, math.sin(a) * rad) for a in [i * math.pi / 3 for i in range(6)]]
        v = [Vector(p0) + q @ Vector((x, y, 0)) for x, y in pts] + [Vector(p0) + q @ Vector((x, y, L_)) for x, y in pts]
        f = [(i, (i + 1) % 6, 6 + (i + 1) % 6, 6 + i) for i in range(6)]
        return add_obj('line', [tuple(a) for a in v], f, mm)
    line((0, AXIS[1], az), (0, AXIS[1] - r, az + L)); line((0, AXIS[1], az), (0, AXIS[1] + r, az + L))
    line((0, AXIS[1], ZS + 0.7), (0, AXIS[1], az + L + 6), 0.12, emit_mat('axis', (0.9, 0.9, 1.0), 2.0))
    # ray from sensor through the lens to the cone edges (thin, to show the optical path)
    for sy in (-1, 1):
        line((0, AXIS[1] + sy * 1.8, ZS + 0.75), (0, AXIS[1], az), 0.1, emit_mat('ray', (1, 0.9, 0.5), 3.0))
    # label (built-in font)
    cu = bpy.data.curves.new('lbl', 'FONT'); cu.body = '%.1f° HFOV' % _lp['hfov_deg']; cu.size = 7.0 * MM * 1000 / 1000; cu.extrude = 0.0
    lo = bpy.data.objects.new('lbl', cu); COLL.objects.link(lo)
    cu.size = 0.0075
    lo.location = (0.0, (AXIS[1] + 0.0) * MM - 0.0, (az + L * 0.55) * MM); lo.rotation_euler = (math.pi / 2, 0, math.pi / 2)
    lo.location = (0.0005, (AXIS[1] - 6) * MM * 1.0 + 0.0, (az + L * 0.52) * MM)
    lo.data.materials.append(emit_mat('lbltxt', (1, 0.95, 0.8), 4.0)); lo.data.align_x = 'CENTER'
    lo.location.y = AXIS[1] * MM
    cyclorama(0.0, (0.46, 0.47, 0.49), wall=1.0)
    tgt = (0, AXIS[1] * MM, 0.030)
    studio(tgt, 1.2)
    camera((1.0, -0.40, 0.22), tgt, 0.40, 85, None, w, h)
    finalize_and_render(path)

def shot_turntable(outdir, w, h, spp, nframes, name='turntable'):
    root = shot_hero(None, w, h, spp, turn=True)
    fdir = os.path.join(WORK, 'turn_frames'); os.makedirs(fdir, exist_ok=True)
    for i in range(nframes):
        root.rotation_euler = (0, 0, 2 * math.pi * i / nframes)
        finalize_and_render(os.path.join(fdir, 'f%03d.png' % i))

# ------------------------------------------------------------------ main
if __name__ == '__main__':
    setup_render(RES[0], RES[1], SPP)
    # lens camera / world setup happens inside the shot functions
    s = SHOT; w, h = RES
    if s == 'hero': shot_hero(os.path.join(OUT, 'hero_assembled.png'), w, h, SPP)
    elif s == 'exploded': shot_exploded(os.path.join(OUT, 'exploded.png'), w, h, SPP)
    elif s == 'pcb_top': shot_pcb(os.path.join(OUT, 'pcb_top.png'), w, h, SPP, 'top')
    elif s == 'pcb_bottom': shot_pcb(os.path.join(OUT, 'pcb_bottom.png'), w, h, SPP, 'bottom')
    elif s == 'section': shot_section(os.path.join(OUT, 'section_fov.png'), w, h, SPP)
    elif s == 'turntable': shot_turntable(OUT, w, h, SPP, int(opt('--frames', 72)))
