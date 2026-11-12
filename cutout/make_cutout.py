"""Capsule + reflection RGBA cutouts.

alpha = 1 inside the SAM capsule mask; around its lower half, a soft alpha from how much greener
than red a pixel is relative to the local table (the cyan glow cast by the capsule).
usage: make_cutout.py edited_dir mask_dir out_dir [--preview dir] [idx ...]
"""
import sys, glob, os, cv2, numpy as np

R_DIL = 220        # how far from the capsule the reflection may reach, px
T0, T1 = 8.0, 30.0  # score above table median where alpha starts / reaches 1


def cutout(img, m):
    cap = m > 127
    ys, xs = np.nonzero(cap)
    pad = R_DIL + 40
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, m.shape[1])
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, m.shape[0])
    im = img[y0:y1, x0:x1].astype(np.float32); c = cap[y0:y1, x0:x1]
    score = cv2.GaussianBlur(im[:, :, 1] - im[:, :, 2], (0, 0), 3)  # G - R (BGR order)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * R_DIL + 1, 2 * R_DIL + 1))
    near = cv2.dilate(c.astype(np.uint8), k) > 0
    ring = cv2.dilate(c.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * (R_DIL + 40) + 1,) * 2)) > 0
    bg = np.median(score[ring & ~near]) if (ring & ~near).any() else np.median(score[~near])
    # only below the capsule's middle: the glow lies on the table under it
    cy = (ys.min() + ys.max()) / 2 - y0
    below = np.arange(im.shape[0])[:, None] >= cy
    a = np.clip((score - bg - T0) / T1, 0, 1) * (near & below)
    # keep only glow connected to the capsule
    lab_n, lab = cv2.connectedComponents(((a > 0.05) | c).astype(np.uint8))
    keep = np.isin(lab, np.unique(lab[c]))
    a = np.where(keep, a, 0)
    a = np.maximum(a, c.astype(np.float32))
    full = np.zeros(m.shape, np.uint8); full[y0:y1, x0:x1] = (a * 255 + 0.5).astype(np.uint8)
    return full


def main():
    args = sys.argv[1:]; prev = None
    if '--preview' in args:
        i = args.index('--preview'); prev = args[i + 1]; del args[i:i + 2]
    src, md, out = args[:3]; idx = [int(i) for i in args[3:]]
    fs = sorted(glob.glob(os.path.join(md, '*.png')))
    sel = idx or range(len(fs))
    if out != '-': os.makedirs(out, exist_ok=True)
    if prev: os.makedirs(prev, exist_ok=True)
    for i in sel:
        name = os.path.basename(fs[i]); img = cv2.imread(os.path.join(src, name)); m = cv2.imread(fs[i], 0)
        a = cutout(img, m)
        if out != '-':
            cv2.imwrite(os.path.join(out, name), np.dstack([img, a]))
        if prev:
            ys, xs = np.nonzero(m > 127); cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2 + 100
            s = 1300; X, Y = cx - s // 2, cy - s // 2
            crop = img[Y:Y + s, X:X + s].astype(np.float32); al = a[Y:Y + s, X:X + s, None] / 255.0
            comp = crop * al + np.array([40, 40, 40]) * (1 - al)
            t = np.hstack([crop, comp, cv2.cvtColor(a[Y:Y + s, X:X + s], cv2.COLOR_GRAY2BGR).astype(np.float32)])
            t = cv2.resize(t.astype(np.uint8), (1200, 400)); cv2.putText(t, str(i), (5, 30), 0, 1, (0, 0, 255), 2)
            cv2.imwrite(os.path.join(prev, f'{i:03d}.jpg'), t)
        print(i, name, flush=True)


if __name__ == '__main__':
    main()
