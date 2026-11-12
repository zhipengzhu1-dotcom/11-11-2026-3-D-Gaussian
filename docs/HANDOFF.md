# Handoff: Gaussian splat of a capsule on a turntable (no marker mat)

Goal: turn a set of turntable photos of a capsule into `final.ply`, an offline viewer and a 1:1 orbit video.

Root folder: the repository root. Paths below are relative to it.

## Why the standard route fails

A turntable shoot has a fixed camera and a rotating object, so the background is static and gives no camera motion. A clear softgel on a plain table has no stable texture either. On the first set COLMAP registered 2 of 156 cutouts and 4 of 156 uncropped originals, and VGGT's poses on the cutouts were too noisy to use. Skip all three: `splatstudio generate`, COLMAP on any variant of the images, and VGGT.

The route that works is **silhouette poses**: recover the turntable geometry from capsule masks, write the cameras in COLMAP text format, and train with ooosplat's bundled Brush directly. `pose\run_turntable.py` does all of it in one command and stops at the first failed gate.

## What is installed

| Thing | Path (under the root) |
|---|---|
| Driver and stage scripts | `pose\run_turntable.py`, `pose\*.py` |
| Python 3.12 + CUDA PyTorch, OpenCV, SciPy, exifread | `pose\.venv\Scripts\python.exe` |
| Brush trainer (headless, has no viewer) | `ooosplat\engines\brush\brush_app.exe` |
| Renderer and HTML viewer export | `ooosplat\node_modules\@playcanvas\splat-transform\bin\cli.mjs` |
| Round 1, for reference | `assets\capsule`, `assets\capsule_cutout`, `projects\capsule_turntable` |
| Round 2 | `assets\Round-2` (189 `.ARW`), `assets\Round-2-Edited` (developed RGB PNGs, 7008×4672), `projects\round2\shoot.json` |

Leftovers from round 1's exploration, used by nothing: `pose\vggt\`, `pose\run_vggt.py`, `pose\analyze.py`, `pose\crop_offsets.py`, and the `.npz`, `.json` and `.jpg` files directly in `pose\`.

## Inputs

1. **Brush images**: RGBA PNGs, one per frame. Alpha marks everything the splat should keep: the capsule, plus its reflection if wanted.
2. **Solver masks**, required when the Brush alpha includes the reflection: PNGs with the same file names whose alpha (or single channel) is the capsule alone. The solver reads the mask as the capsule's outline, so a reflection in it corrupts the fit.
3. **`capture.md`** beside the originals. `python capture_info.py <originals_dir>` prints the camera-recorded half (lens, exposure, white balance, rings from pauses between shots); the user supplies the rest.

Every frame must be the full camera frame or the same centred crop of it: the solver assumes the lens axis is at the image centre. The driver's own crop keeps this true.

As of 2026-11-12 round 2 has no masks yet. If the user has only developed RGB frames, ask how they want the cutouts made.

## Steps

### 1. Write `shoot.json` in the project folder

All keys are optional; `DEFAULTS` in `pose\shoot.py` lists every key with its meaning. The ones a new shoot usually sets:

| Key | Set it when |
|---|---|
| `capsule_length_mm` | the real length is known. It sets the scale; the default 21.8 is round 1's nominal value |
| `rings` | you have ring boundaries from `capture_info.py`. Otherwise they are detected from centroid jumps |
| `reflection` | the Brush alpha keeps the reflection. Seeds extra start points mirrored through the table |
| `focal_mm` | the lens was not at 70 mm |

Frame indices in `rings` count the sorted mask files from 0, end-exclusive. Dropping a frame shifts them.

### 2. Run the driver

```
pose\.venv\Scripts\python.exe pose\run_turntable.py projects\<name> --images <rgba_dir> [--solver-masks <mask_dir>]
```

About 10 minutes for 156 frames on the RTX 5090. `--stages fit,export,check` reruns part of it; `--crop none` uses the images as they are.

