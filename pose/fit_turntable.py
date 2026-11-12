"""Recover turntable camera geometry from capsule silhouettes.

usage: fit_turntable.py <mask_dir> <measure.npz> <out_dir> [--config shoot.json]

Model: the capsule sits on a turntable (axis = world z). Each camera height is
a ring: a fixed camera with slow pan/tilt creep. Per frame the table angle
theta is free. A voxel occupancy grid in the capsule's own frame is learned
jointly, by matching rendered silhouettes to the masks.

Writes fit.npz, fit_overlay.jpg and fit_report.json into <out_dir>.
Exits 1 when a gate fails (the outputs are still written, for diagnosis).
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
import torch
import torch.nn.functional as Fn
from scipy.optimize import least_squares

from shoot import list_pngs, load_config, read_mask, stem

ap = argparse.ArgumentParser()
ap.add_argument("mask_dir")
ap.add_argument("measure")
ap.add_argument("out_dir")
ap.add_argument("--config")
args = ap.parse_args()
cfg = load_config(args.config)
os.makedirs(args.out_dir, exist_ok=True)
failures = []

torch.manual_seed(0)
dev = "cuda"
meas = np.load(args.measure)
m = meas["rows"]
W, H = (int(v) for v in meas["size"])
names = list_pngs(args.mask_dir)
N = len(names)
if N != len(m):
    sys.exit(f"FAIL: {N} masks in {args.mask_dir} but {len(m)} rows in {args.measure}; rerun measure.py")

RINGS = [tuple(int(v) for v in r) for r in (cfg["rings"] or meas["rings"].tolist())]
K = len(RINGS)
if [a for a, _ in RINGS] + [RINGS[-1][1]] != [0] + [b for _, b in RINGS] or RINGS[-1][1] != N:
    sys.exit(f"FAIL: rings {RINGS} must be end-exclusive, contiguous and cover frames 0-{N - 1}")

# Per-ring time axis in units of the ring's median shot interval. Without frame_times the shots are
# taken as evenly spaced, so this is just the frame index within the ring.
TIX = np.zeros(N)
for a, b in RINGS:
    if cfg["frame_times"]:
        if len(cfg["frame_times"]) != N:
            sys.exit(f"FAIL: frame_times has {len(cfg['frame_times'])} values for {N} frames")
        t = np.asarray(cfg["frame_times"][a:b], dtype=np.float64)
        TIX[a:b] = (t - t[0]) / np.median(np.diff(t))
    else:
        TIX[a:b] = np.arange(b - a)
if cfg["frame_times"]:
    print("using frame_times: shot spacing per ring (median intervals):",
          [round(float(TIX[b - 1]), 1) for a, b in RINGS], "for", [b - a - 1 for a, b in RINGS], "gaps")

F_PX = float(cfg["f_px"] or cfg["focal_mm"] / cfg["sensor_width_mm"] * cfg["full_width_px"] * cfg["close_focus_factor"])
CX, CY = W / 2, H / 2
L_MM = float(cfg["capsule_length_mm"])
# The capsule lies flat, so each ring sees its full length side-on at some table angle.
D_INIT = [float(d) for d in (cfg["d_init_mm"] or [F_PX * L_MM / m[a:b, 6].max() for a, b in RINGS])]
if len(D_INIT) != K:
    sys.exit(f"FAIL: d_init_mm has {len(D_INIT)} values for {K} rings")
D0 = D_INIT[0]           # ring 0 distance is the fixed scale reference
HALF = float(cfg["half_mm"] or round(0.6 * L_MM, 1))
a0, b0 = RINGS[0]
CH = float(cfg["center_height_mm"] or 0.5 * np.median(m[a0:b0, 7]) * D0 / F_PX)
DS = int(cfg["ds"] or max(1, math.ceil(W / 1200)))
print(f"{N} frames {W}x{H}, {K} rings {RINGS}")
print(f"f {F_PX:.0f} px, start distances mm {np.round(D_INIT, 1).tolist()}, grid half {HALF} mm, "
      f"centre height {CH:.2f} mm, mask downsample {DS}")

masks = []
for n in names:
    masks.append(cv2.resize(read_mask(n), (W // DS, H // DS), interpolation=cv2.INTER_AREA))
masks = torch.tensor(np.array(masks), dtype=torch.float32, device=dev)[:, None] / 255.0

# ---------- initial guess from silhouette centroids ----------
cx, cy = m[:, 0], m[:, 1]
PERIODS = [cfg["shots_per_rev"]] if cfg["shots_per_rev"] else [12, 16, 20, 24, 28, 32, 36, 40, 48, 60, 72, 90]


def fit_ring(a, b):
    """Least-squares ellipse path for one ring's centroids: x = A sin(th), y = B cos(th), plus linear drift."""
    i = TIX[a:b]

    def resid(p):
        ax, bu, A, av, bv, B, ph, om = p
        th = ph + om * i
        return np.concatenate([ax + bu * i + A * np.sin(th) - cx[a:b], av + bv * i + B * np.cos(th) - cy[a:b]])

    best = None
    A0 = (cx[a:b].max() - cx[a:b].min()) / 2
    for per in PERIODS:
        for ph in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            for om in (-2 * np.pi / per, 2 * np.pi / per):
                s = least_squares(resid, [cx[a:b].mean(), 0, A0, cy[a:b].mean(), 0, A0 * 0.3, ph, om])
                if best is None or s.cost < best.cost:
                    best = s
    p = list(best.x)
    if p[2] < 0:  # A > 0
        p[2], p[5], p[6] = -p[2], -p[5], p[6] + np.pi
    return p, np.sqrt(best.cost / (b - a))


