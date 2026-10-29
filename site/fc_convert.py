# Run with FreeCAD: freecadcmd.exe fc_convert.py   (env STEP_IN, JSON_OUT)
import os, json, FreeCAD, Import
src = os.environ["STEP_IN"]; out = os.environ["JSON_OUT"]
doc = FreeCAD.newDocument("x")
Import.insert(src, doc.Name)
parts = []
for o in doc.Objects:
    if not hasattr(o, "Shape") or o.Shape.isNull() or not o.Shape.Solids: continue
    if o.Shape.Solids and len(o.Shape.Solids) > 1 and o.Shape.Solids[0].isEqual(o.Shape) is False: pass
    for sol in o.Shape.Solids:
        v, f = sol.tessellate(0.05)
        if not f: continue
        bb = sol.BoundBox
        parts.append(dict(name=o.Label, bb=[bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
                          v=[round(c, 3) for p in v for c in (p.x, p.y, p.z)], f=[i for t in f for i in t]))
json.dump(parts, open(out, "w"))
print("PARTS", len(parts))
