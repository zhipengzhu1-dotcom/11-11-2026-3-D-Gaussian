"""Render silhouette masks of a known capsule on a known turntable, to test the solver.

usage: synthetic_shoot.py <out_mask_dir>

Three rings at 80, 45 and 10 degrees elevation, 12 degree steps, table turning
the positive way (round 1 turned the negative way). Writes truth.json beside
the masks. Covers what round 1 could not: a near top-down ring and the other
rotation direction.
"""
import json
import os
import sys

import cv2
import numpy as np

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
W, H, F = 2240, 2240, 15000.0  # tall enough that the top-down orbit stays in frame
LENGTH, DIAM = 21.8, 8.6
RINGS = [(80.0, 333.0, 40), (45.0, 350.0, 45), (10.0, 360.0, 50)]  # elevation deg, distance mm, shots
STEP = np.radians(12.0)
OFF = np.array([6.5, 1.0, DIAM / 2])  # capsule centre: off the table axis, resting on the table

rng = np.random.default_rng(0)
u = rng.normal(size=(40000, 3))
u /= np.linalg.norm(u, axis=1, keepdims=True)
half_cyl = (LENGTH - DIAM) / 2
surf = u * DIAM / 2 + np.sign(u[:, :1]) * np.array([half_cyl, 0, 0])  # capsule along x: sphere split and pulled apart
yaw = np.radians(35.0)
surf = surf @ np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]]).T

n = 0
for elev, dist, shots in RINGS:
    phi = np.radians(elev)
    Rk = np.array([[0, 1, 0], [np.sin(phi), 0, -np.cos(phi)], [-np.cos(phi), 0, -np.sin(phi)]])
    c = dist * np.array([np.cos(phi), 0, np.sin(phi)])
    for i in range(shots):
        th = 0.4 + STEP * i
        Rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
        pc = ((surf + OFF) @ Rz.T - c) @ Rk.T
        px = np.stack([F * pc[:, 0] / pc[:, 2] + W / 2, F * pc[:, 1] / pc[:, 2] + H / 2], -1)
        mask = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask, cv2.convexHull(px.astype(np.float32)).astype(np.int32), 255)
        cv2.imwrite(os.path.join(out, f"SYN{n:04d}.png"), mask)
        n += 1
with open(os.path.join(out, "truth.json"), "w") as fh:
    json.dump({"elev_deg": [r[0] for r in RINGS], "dist_mm": [r[1] for r in RINGS], "shots": [r[2] for r in RINGS],
               "step_deg": 12.0}, fh)
print(n, "masks ->", out)
