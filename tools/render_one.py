"""Render a single dataset case by index (exposure/debug helper):  py render_one.py <index>"""
import sys, os, json, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from make_dataset import *
c = make_cases()[int(sys.argv[1])]
tmp = os.path.join(IMG, 'one.json'); json.dump([c], open(tmp, 'w'))
subprocess.run([BLENDER, '-b', '-P', os.path.join(ROOT, 'tools', 'blender_render.py'), '--', tmp,
                os.path.join(IMG, 'raw')], capture_output=True)
os.remove(tmp)
import cv2
im = cv2.imread(os.path.join(IMG, 'raw', c['name'] + '.png'))
print(c['name'], im.shape, 'mean', im.mean(), 'min', im.min(), 'max', im.max())
