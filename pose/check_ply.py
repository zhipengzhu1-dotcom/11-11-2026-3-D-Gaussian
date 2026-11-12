"""Sanity-check a trained splat: count, extent, and a crude point projection into one training camera.

usage: check_ply.py <final.ply> <frame_index> <out.jpg> <fit.npz> <dataset_images_dir>
"""
import sys

import cv2
import numpy as np

ply, frame, out, fit, image_dir = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
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
col = {p: data[:, i] for i, p in enumerate(props)}
xyz = np.stack([col["x"], col["y"], col["z"]], -1)
opac = 1 / (1 + np.exp(-col["opacity"]))
rgb = np.clip(0.5 + 0.2820948 * np.stack([col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]], -1), 0, 1)
lo, hi = np.percentile(xyz, [1, 99], axis=0)
print(f"{n} splats, {len(props)} properties; 1-99% extent (scene units = cm): {(hi - lo).round(2)}; "
      f"median opacity {np.median(opac):.2f}; finite: {np.isfinite(data).all()}")

d = np.load(fit)
R, t, f = d["R"][frame], d["t"][frame] * 0.1, float(d["f"])
(cx, cy), (w, h) = d["c"], (int(s) // 2 for s in d["size"])
pc = xyz @ R.T + t
u = (f * pc[:, 0] / pc[:, 2] + cx) / 2
v = (f * pc[:, 1] / pc[:, 2] + cy) / 2
img = np.zeros((h, w, 3), np.float32)
order = np.argsort(-pc[:, 2])
ok = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (opac > 0.2)
for i in order[ok[order]]:
    img[int(v[i]), int(u[i])] = rgb[i, ::-1]
img = cv2.dilate(img, np.ones((2, 2)))
gt = cv2.imread(f"{image_dir}/{d['stems'][frame]}.png", cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
gt = cv2.resize(gt[..., :3] * gt[..., 3:], (w, h), interpolation=cv2.INTER_AREA)
cv2.imwrite(out, (np.concatenate([img, gt], 1) * 255).astype(np.uint8))