def flip(p):
    """The same centroid path with the table turning the other way and the camera mirrored through the table."""
    p[7], p[6], p[5] = -p[7], np.pi - p[6], -p[5]


fits = [fit_ring(a, b) for a, b in RINGS]
# Direction is ambiguous per ring. The camera is above the table (B > 0), which settles
# it for the most elevated ring; every other ring turns the same way.
ref = int(np.argmax([abs(p[5]) / p[2] for p, _ in fits]))
if fits[ref][0][5] < 0:
    flip(fits[ref][0])
for p, _ in fits:
    if np.sign(p[7]) != np.sign(fits[ref][0][7]):
        flip(p)

ring_of = np.zeros(N, dtype=np.int64)
rel = np.zeros(N)
theta0 = np.zeros(N)
phi0, pan0, tilt0, dpan0, dtilt0, ph_init, om_init, r0_est = [], [], [], [], [], [], [], []
for k, ((a, b), (p, rms)) in enumerate(zip(RINGS, fits)):
    ax, bu, A, av, bv, B, ph, om = p
    i = TIX[a:b]
    ring_of[a:b] = k
    rel[a:b] = i / (b - a)
    phi = np.arcsin(np.clip(B / A, -0.996, 0.996))
    print(f"ring {k}: A {A:.1f} B {B:.1f} elev {np.degrees(phi):.1f} deg  period {2*np.pi/om:.2f} frames  "
          f"drift ({bu*(b-a):.0f},{bv*(b-a):.0f}) px  rms {rms:.1f} px")
    if rms > max(0.1 * A, 15):
        failures.append(f"ring {k} centroids do not follow an ellipse (rms {rms:.0f} px): wrong ring "
                        f"boundaries, or the capsule moved within the ring")
    if B / A < -0.15:
        failures.append(f"ring {k} turns the opposite way to ring {ref}: check the ring boundaries")
    theta0[a:b] = ph + om * i
    ph_init.append(ph); om_init.append(om)
    phi0.append(phi)
    px_per_mm = F_PX / D_INIT[k]
    r0_est.append(A / px_per_mm)
    h_px = CH * px_per_mm * np.cos(phi)
    pan0.append((ax - CX) / F_PX)
    tilt0.append(-(av + h_px - CY) / F_PX)
    dpan0.append(bu * (b - a) / F_PX)
    dtilt0.append(-bv * (b - a) / F_PX)

