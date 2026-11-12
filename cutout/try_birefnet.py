import sys, glob, os, time, cv2, numpy as np
from PIL import Image
from rembg import new_session, remove
model, out = sys.argv[1], sys.argv[2]; idx = [int(i) for i in sys.argv[3:]]
os.makedirs(out, exist_ok=True)
sess = new_session(model)
fs = sorted(glob.glob('assets/Round-2-Mask/*.png'))
for i in idx:
    name = os.path.basename(fs[i]); m = cv2.imread(fs[i], 0)
    ys, xs = np.nonzero(m); cx = (xs.min()+xs.max())//2; cy = (ys.min()+ys.max())//2
    S = 1400; x0, y0 = cx - S//2, cy - S//2 + 150
    im = cv2.imread('assets/Round-2-Edited/' + name)[y0:y0+S, x0:x0+S]
    t = time.time(); a = np.array(remove(Image.fromarray(im[:, :, ::-1]), session=sess, only_mask=True))
    print(i, f'{time.time()-t:.1f}s', flush=True)
    cv2.imwrite(f'{out}/{i}.png', np.hstack([im, cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)]))
