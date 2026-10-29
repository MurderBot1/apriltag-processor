"""Run the baked TPU program in the Python ISS on a binary frame."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import golden, tpu_prog
from tpu_isa import Machine, s32
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from make_tags import code_of

CODES = [code_of(i) for i in range(587)]
PROG, _ASM = tpu_prog.program()

def run_iss(mask, frame_id=1, maxham=2, **filters):
    keep, lab, allc = golden.components(mask, **filters)
    words = golden.pack_records(keep, lab)
    cand = words + [0] * (1024 - len(words))
    h, w = mask.shape
    def pix(x, y):
        return int(mask[y, x]) if 0 <= x < w and 0 <= y < h else 0
    m = Machine(PROG, CODES, pix, cand, dict(frame_id=frame_id, maxham=maxham, cand_count=len(keep), minside=8))
    m.run()
    return parse_results(m.res), m, len(keep)

def parse_results(res):
    n = s32(res[0]); tags = []
    for i in range(n):
        b = 16 + 16 * i
        w0 = res[b] & 0xFFFFFFFF
        tags.append(dict(id=w0 & 0x3FF, rot=(w0 >> 10) & 3, ham=(w0 >> 12) & 63,
                         corners=np.array([[s32(res[b + 1 + 2 * k]) / 65536.0, s32(res[b + 2 + 2 * k]) / 65536.0] for k in range(4)]),
                         label=res[b + 9], area=res[b + 10], frame=res[b + 11], quad_area=res[b + 12]))
    return tags