print("offset from axis (mm):", np.round(r0_est, 2))
idx_in_ring = torch.tensor(TIX, dtype=torch.float32, device=dev)
ring_of_t = torch.tensor(ring_of, device=dev)
rel_t = torch.tensor(rel, dtype=torch.float32, device=dev)
free_d = torch.tensor([0.0] + [1.0] * (K - 1), device=dev)

P = {
    "ph": torch.tensor(ph_init, dtype=torch.float32, device=dev),
    "om": torch.tensor(om_init, dtype=torch.float32, device=dev),
    "dth": torch.zeros(N, device=dev),
    "off": torch.tensor([[r, 0.0, CH] for r in r0_est], dtype=torch.float32, device=dev),  # per ring: the capsule may shift between heights
    "phi": torch.tensor(phi0, dtype=torch.float32, device=dev),
    "logd": torch.tensor(np.log(np.array(D_INIT) / D0), dtype=torch.float32, device=dev),
    "pan": torch.tensor(pan0, dtype=torch.float32, device=dev),
    "tilt": torch.tensor(tilt0, dtype=torch.float32, device=dev),
    "dpan": torch.tensor(dpan0, dtype=torch.float32, device=dev),
    "dtilt": torch.tensor(dtilt0, dtype=torch.float32, device=dev),
    "roll": torch.zeros(K, device=dev),
    "jit": torch.zeros(N, 2, device=dev),   # per-frame pan/tilt residual
}
for v in P.values():
    v.requires_grad_(True)

G = 176
ax_ = torch.linspace(-1, 1, G, device=dev)
zz, yy, xx = torch.meshgrid(ax_, ax_, ax_, indexing="ij")
rad = torch.sqrt(xx**2 + yy**2 + zz**2) * HALF
grid = (2.0 * (HALF * 7.0 / 13.0 - rad)).clamp(-6, 6)[None, None].clone().requires_grad_(True)


def rot(axis, a):
    c, s, o, z = torch.cos(a), torch.sin(a), torch.ones_like(a), torch.zeros_like(a)
    if axis == "x":
        r = [o, z, z, z, c, -s, z, s, c]
    elif axis == "y":
        r = [c, z, s, z, o, z, -s, z, c]
    else:
        r = [c, -s, z, s, c, z, z, z, o]
    return torch.stack(r, -1).reshape(*a.shape, 3, 3)


def theta():
    return P["ph"][ring_of_t] + P["om"][ring_of_t] * idx_in_ring + P["dth"]


def cameras():
    """Per-frame (R, t) mapping capsule-frame points to OpenCV camera coordinates."""
    k = ring_of_t
    phi = P["phi"][k]
    d = D0 * torch.exp(P["logd"][k] * free_d[k])
    c = torch.stack([d * torch.cos(phi), torch.zeros_like(d), d * torch.sin(phi)], -1)
    z, o = torch.zeros_like(phi), torch.ones_like(phi)
    Rk = torch.stack([z, o, z, torch.sin(phi), z, -torch.cos(phi), -torch.cos(phi), z, -torch.sin(phi)], -1).reshape(-1, 3, 3)
    pan = P["pan"][k] + P["dpan"][k] * rel_t + P["jit"][:, 0]
    tilt = P["tilt"][k] + P["dtilt"][k] * rel_t + P["jit"][:, 1]
    Rs = rot("y", pan) @ rot("x", tilt) @ rot("z", P["roll"][k])
    Rz = rot("z", theta())
    M = Rs @ Rk
    R = M @ Rz
    t = (R @ P["off"][k][:, :, None]).squeeze(-1) - (M @ c[:, :, None]).squeeze(-1)
    return R, t


