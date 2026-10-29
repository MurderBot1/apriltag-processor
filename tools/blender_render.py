"""Run with:  blender -b -P blender_render.py -- cases.json out_dir
Renders the AprilTag world (config/tag_map.json) from every camera pose in cases.json
using an ideal pinhole camera on a 1920x1200 canvas (f=640px, so the 1280x800 distorted
sensor image can be remapped from it).  Pose convention: OpenCV camera->world."""
import bpy, sys, json, math, os
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index('--') + 1:]
cases = json.load(open(argv[0])); outdir = argv[1]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmap = json.load(open(os.path.join(root, 'config', 'tag_map.json')))
SRC_W, SRC_H, F = 1920, 1200, 640.0

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
if os.environ.get('RENDER_DEVICE', 'CPU') != 'CPU':       # e.g. RENDER_DEVICE=HIP -> the RX 7700 XT (same selection as render/render_hardware.py)
    try:
        _p = bpy.context.preferences.addons['cycles'].preferences; _p.compute_device_type = os.environ['RENDER_DEVICE']; _p.get_devices()
        for _d in _p.devices: _d.use = (_d.type != 'CPU') and 'Radeon RX' in _d.name
        sc.cycles.device = 'GPU'
    except Exception as e:
        print('GPU setup failed, CPU', e)
sc.cycles.samples = int(os.environ.get('RENDER_SAMPLES', 40))
sc.cycles.use_denoising = False
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = SRC_W, SRC_H, 100
sc.view_settings.view_transform = 'Standard'
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGB'
sc.render.image_settings.color_depth = '8'


def mat_diffuse(name, base, noise=0.0, scale=40.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.9
    if noise > 0:
        n = nt.nodes.new('ShaderNodeTexNoise'); n.inputs['Scale'].default_value = scale
        n.inputs['Detail'].default_value = 8
        r = nt.nodes.new('ShaderNodeValToRGB')
        r.color_ramp.elements[0].color = (base * (1 - noise),) * 3 + (1,)
        r.color_ramp.elements[1].color = (base * (1 + noise),) * 3 + (1,)
        nt.links.new(n.outputs['Fac'], r.inputs['Fac']); nt.links.new(r.outputs['Color'], bsdf.inputs['Base Color'])
    else:
        bsdf.inputs['Base Color'].default_value = (base, base, base, 1)
    return m


def add_plane(name, size, loc, rot_m, mat):
    bpy.ops.mesh.primitive_plane_add(size=size)
    o = bpy.context.active_object; o.name = name
    o.matrix_world = Matrix.Translation(loc) @ rot_m.to_4x4()
    o.data.materials.append(mat); return o


# background surfaces (wall y=0 facing +Y, side wall x=-2.5 facing +X, floor z=0 facing +Z)
wallm, floorm = mat_diffuse('wall', 0.45, 0.35, 12), mat_diffuse('floor', 0.28, 0.3, 25)
ROOM = {}
ROOM['wall'] = add_plane('wall', 14, (0, 0, 3), Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0))), wallm)
ROOM['side'] = add_plane('side', 14, (-2.5, 3, 3), Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0))), wallm)
ROOM['floor'] = add_plane('floor', 14, (0, 3, 0), Matrix.Identity(3), floorm)
ROOM['ceil'] = add_plane('ceil', 14, (0, 3, 5), Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1))), wallm)
ROOM['back'] = add_plane('back', 14, (0, 8, 3), Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0))), wallm)
ROOM['right'] = add_plane('right', 14, (4.5, 3, 3), Matrix(((0, 0, -1), (-1, 0, 0), (0, 1, 0))), wallm)


