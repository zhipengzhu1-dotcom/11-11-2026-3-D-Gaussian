"""Crop full-frame RGBA images (and optional solver masks) to one centred window.

usage: prepare.py <image_dir> <out_image_dir> [--solver-masks DIR --out-masks DIR] [--crop auto|WxH]

The window is centred on the frame so the principal point stays at its centre,
which the solver and the exported camera both assume. "auto" sizes it to hold
every frame's alpha (and solver mask) with a margin.
"""
import argparse
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from shoot import list_pngs, read_mask, stem

ap = argparse.ArgumentParser()
ap.add_argument("image_dir")
ap.add_argument("out_image_dir")
ap.add_argument("--solver-masks")
ap.add_argument("--out-masks")
ap.add_argument("--crop", default="auto")
args = ap.parse_args()
if bool(args.solver_masks) != bool(args.out_masks):
    sys.exit("--solver-masks and --out-masks go together")

images = list_pngs(args.image_dir)
stems = [stem(p) for p in images]
masks = None
if args.solver_masks:
    masks = list_pngs(args.solver_masks)
    if [stem(p) for p in masks] != stems:
        sys.exit(f"FAIL: {args.solver_masks} and {args.image_dir} do not hold the same frame names")


def reach(path):
    """Frame size and how far the mask extends from the frame centre (half-width, half-height)."""
    a = read_mask(path)
    h, w = a.shape
    ys, xs = np.nonzero(a > 8)
    if len(xs) == 0:
        return w, h, None
    return w, h, (max(w / 2 - xs.min(), xs.max() + 1 - w / 2), max(h / 2 - ys.min(), ys.max() + 1 - h / 2))


with ThreadPoolExecutor(8) as ex:
    info = list(ex.map(reach, images + (masks or [])))
sizes = {(w, h) for w, h, _ in info}
if len(sizes) != 1:
    sys.exit(f"FAIL: inputs have mixed sizes {sorted(sizes)}")
W, H = sizes.pop()
empty = [stem(p) for p, (_, _, r) in zip(images + (masks or []), info) if r is None]
if empty:
    sys.exit(f"FAIL: {len(empty)} empty masks, e.g. {empty[0]}")

if args.crop == "auto":
    hw = max(r[0] for _, _, r in info) * 1.08 + 48
    hh = max(r[1] for _, _, r in info) * 1.08 + 48
    cw, ch = min(W, 2 * math.ceil(hw / 16) * 16), min(H, 2 * math.ceil(hh / 16) * 16)
else:
    cw, ch = (int(v) for v in args.crop.lower().split("x"))
    if cw > W or ch > H or cw % 2 or ch % 2:
        sys.exit(f"FAIL: crop {cw}x{ch} must be even and fit inside {W}x{H}")
x0, y0 = (W - cw) // 2, (H - ch) // 2
print(f"{len(images)} frames {W}x{H} -> centred crop {cw}x{ch} at offset ({x0},{y0})")

os.makedirs(args.out_image_dir, exist_ok=True)
if args.out_masks:
    os.makedirs(args.out_masks, exist_ok=True)


def crop(i):
    img = cv2.imread(images[i], cv2.IMREAD_UNCHANGED)
    cv2.imwrite(os.path.join(args.out_image_dir, stems[i] + ".png"), img[y0:y0 + ch, x0:x0 + cw])
    if masks:
        cv2.imwrite(os.path.join(args.out_masks, stems[i] + ".png"), read_mask(masks[i])[y0:y0 + ch, x0:x0 + cw])


with ThreadPoolExecutor(8) as ex:
    list(ex.map(crop, range(len(images))))
