# freecadcmd helper for render_part_thumbs.py: KiCad STEP -> per-face tessellated meshes WITH the STEP's face colours (JSON).
# env THUMB_JOBS = json {key: step_path}, THUMB_OUT = dir.   Output: [{faces:[{rgb,v,f}]}] per solid.
import os, re, json, FreeCAD, Import
jobs = json.loads(os.environ["THUMB_JOBS"]); out = os.environ["THUMB_OUT"]

def parse_step(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = t[t.find("DATA;"):]
    ents = {}
    for m in re.finditer(r"#(\d+)\s*=\s*(.*?);\s*(?=\n#|\nENDSEC)", t, re.S):
        ents[int(m.group(1))] = re.sub(r"\s+", " ", m.group(2))
    return ents

def rgb_of(ents, eid, depth=0, seen=None):
    seen = seen or set()
    if eid in seen or depth > 12 or eid not in ents: return None
    seen.add(eid); s = ents[eid]
    if s.startswith("COLOUR_RGB"):
        a = s[s.rfind(",") - 40:]
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", s.split("'',", 1)[1] if "'''" not in s else s)
        return [float(x) for x in nums[:3]]
    for r in re.findall(r"#(\d+)", s):
        c = rgb_of(ents, int(r), depth + 1, seen)
        if c: return c
    return None

def shells_with_colours(path):
    ents = parse_step(path)
    fcol = {}
    for eid, s in ents.items():
        if s.startswith("STYLED_ITEM") or s.startswith("OVER_RIDING_STYLED_ITEM"):
            ids = [int(x) for x in re.findall(r"#(\d+)", s)]
            if len(ids) >= 2:
                c = rgb_of(ents, ids[0])
                if c: fcol[ids[1]] = c
    solids = []
    for eid in sorted(ents):
        s = ents[eid]
        if s.startswith("MANIFOLD_SOLID_BREP"):
            sh = int(re.findall(r"#(\d+)", s)[0])
            faces = [int(x) for x in re.findall(r"#(\d+)", ents[sh])]
            solids.append([fcol.get(f) or fcol.get(eid) for f in faces])
    return solids

for key, step in jobs.items():
    try:
        cols = shells_with_colours(step)
        doc = FreeCAD.newDocument("t")
        Import.insert(step, doc.Name)
        res = []; k = 0
        for o in doc.Objects:
            if not hasattr(o, "Shape") or o.Shape.isNull(): continue
            for s in o.Shape.Solids:
                fl = []
                for fa in s.Faces:
                    v, f = fa.tessellate(0.02)
                    if f: fl.append(dict(v=[round(c, 4) for p in v for c in (p.x, p.y, p.z)], f=[i for t in f for i in t], area=fa.Area))
                res.append(dict(faces=fl, nface=len(s.Faces), vol=s.Volume))
        # attach colours: match solids to MANIFOLD_SOLID_BREP lists by face count, in order
        pool = list(cols)
        for r in res:
            m = next((c for c in pool if len(c) == r["nface"]), None)
            if m: pool.remove(m)
            for i, fd in enumerate(r["faces"]):
                fd["rgb"] = m[i] if m and i < len(m) else None
        json.dump(res, open(os.path.join(out, key + ".json"), "w"))
        print("OK", key, len(res), "solids", sum(1 for r in res for f in r["faces"] if f["rgb"]), "coloured faces of", sum(len(r["faces"]) for r in res))
        FreeCAD.closeDocument(doc.Name)
    except Exception as e:
        import traceback; traceback.print_exc(); print("FAIL", key, e)