def render(R, t, uv, nsamp=176, jitter=True):
    """uv: (n, B, 2) full-res pixel coords -> silhouette alpha (n, B)."""
    dcam = torch.stack([(uv[..., 0] - CX) / F_PX, (uv[..., 1] - CY) / F_PX, torch.ones_like(uv[..., 0])], -1)
    dobj = torch.einsum("nji,nbj->nbi", R, dcam)
    dobj = dobj / dobj.norm(dim=-1, keepdim=True)
    o = -torch.einsum("nji,nj->ni", R, t)[:, None, :]
    tc = -(o * dobj).sum(-1, keepdim=True)
    span = HALF * 1.75
    steps = torch.linspace(-1, 1, nsamp, device=dev)
    if jitter:
        steps = steps + (torch.rand(nsamp, device=dev) - 0.5) * (2 / nsamp)
    pts = o[:, :, None, :] + dobj[:, :, None, :] * (tc[..., None] + steps[None, None, :, None] * span)
    dens = Fn.grid_sample(grid, (pts / HALF).reshape(1, -1, 1, 1, 3), align_corners=True, padding_mode="zeros")
    inside = (pts.abs() < HALF).all(-1)  # without this every ray saturates and the fit diverges
    dens = Fn.softplus(dens.reshape(pts.shape[:-1])) * inside
    return 1 - torch.exp(-dens.sum(-1) * (2 * span / nsamp))


boxes = []
for i in range(N):
    hw = 2.6 * m[i, 3] + 120
    boxes.append([m[i, 0] - hw, m[i, 0] + hw, m[i, 1] - hw, m[i, 1] + hw])
boxes = torch.tensor(np.array(boxes), dtype=torch.float32, device=dev)


def sample_uv(B):
    r = torch.rand(N, B, 2, device=dev)
    u = boxes[:, None, 0] + r[..., 0] * (boxes[:, None, 1] - boxes[:, None, 0])
    v = boxes[:, None, 2] + r[..., 1] * (boxes[:, None, 3] - boxes[:, None, 2])
    return torch.stack([u.clamp(0, W - 1), v.clamp(0, H - 1)], -1)


def target(uv):
    g = torch.stack([uv[..., 0] / W * 2 - 1, uv[..., 1] / H * 2 - 1], -1)[:, :, None, :]
    return Fn.grid_sample(masks, g, align_corners=False).reshape(uv.shape[0], uv.shape[1])


opt_g = torch.optim.Adam([grid], lr=0.1)
opt_p = torch.optim.Adam([
    {"params": [P["ph"], P["dth"]], "lr": 1e-3},
    {"params": [P["om"]], "lr": 3e-5},
    {"params": [P["off"]], "lr": 5e-3},
    {"params": [P["phi"], P["roll"]], "lr": 1e-3},
    {"params": [P["logd"]], "lr": 5e-4},
    {"params": [P["pan"], P["tilt"], P["dpan"], P["dtilt"]], "lr": 2e-5},
    {"params": [P["jit"]], "lr": 1e-5},
])
WARM, TOTAL = 400, 6000
sched = torch.optim.lr_scheduler.MultiStepLR(opt_p, [4000, 5200], 0.3)
for step in range(TOTAL):
    R, t = cameras()
    uv = sample_uv(1000)
    pred = render(R, t, uv)
    loss = ((pred - target(uv)) ** 2).mean()
    tv = sum((grid.diff(dim=d) ** 2).mean() for d in (2, 3, 4))
    # jit and dth weights are the tuned ones: stiffer cost about 0.9 dB, looser gained nothing.
    reg = 2e-4 * tv + 0.5 * (P["jit"] ** 2).mean() * (F_PX**2) * 1e-6 + 0.1 * (P["dth"] ** 2).mean()
    opt_g.zero_grad(); opt_p.zero_grad()
    (loss + reg).backward()
    opt_g.step()
    if step >= WARM:
        opt_p.step(); sched.step()
    if step % 1000 == 0 or step == TOTAL - 1:
        print(f"step {step:5d} mse {loss.item():.5f} elev {np.degrees(P['phi'].detach().cpu().numpy()).round(2)} "
              f"dist {(D0*torch.exp(P['logd']*free_d)).detach().cpu().numpy().round(1)} "
              f"jit px rms {(P['jit'].detach()*F_PX).pow(2).mean().sqrt().item():.2f}", flush=True)

