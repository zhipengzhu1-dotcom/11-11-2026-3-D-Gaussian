"""PSNR of Brush held-out renders against the training images (composited on black).

usage: psnr.py <eval_images_dir> <dataset_images_dir> [--min DB]

Exits 1 when the mean is below --min.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("eval_dir")
ap.add_argument("gt_dir")
ap.add_argument("--min", type=float)
args = ap.parse_args()

vals = []
for p in sorted(glob.glob(os.path.join(args.eval_dir, "*.png"))):
    r = cv2.imread(p, cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
    g = cv2.imread(os.path.join(args.gt_dir, os.path.basename(p)), cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
    if r.shape[2] == 4:
        r = r[..., :3] * r[..., 3:]
    g3 = g[..., :3] * g[..., 3:]
    ys, xs = np.nonzero(g[..., 3] > 0.5)
    y0, y1, x0, x1 = max(0, ys.min() - 20), ys.max() + 20, max(0, xs.min() - 20), xs.max() + 20
    mse = ((r[y0:y1, x0:x1, :3] - g3[y0:y1, x0:x1]) ** 2).mean()
    vals.append(-10 * np.log10(mse))
if not vals:
    sys.exit(f"FAIL: no held-out renders in {args.eval_dir}")
vals = np.array(vals)
n = len(vals)
print(f"PSNR (object crop) mean {vals.mean():.2f} dB over {n} held-out views | "
      f"by third: {vals[:n//3].mean():.2f} {vals[n//3:2*n//3].mean():.2f} {vals[2*n//3:].mean():.2f}")
if args.min is not None and vals.mean() < args.min:
    sys.exit(f"FAIL: held-out PSNR {vals.mean():.2f} dB is below {args.min} dB; the poses are suspect")
