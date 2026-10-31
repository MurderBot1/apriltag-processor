"""Write the 100 frames after the RTL front end (tools/golden.py: tile adaptive threshold + 3x3 despeckle) as 0/255 PGMs.
    py -3.12 tools/costdown_binpgm.py <out_dir>
Used to measure the software back-end cost (CCL + quad fit + decode) when a small FPGA does only capture + threshold."""
import os, sys, glob, cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden
from geom import ROOT
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
for f in sorted(glob.glob(os.path.join(ROOT, 'test_images', 'sensor', '*.png'))):
    im = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
    m = golden.binarize_clean(im)
    cv2.imwrite(os.path.join(out, os.path.basename(f)[:-4] + '.pgm'), np.where(m, 0, 255).astype(np.uint8))
