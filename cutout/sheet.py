"""Contact sheet: mask outline over source, zoomed on the mask bbox. usage: sheet.py src maskdir out.jpg idx..."""
import sys, glob, os, cv2, numpy as np
src, md, out = sys.argv[1:4]; idx = [int(i) for i in sys.argv[4:]]
fs = sorted(glob.glob(os.path.join(md, '*.png'))); tiles = []
for i in idx:
    m = cv2.imread(fs[i], 0); im = cv2.imread(os.path.join(src, os.path.basename(fs[i])))
    b = (m > 127).astype(np.uint8)
    ys, xs = np.nonzero(b); cx, cy = (xs.min()+xs.max())//2, (ys.min()+ys.max())//2
    s = 700; x0, y0 = max(cx-s//2*1, 0), max(cy-s//2, 0)
    cs, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(im, cs, -1, (0, 0, 255), 2)
    t = cv2.resize(im[y0:y0+s, x0:x0+s], (350, 350)); cv2.putText(t, str(i), (5, 25), 0, 0.8, (0,0,255), 2); tiles.append(t)
while len(tiles) % 6: tiles.append(np.zeros_like(tiles[0]))
rows = [np.hstack(tiles[k:k+6]) for k in range(0, len(tiles), 6)]
cv2.imwrite(out, np.vstack(rows))
