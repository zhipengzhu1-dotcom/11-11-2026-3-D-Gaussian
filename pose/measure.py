"""Per-frame silhouette measurements and ring detection.

usage: measure.py <mask_dir> <out.npz> [--table]

Row columns: cx, cy, area, major, minor, angle, long, short (pixels; long and
short are the sides of the tightest rotated box round the silhouette).
Exits 1 when a mask is empty, sizes differ, or a detected ring is too short.
"""
import argparse
import sys

import cv2
import numpy as np

from shoot import detect_rings, list_pngs, read_mask, stem

ap = argparse.ArgumentParser()
ap.add_argument("mask_dir")
ap.add_argument("out")
ap.add_argument("--table", action="store_true", help="print one row per frame")
args = ap.parse_args()

names = list_pngs(args.mask_dir)
rows, size, problems, clipped = [], None, [], []
for n in names:
    a = read_mask(n)
    if size is None:
        size = (a.shape[1], a.shape[0])
    elif size != (a.shape[1], a.shape[0]):
        problems.append(f"{stem(n)}: size {a.shape[1]}x{a.shape[0]} differs from {size[0]}x{size[1]}")
        continue
    b = (a > 127).astype(np.uint8)
    m = cv2.moments(b, binaryImage=True)
    if m["m00"] < 100:
        problems.append(f"{stem(n)}: empty mask")
        continue
    if b[0].any() or b[-1].any() or b[:, 0].any() or b[:, -1].any():
        clipped.append(stem(n))
    cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    cov = np.array([[m["mu20"], m["mu11"]], [m["mu11"], m["mu02"]]]) / m["m00"]
    w, v = np.linalg.eigh(cov)
    ang = np.degrees(np.arctan2(v[1, 1], v[0, 1]))
    contours, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    big = max(contours, key=cv2.contourArea)
    if cv2.contourArea(big) < 0.9 * m["m00"]:
        problems.append(f"{stem(n)}: mask has stray pieces (largest blob is "
                        f"{100 * cv2.contourArea(big) / m['m00']:.0f}% of the area)")
    (_, _), (rw, rh), _ = cv2.minAreaRect(big)
    rows.append([cx, cy, m["m00"], np.sqrt(w[1]), np.sqrt(w[0]), ang, max(rw, rh), min(rw, rh)])

if problems:
    print("\n".join(problems))
    sys.exit(f"FAIL: {len(problems)} of {len(names)} masks are unusable")

rows = np.array(rows)
rings = detect_rings(rows[:, 0], rows[:, 1])
np.savez(args.out, rows=rows, names=np.array(names), size=np.array(size), rings=np.array(rings))

if args.table:
    for i, r in enumerate(rows):
        print(f"{i:3d} {stem(names[i])} cx {r[0]:7.1f} cy {r[1]:7.1f} area {r[2]:8.0f} "
              f"long {r[6]:6.1f} short {r[7]:6.1f} ang {r[5]:7.1f}")
print(f"{len(names)} masks, {size[0]}x{size[1]} px, {len(rings)} rings detected")
for k, (a, b) in enumerate(rings):
    print(f"ring {k}: frames {a}-{b - 1} ({stem(names[a])}..{stem(names[b - 1])}), {b - a} shots, "
          f"longest silhouette {rows[a:b, 6].max():.0f} px")
if clipped:
    print(f"WARNING: {len(clipped)} masks touch the frame edge (first: {clipped[0]}). A cut-off silhouette biases "
          f"the solver's starting camera heights; use a wider crop if the fit fails.")
short = [f"ring {k} has {b - a} shots" for k, (a, b) in enumerate(rings) if b - a < 8]
if short:
    sys.exit("FAIL: " + "; ".join(short) + ". Set \"rings\" in shoot.json by hand.")
