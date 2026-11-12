"""Write the fitted turntable cameras as a COLMAP text model plus a Brush-ready dataset.

usage: export_colmap.py <fit.npz> <image_dir> <dataset_dir> [--mirror-init]

<image_dir> holds the RGBA PNGs Brush trains on, one per fitted frame, same
size as the solver masks. --mirror-init also seeds points for the capsule's
reflection, mirrored through the table plane.
"""
import argparse
import os
import shutil
import sys

import cv2
import numpy as np
from scipy.ndimage import binary_erosion
from scipy.spatial.transform import Rotation

ap = argparse.ArgumentParser()
ap.add_argument("fit")
ap.add_argument("image_dir")
ap.add_argument("out")
ap.add_argument("--mirror-init", action="store_true")
args = ap.parse_args()

SCALE = 0.1  # mm -> cm, keeps the scene at a comfortable numeric size
d = np.load(args.fit)
R, t, f, half, grid = d["R"], d["t"] * SCALE, float(d["f"]), float(d["half"]), d["grid"]
(W, H), (cx, cy) = (int(v) for v in d["size"]), d["c"]

files = [f"{s}.png" for s in d["stems"]]
missing = [n for n in files if not os.path.exists(os.path.join(args.image_dir, n))]
if missing:
    sys.exit(f"FAIL: {len(missing)} fitted frames have no image in {args.image_dir}, e.g. {missing[0]}")
first = cv2.imread(os.path.join(args.image_dir, files[0]), cv2.IMREAD_UNCHANGED)
if first.shape[1] != W or first.shape[0] != H or first.ndim != 3 or first.shape[2] != 4:
    sys.exit(f"FAIL: {files[0]} is {first.shape[1]}x{first.shape[0]} with {first.shape[2] if first.ndim == 3 else 1} "
             f"channels; Brush needs RGBA at the solver's {W}x{H}")

os.makedirs(os.path.join(args.out, "sparse", "0"), exist_ok=True)
img_out = os.path.join(args.out, "images")
os.makedirs(img_out, exist_ok=True)
with open(os.path.join(args.out, "sparse", "0", "cameras.txt"), "w") as fh:
    fh.write(f"1 PINHOLE {W} {H} {f} {f} {cx} {cy}\n")
with open(os.path.join(args.out, "sparse", "0", "images.txt"), "w") as fh:
    for i, base in enumerate(files):
        q = Rotation.from_matrix(R[i]).as_quat()  # x y z w
        fh.write(f"{i+1} {q[3]} {q[0]} {q[1]} {q[2]} {t[i,0]} {t[i,1]} {t[i,2]} 1 {base}\n\n")
        dst = os.path.join(img_out, base)
        if not os.path.exists(dst):
            shutil.copy2(os.path.join(args.image_dir, base), dst)

# Initial points: the surface shell of the fitted silhouette hull.
occ = grid > 0
shell = occ & ~binary_erosion(occ, iterations=2)
zi, yi, xi = np.nonzero(shell)
G = grid.shape[0]
pts = (np.stack([xi, yi, zi], -1) / (G - 1) * 2 - 1) * half * SCALE
rng = np.random.default_rng(0)
if len(pts) > 60000:
    pts = pts[rng.choice(len(pts), 60000, replace=False)]
if args.mirror_init:
    below = pts.copy()
    below[:, 2] = 2 * pts[:, 2].min() - below[:, 2]  # the hull's lowest point rests on the table
    pts = np.concatenate([pts, below])
with open(os.path.join(args.out, "sparse", "0", "points3D.txt"), "w") as fh:
    for j, p in enumerate(pts):
        fh.write(f"{j+1} {p[0]} {p[1]} {p[2]} 20 170 150 0\n")
ext = (np.ptp(np.array(np.nonzero(occ)), axis=1) + 1) / G * 2 * half
print(f"{len(files)} cameras, {len(pts)} init points, hull extent mm (z,y,x): {ext.round(1)}")
