"""Shared per-shoot config and mask loading for the turntable silhouette pipeline."""
import glob
import json
import os

import cv2
import numpy as np

# Every key a shoot.json may set. None means "derive from the masks".
DEFAULTS = {
    "capsule_length_mm": 21.8,   # real long-axis length; sets the scene scale (default = round-1 nominal)
    "focal_mm": 70.0,
    "sensor_width_mm": 35.9,
    "full_width_px": 7008,       # width of the uncropped camera frame
    "close_focus_factor": 1.1,   # lens extension at close focus
    "f_px": None,                # overrides the four lens fields above
    "rings": None,               # [[start, end), ...] per camera height
    "shots_per_rev": None,       # starting guess; searched when None
    "frame_times": None,         # JSON file (relative to shoot.json) of capture seconds per frame, sorted order;
                                 # set it when shots are unevenly spaced in time (capture_info.py --times writes it)
    "d_init_mm": None,           # starting camera distance per ring
    "half_mm": None,             # half-size of the shape grid; must enclose the capsule
    "center_height_mm": None,    # capsule centre above the table
    "ds": None,                  # mask downsample factor for the fit
    "reflection": False,         # Brush images keep the table reflection
    "min_iou": 0.99,             # gate: mean silhouette IoU per ring
    "max_step_dev": 0.5,         # gate: |step - median| / |median| within a ring
    "min_psnr": 23.0,            # gate: held-out PSNR of the check run, dB
}


def load_config(path):
    cfg = dict(DEFAULTS)
    if path:
        with open(path) as fh:
            user = json.load(fh)
        unknown = sorted(set(user) - set(DEFAULTS))
        if unknown:
            raise SystemExit(f"{path}: unknown keys {unknown}; valid keys are {sorted(DEFAULTS)}")
        cfg.update(user)
        if isinstance(cfg["frame_times"], str):
            with open(os.path.join(os.path.dirname(os.path.abspath(path)), cfg["frame_times"])) as fh:
                cfg["frame_times"] = json.load(fh)
    return cfg


def list_pngs(folder):
    names = sorted(glob.glob(os.path.join(folder, "*.png")))
    if not names:
        raise SystemExit(f"no .png files in {folder}")
    return names


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def read_mask(path):
    """Silhouette as uint8: the alpha of an RGBA image, or a single-channel image as is."""
    a = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if a is None:
        raise SystemExit(f"cannot read {path}")
    if a.ndim == 3:
        if a.shape[2] != 4:
            raise SystemExit(f"{path}: no alpha channel. Masks must be RGBA or single-channel PNGs.")
        a = a[..., 3]
    if a.dtype == np.uint16:
        a = (a >> 8).astype(np.uint8)
    return a


def detect_rings(cx, cy, min_len=8):
    """Split frames into rings where the mask centroid jumps.

    Within a ring the centroid moves smoothly round an ellipse, so its second
    difference stays small. Moving the camera breaks the path, which makes the
    second difference large at both frames next to the break.
    """
    c = np.stack([cx, cy], -1)
    n = len(c)
    if n < 2 * min_len:
        return [(0, n)]
    d2 = np.linalg.norm(c[2:] - 2 * c[1:-1] + c[:-2], axis=1)  # d2[j] is centred on frame j+1
    thr = 6 * np.median(d2) + 1e-6
    cuts = [i + 1 for i in range(1, n - 2) if d2[i - 1] > thr and d2[i] > thr]  # break between i and i+1
    edges = [0] + cuts + [n]
    return [(a, b) for a, b in zip(edges[:-1], edges[1:])]
