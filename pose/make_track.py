"""Write a seamless-loop orbit camera track (splat-transform JSON) around the capsule.

usage: make_track.py <final.ply> <track.json> [el_min_deg el_max_deg [start_turn]]   (default 6 28 0)
start_turn shifts where the loop begins, in turns (0.5 = start halfway round).
Keep the elevation range inside the solved camera heights in fit_report.json.
"""
import json
import sys

import numpy as np

ply, out = sys.argv[1], sys.argv[2]
EL_MIN, EL_MAX = (float(v) for v in sys.argv[3:5]) if len(sys.argv) >= 5 else (6.0, 28.0)
START = float(sys.argv[5]) if len(sys.argv) >= 6 else 0.0
with open(ply, "rb") as fh:
    props, n = [], 0
    while True:
        line = fh.readline().decode().strip()
        if line.startswith("element vertex"):
            n = int(line.split()[-1])
        elif line.startswith("property"):
            props.append(line.split()[-1])
        elif line == "end_header":
            break
    data = np.frombuffer(fh.read(n * len(props) * 4), dtype="<f4").reshape(n, len(props))
xyz = data[:, :3]
lo, hi = np.percentile(xyz, [2, 98], axis=0)
centre = (lo + hi) / 2
print("centre", centre.round(3), "extent", (hi - lo).round(3))

FPS, SECONDS, DIST, FOV = 30, 12, 35.0, 5.0
frames = []
N = FPS * SECONDS
for i in range(N):
    u = i / N + START
    az = 2 * np.pi * u
    el = np.radians((EL_MIN + EL_MAX) / 2 + (EL_MAX - EL_MIN) / 2 * np.sin(2 * np.pi * u))
    pos = centre + DIST * np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    frames.append({"position": pos.tolist(), "target": centre.tolist(), "fov": FOV, "up": [0, 0, 1]})
json.dump({"frameRate": FPS, "frames": frames}, open(out, "w"))
print(N, "frames ->", out)
