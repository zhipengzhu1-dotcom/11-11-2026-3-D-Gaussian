"""Turntable capsule photos -> final.ply, in one command. Stops at the first failed gate.

usage: run_turntable.py <project_dir> --images DIR [--solver-masks DIR] [--crop auto|none|WxH]
                        [--stages prep,measure,fit,export,check,final,viewer]

--images        RGBA PNGs Brush trains on; alpha = everything to keep (capsule, and its reflection if wanted).
--solver-masks  PNGs whose alpha (or single channel) is the capsule alone. Needed when --images keeps
                the reflection; defaults to the alpha of --images.
<project_dir>/shoot.json holds per-shoot settings (keys: see shoot.py). It is optional.

Outputs under <project_dir>: solve/ (measure.npz, fit.npz, fit_overlay.jpg, fit_report.json),
dataset/, check/, final.ply, final-viewer.html.
"""
import argparse
import os
import subprocess
import sys

import numpy as np

from shoot import load_config

POSE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(POSE)
OOO = os.path.join(ROOT, "ooosplat")
BRUSH = os.path.join(OOO, "engines", "brush", "brush_app.exe")
SPLAT_TRANSFORM = os.path.join(OOO, "node_modules", "@playcanvas", "splat-transform", "bin", "cli.mjs")
STAGES = ["prep", "measure", "fit", "export", "check", "final", "viewer"]

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--images", required=True)
ap.add_argument("--solver-masks")
ap.add_argument("--crop", default="auto")
ap.add_argument("--stages", default=",".join(STAGES))
ap.add_argument("--check-iters", type=int, default=6000)
ap.add_argument("--final-iters", type=int, default=30000)
args = ap.parse_args()

proj = os.path.abspath(args.project)
solve, dataset, check = (os.path.join(proj, d) for d in ("solve", "dataset", "check"))
os.makedirs(solve, exist_ok=True)
cfg_path = os.path.join(proj, "shoot.json")
cfg_path = cfg_path if os.path.exists(cfg_path) else None
cfg = load_config(cfg_path)
stages = args.stages.split(",")
bad = [s for s in stages if s not in STAGES]
if bad:
    sys.exit(f"unknown stages {bad}; choose from {STAGES}")

if args.crop == "none":
    images = os.path.abspath(args.images)
    masks = os.path.abspath(args.solver_masks) if args.solver_masks else images
    stages = [s for s in stages if s != "prep"]
else:
    images = os.path.join(dataset, "images")
    masks = os.path.join(solve, "masks") if args.solver_masks else images


def run(stage, cmd, cwd=None, log=None):
    print(f"\n== {stage} ==", flush=True)
    if log:
        with open(log, "w") as fh:
            code = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT).returncode
    else:
        code = subprocess.run(cmd, cwd=cwd).returncode
    if code:
        sys.exit(f"\nstopped: stage '{stage}' failed (exit {code})" + (f"; see {log}" if log else ""))


def py(script, *a):
    return [sys.executable, os.path.join(POSE, script), *a]


def brush(iters, out_dir, name, *extra):
    longest = str(max(int(v) for v in np.load(os.path.join(solve, "fit.npz"))["size"]))
    return [BRUSH, "--total-train-iters", str(iters), "--max-resolution", longest, "--alpha-mode", "transparent",
            *extra, "--export-every", str(iters), "--export-path", out_dir, "--export-name", name, dataset]


for stage in stages:
    if stage == "prep":
        cmd = py("prepare.py", os.path.abspath(args.images), images, "--crop", args.crop)
        if args.solver_masks:
            cmd += ["--solver-masks", os.path.abspath(args.solver_masks), "--out-masks", masks]
        run(stage, cmd)
    elif stage == "measure":
        run(stage, py("measure.py", masks, os.path.join(solve, "measure.npz")))
    elif stage == "fit":
        run(stage, py("fit_turntable.py", masks, os.path.join(solve, "measure.npz"), solve,
                      *(["--config", cfg_path] if cfg_path else [])))
    elif stage == "export":
        run(stage, py("export_colmap.py", os.path.join(solve, "fit.npz"), images, dataset,
                      *(["--mirror-init"] if cfg["reflection"] else [])))
    elif stage == "check":
        n = args.check_iters
        run(stage, brush(n, check, "check.ply", "--eval-split-every", "8", "--eval-every", str(n), "--eval-save-to-disk"),
            log=os.path.join(proj, "brush-check.log"))
        run("check score", py("psnr.py", os.path.join(check, f"eval_{n}", "images"), os.path.join(dataset, "images"),
                              "--min", str(cfg["min_psnr"])))
    elif stage == "final":
        run(stage, brush(args.final_iters, proj, "final.ply"), log=os.path.join(proj, "brush-final.log"))
        if not os.path.exists(os.path.join(proj, "final.ply")):
            sys.exit("stopped: Brush exited 0 but wrote no final.ply")
    elif stage == "viewer":
        run(stage, ["node", SPLAT_TRANSFORM, "-w", os.path.join(proj, "final.ply"), os.path.join(proj, "final-viewer.html")],
            cwd=OOO)
print(f"\ndone: {proj}")