| Stage | Does | Stops when |
|---|---|---|
| `prep` | crops images and masks to one centred window | a mask is empty, sizes or names differ |
| `measure` | per-frame silhouette centroid and size, ring detection | a mask is empty or has stray pieces, a ring has under 8 shots |
| `fit` | solves camera heights, distances and per-frame table angle | a ring's mean IoU < 0.99, rotation steps are uneven, centroids do not trace an ellipse |
| `export` | writes `dataset\` (images, COLMAP cameras, start points) | an image is missing or not RGBA at the mask size |
| `check` | 6,000-iteration Brush run holding out every 8th view, then PSNR | held-out PSNR < 23 dB |
| `final` | 30,000-iteration Brush run on all views | no `final.ply` |
| `viewer` | `final-viewer.html` | |

Done when the driver prints `done:` and exits 0.

### 3. Inspect what the gates cannot see

- `solve\fit_overlay.jpg`: silhouettes are white with at most a thin green or magenta fringe.
- `solve\fit_report.json`: each ring's `elev_deg` agrees with the camera heights in `capture.md`.
- `check\eval_6000\images` beside `dataset\images`: outline, liquid level and colour match.

Done when all three hold. Round 1 scores for comparison: IoU 0.994, 0.994, 0.991; steps about 12.7° ± 1°; held-out PSNR 24.6 dB.

### 4. Video

From `ooosplat\`:

```
python ..\pose\make_track.py <final.ply> <track.json>
node node_modules\@playcanvas\splat-transform\bin\cli.mjs -w <final.ply> <frames_dir>\orbit.webp --camera-track <track.json> --resolution 1080x1080 --camera-up 0,0,1 --background 0.03,0.03,0.035,1
ffmpeg -framerate 30 -start_number 0 -i <frames_dir>\orbit.%04d.webp -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart <out.mp4>
```

`make_track.py` holds the orbit settings (12 s at 30 fps, distance 35, FOV 5°, elevation 6–28°). Keep the elevation inside the camera heights in `fit_report.json`, so unphotographed surfaces stay out of view.

Done when a contact sheet of the video shows the capsule centred, upright and intact from every angle, and the user has opened the viewer and video themselves.

## When a gate fails

- **Uneven rotation steps mean a model problem, not noise.** Round 1's first fit gave 10° steps with periodic 24° bursts because the capsule had shifted between rings. Per-ring offsets (`P["off"]`) fixed that. Look for the next thing the model assumes fixed that the shoot changed.
- **Centroids off an ellipse**: wrong ring boundaries. Compare `measure` with `capture_info.py` and set `rings`.
- **"masks touch the frame edge" warning**: a cut-off silhouette biases the starting camera height. On a synthetic top-down ring this passed every gate with the height 9° wrong. Widen the crop, then confirm `elev_deg` against `capture.md`.
- **Low PSNR with good IoU**: suspect the images (inconsistent white balance or exposure between frames) before the poses.
- **Brush prints nothing to its log.** Success is exit code 0 and the `.ply` on disk.

## What has been verified

On 2026-11-12, after the solver was made configurable:

- Round 1 with its original constants in `shoot.json`: same IoU, poses within 0.25°.
- Round 1 padded to a larger frame, fully automatic (auto crop, separate solver masks, detected rings, derived distances): IoU 0.994, 0.994, 0.991 and held-out PSNR 24.55 dB.
- `pose\synthetic_shoot.py` (rings at 80°, 45°, 10°, table turning the other way): heights recovered to 0.2°, steps to 0.02°.
- Wrong ring boundaries stop the driver at `fit` with exit 1.

Unverified on real photos: a near top-down ring, `reflection: true` (the mirrored start points), and any ring count other than 3.

## Known limits to tell the user

- Poses from silhouettes are good to a few pixels, so fine scratches and sharp highlights come out soft.
- Lights fixed in the room move relative to a rotating capsule, so reflections smear.
- The underside is never photographed unless the capsule is flipped for a second pass.
- Scale is nominal unless `capsule_length_mm` is measured (scene units are centimetres).
- For publication, describe the method as ooosplat's Brush engine plus a custom silhouette pose solver; ooosplat's own pipeline does not handle this capture.