# ---------- evaluation: IoU per frame, rotation steps, gates ----------
report = {"frames": N, "size": [W, H], "f_px": F_PX, "rings": []}
with torch.no_grad():
    R, t = cameras()
    us = (torch.arange(W // DS, device=dev) + 0.5) * DS
    vs = (torch.arange(H // DS, device=dev) + 0.5) * DS
    vv, uu = torch.meshgrid(vs, us, indexing="ij")
    uv = torch.stack([uu, vv], -1).reshape(1, -1, 2)
    ious, renders = [], []
    for i in range(N):
        p = torch.cat([render(R[i:i+1], t[i:i+1], c, jitter=False) for c in uv.split(1 << 18, dim=1)], 1)
        p = p.reshape(H // DS, W // DS)
        gt = masks[i, 0]
        ious.append(((p > 0.5) & (gt > 0.5)).sum().item() / max(1, ((p > 0.5) | (gt > 0.5)).sum().item()))
        renders.append(p.cpu().numpy())
    ious = np.array(ious)
    th = np.degrees(theta().cpu().numpy())
    elev = np.degrees(P["phi"].cpu().numpy())
    dist = (D0 * torch.exp(P["logd"] * free_d)).cpu().numpy()
    for k, (a, b) in enumerate(RINGS):
        steps = np.diff(th[a:b]) / np.diff(TIX[a:b])  # per median shot interval
        med = float(np.median(steps))
        dev_ = float(np.abs(steps - med).max() / abs(med))
        print(f"ring {k}: IoU mean {ious[a:b].mean():.4f} min {ious[a:b].min():.4f} | elev {elev[k]:.1f} deg "
              f"dist {dist[k]:.0f} mm | step median {med:.2f} deg, range {steps.min():.2f}..{steps.max():.2f}")
        report["rings"].append({"frames": [a, b], "iou_mean": float(ious[a:b].mean()), "iou_min": float(ious[a:b].min()),
                                "elev_deg": float(elev[k]), "dist_mm": float(dist[k]), "step_median_deg": med,
                                "step_min_deg": float(steps.min()), "step_max_deg": float(steps.max()),
                                "offset_mm": P["off"][k].cpu().numpy().round(2).tolist()})
        if ious[a:b].mean() < cfg["min_iou"]:
            failures.append(f"ring {k} mean IoU {ious[a:b].mean():.4f} is below {cfg['min_iou']}")
        if dev_ > cfg["max_step_dev"]:
            failures.append(f"ring {k} rotation steps are uneven ({steps.min():.1f}..{steps.max():.1f} deg, median "
                            f"{med:.1f}): the model is wrong for this ring, not noisy")
    np.savez(os.path.join(args.out_dir, "fit.npz"), R=R.cpu().numpy(), t=t.cpu().numpy(), grid=grid[0, 0].cpu().numpy(),
             ious=ious, names=np.array(names), stems=np.array([stem(n) for n in names]), f=F_PX, half=HALF,
             size=np.array([W, H]), c=np.array([CX, CY]), rings=np.array(RINGS), theta=theta().cpu().numpy(),
             **{k: v.cpu().numpy() for k, v in P.items()})
    # overlay sheet: green = mask only, magenta = model only, white = both
    idx = list(range(0, N, max(1, N // 26)))
    tiles = []
    for i in idx:
        gt = masks[i, 0].cpu().numpy()
        tiles.append(np.stack([renders[i], gt, renders[i]], -1))
    cols = 6
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.concatenate([np.concatenate(tiles[r:r+cols], 1) for r in range(0, len(tiles), cols)], 0)
    cv2.imwrite(os.path.join(args.out_dir, "fit_overlay.jpg"), (sheet * 255).astype(np.uint8)[::2, ::2])

report["failures"] = failures
with open(os.path.join(args.out_dir, "fit_report.json"), "w") as fh:
    json.dump(report, fh, indent=1)
if failures:
    sys.exit("FAIL:\n  " + "\n  ".join(failures))
print("fit passed all gates")
