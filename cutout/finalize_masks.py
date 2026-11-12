"""Binarize SAM probabilities, keep the largest piece, fill holes. usage: finalize_masks.py prob_dir out_dir"""
import sys, glob, os, cv2, numpy as np
src, out = sys.argv[1:3]; os.makedirs(out, exist_ok=True)
for f in sorted(glob.glob(os.path.join(src, '*.png'))):
    b = (cv2.imread(f, 0) >= 128).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    b = (lab == 1 + np.argmax(st[1:, 4])).astype(np.uint8)
    cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    m = np.zeros_like(b); cv2.drawContours(m, cs, -1, 255, -1)
    ys, xs = np.nonzero(m); h, w = m.shape
    edge = min(xs.min(), ys.min(), w - 1 - xs.max(), h - 1 - ys.max())
    if edge < 50: print('near edge', os.path.basename(f), edge)
    cv2.imwrite(os.path.join(out, os.path.basename(f)), m)
print('done')
