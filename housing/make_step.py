"""Housing STL -> STEP (FreeCAD): front.stl / back.stl become solids in one STEP file. Run: freecadcmd make_step.py"""
import os, FreeCAD, Mesh, Part
HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else r'D:\apriltag-proccessor\housing'
doc = FreeCAD.newDocument('housing')
objs = []
for name in ('back', 'front'):
    m = Mesh.Mesh(os.path.join(HERE, 'output', name + '.stl'))
    sh = Part.Shape(); sh.makeShapeFromMesh(m.Topology, 0.01)
    sh = Part.Solid(Part.Shell(sh.Faces)); sh = sh.removeSplitter()
    o = doc.addObject('Part::Feature', 'housing_' + name); o.Shape = sh; objs.append(o)
    print(name, 'solid', sh.isValid(), 'volume mm3', round(sh.Volume, 1), 'faces', len(sh.Faces))
    Part.export([o], os.path.join(HERE, 'output', f'housing_{name}.step'))
Part.export(objs, os.path.join(HERE, 'output', 'housing.step'))