def quat_R(q):
    w, x, y, z = q
    return Matrix(((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                   (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                   (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y))))


TAG_BSDF = []
for t in tmap['tags']:
    img = bpy.data.images.load(os.path.join(root, 'test_images', 'tags', f"tag36h11_{t['id']:03d}.png"))
    m = bpy.data.materials.new(f"tag{t['id']}"); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes['Principled BSDF']; bsdf.inputs['Roughness'].default_value = 0.85
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Linear'
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.02, 0.02, 0.02, 1)
    ramp.color_ramp.elements[1].color = (0.85, 0.85, 0.85, 1)
    nt.links.new(tex.outputs['Color'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    s = t['size'] * 10 / 8
    pos = Vector(t['position']) + quat_R(t['quat_wxyz']) @ Vector((0, 0, 0.0005))
    add_plane(f"tag{t['id']}", s, pos, quat_R(t['quat_wxyz']), m)
    TAG_BSDF.append(bsdf)

cd = bpy.data.cameras.new('cam'); cd.sensor_fit = 'HORIZONTAL'; cd.sensor_width = 36.0
cd.angle = 2 * math.atan((SRC_W / 2) / F); cd.clip_start, cd.clip_end = 0.02, 60
cam = bpy.data.objects.new('cam', cd); sc.collection.objects.link(cam); sc.camera = cam

lights = []
for i, (p, e) in enumerate((((0, 2.5, 4.2), 105), ((-2, 4, 3.8), 59), ((2.5, 3, 3.8), 59))):
    ld = bpy.data.lights.new(f'l{i}', 'AREA'); ld.energy = e; ld.size = 2.0
    lo = bpy.data.objects.new(f'l{i}', ld); lo.location = p
    sc.collection.objects.link(lo); lights.append((lo, e))
world = bpy.data.worlds.new('w'); world.use_nodes = True; sc.world = world
bg = world.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (0.5, 0.5, 0.5, 1)

# ---------------------------------------------------------------- optional per-case extensions (dataset v2)
# keys: bg {kind, scale, floor_kind}, occluders [{kind box|sphere, center, size, R, albedo}], spot {pos, target, energy, size},
#       glare {pos, target, energy, size}, tag_rough.  Cases without these keys render exactly as before.
def bg_material(kind, scale):
    m = bpy.data.materials.new('bg_' + kind); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes['Principled BSDF']; bsdf.inputs['Roughness'].default_value = 0.9

    def ramp(a, b, pa=0.0, pb=1.0):
        r = nt.nodes.new('ShaderNodeValToRGB')
        r.color_ramp.elements[0].position = pa; r.color_ramp.elements[1].position = pb
        r.color_ramp.elements[0].color = (a, a, a, 1); r.color_ramp.elements[1].color = (b, b, b, 1)
        return r
    if kind == 'dark':
        bsdf.inputs['Base Color'].default_value = (0.06, 0.06, 0.07, 1)
    elif kind == 'light':
        bsdf.inputs['Base Color'].default_value = (0.82, 0.82, 0.8, 1)
    elif kind == 'checker':
        tc = nt.nodes.new('ShaderNodeTexCoord'); ck = nt.nodes.new('ShaderNodeTexChecker')
        ck.inputs['Scale'].default_value = scale; ck.inputs['Color1'].default_value = (0.08, 0.08, 0.08, 1); ck.inputs['Color2'].default_value = (0.85, 0.85, 0.85, 1)
        nt.links.new(tc.outputs['Object'], ck.inputs['Vector']); nt.links.new(ck.outputs['Color'], bsdf.inputs['Base Color'])
    elif kind == 'stripes':
        tc = nt.nodes.new('ShaderNodeTexCoord'); w = nt.nodes.new('ShaderNodeTexWave')
        w.wave_type = 'BANDS'; w.bands_direction = 'X'; w.wave_profile = 'SAW'
        w.inputs['Scale'].default_value = scale; w.inputs['Distortion'].default_value = 1.5; w.inputs['Detail'].default_value = 1.0
        r = ramp(0.08, 0.85, 0.45, 0.55)
        nt.links.new(tc.outputs['Object'], w.inputs['Vector']); nt.links.new(w.outputs['Fac'], r.inputs['Fac']); nt.links.new(r.outputs['Color'], bsdf.inputs['Base Color'])
    elif kind == 'busy':
        tc = nt.nodes.new('ShaderNodeTexCoord'); n = nt.nodes.new('ShaderNodeTexNoise')
        n.inputs['Scale'].default_value = scale; n.inputs['Detail'].default_value = 10; n.inputs['Roughness'].default_value = 0.7
        r = ramp(0.03, 0.9, 0.42, 0.58)
        nt.links.new(tc.outputs['Object'], n.inputs['Vector']); nt.links.new(n.outputs['Fac'], r.inputs['Fac']); nt.links.new(r.outputs['Color'], bsdf.inputs['Base Color'])
    elif kind == 'brick':
        tc = nt.nodes.new('ShaderNodeTexCoord'); b = nt.nodes.new('ShaderNodeTexBrick')
        b.inputs['Scale'].default_value = scale; b.inputs['Color1'].default_value = (0.5, 0.3, 0.22, 1); b.inputs['Color2'].default_value = (0.35, 0.2, 0.15, 1)
        b.inputs['Mortar'].default_value = (0.75, 0.75, 0.72, 1)
        nt.links.new(tc.outputs['Object'], b.inputs['Vector']); nt.links.new(b.outputs['Color'], bsdf.inputs['Base Color'])
    return m


def aim(obj, pos, target):
    obj.location = pos
    obj.rotation_euler = (Vector(target) - Vector(pos)).to_track_quat('-Z', 'Y').to_euler()


extra_objs, extra_mats, extra_lights = [], [], []
base_mats = {k: o.data.materials[0] for k, o in ROOM.items()}


def setup_extras(c):
    bg = c.get('bg')
    if bg:
        for k, o in ROOM.items():
            kind = bg.get('floor_kind') if k == 'floor' else bg['kind']
            if kind and kind != 'default':
                m = bg_material(kind, bg.get('scale', 8.0)); extra_mats.append(m); o.data.materials[0] = m
    for oc in c.get('occluders', []):
        if oc['kind'] == 'sphere':
            bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=64, ring_count=32)
            o = bpy.context.active_object; bpy.ops.object.shade_smooth()
            o.matrix_world = Matrix.Translation(oc['center']) @ Matrix.Diagonal((oc['size'][0],) * 3 + (1,))
        else:
            bpy.ops.mesh.primitive_cube_add(size=1.0)
            o = bpy.context.active_object
            o.matrix_world = Matrix.Translation(oc['center']) @ Matrix(oc['R']).to_4x4() @ Matrix.Diagonal(tuple(oc['size']) + (1,))
        m = mat_diffuse('occ', oc['albedo']); o.data.materials.append(m)
        extra_objs.append(o); extra_mats.append(m)
    for key in ('spot', 'glare'):
        if c.get(key):
            sp = c[key]
            ld = bpy.data.lights.new(key, 'AREA'); ld.energy = sp['energy']; ld.size = sp['size']
            lo = bpy.data.objects.new(key, ld); sc.collection.objects.link(lo); aim(lo, sp['pos'], sp['target'])
            extra_lights.append(lo)
    for b in TAG_BSDF:
        b.inputs['Roughness'].default_value = c.get('tag_rough', 0.85)


def teardown_extras():
    for k, o in ROOM.items():
        o.data.materials[0] = base_mats[k]
    for o in extra_objs:
        me = o.data; bpy.data.objects.remove(o, do_unlink=True); bpy.data.meshes.remove(me)
    for lo in extra_lights:
        ld = lo.data; bpy.data.objects.remove(lo, do_unlink=True); bpy.data.lights.remove(ld)
    for m in extra_mats:
        bpy.data.materials.remove(m)
    extra_objs.clear(); extra_mats.clear(); extra_lights.clear()


for c in cases:
    if os.path.exists(os.path.join(outdir, c['name'] + '.png')):       # resumable: never re-render an existing frame
        print('skip', c['name'], flush=True); continue
    setup_extras(c)
    R = Matrix(c['R_wc']); t = Vector(c['t_wc'])
    Rb = R @ Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1)))        # OpenCV -> Blender camera axes
    cam.matrix_world = Matrix.Translation(t) @ Rb.to_4x4()
    ls = c.get('light_scale', 1.0)
    for lo, e in lights:
        lo.data.energy = e * ls
    lights[0][0].location = (c.get('light_shift', 0.0), 2.5, 4.2)
    bg.inputs['Strength'].default_value = 0.07 * ls
    final = os.path.join(outdir, c['name'] + '.png'); tmp = os.path.join(outdir, c['name'] + '.part.png')
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    os.replace(tmp, final)       # atomic: a half-written frame never counts as rendered
    teardown_extras()
    print('rendered', c['name'], flush=True)
