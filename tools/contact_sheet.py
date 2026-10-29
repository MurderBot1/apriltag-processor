import os, sys, cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import ROOT
d = os.path.join(ROOT, 'test_images', 'sensor'); names = sorted(os.listdir(d))
tw, th, cols = 256, 160, 10
rows = (len(names) + cols - 1) // cols
sheet = np.zeros((rows * th, cols * tw), np.uint8)
for i, n in enumerate(names):
    im = cv2.resize(cv2.imread(os.path.join(d, n), 0), (tw, th), interpolation=cv2.INTER_AREA)
    cv2.putText(im, n[:-4], (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, 255, 2); cv2.putText(im, n[:-4], (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, 0, 1)
    r, c = divmod(i, cols); sheet[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = im
cv2.imwrite(os.path.join(ROOT, 'results', 'dataset_contact_sheet.png'), sheet)
