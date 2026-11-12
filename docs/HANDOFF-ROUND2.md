# Handoff: Round-2 capsule splat

Goal: a Gaussian splat of the Round-2 turntable photos that keeps the capsule and its reflection on the table, delivered as `projects\round2\final.ply`, `final-viewer.html` and a 1:1 orbit video.

Root folder: the repository root. Paths below are relative to it.

Read `HANDOFF.md` first. It holds the route, the driver's stages and gates, and what to do when a gate fails. This document holds only what is specific to Round 2.

## State on 2026-11-12

| Item | Where | Status |
|---|---|---|
| Raw photos | `assets\Round-2` | 189 `.ARW`, DSC04869 to DSC05057 |
| Developed frames | `assets\Round-2-Edited` | 189 RGB PNGs, 7008×4672, no alpha. Another session developed them with one fixed recipe; their consistency is unchecked here |
| Capture notes | `assets\Round-2\capture.md` | camera-recorded half filled in; the user's half is blank |
| Solver settings | `projects\round2\shoot.json` | ring boundaries from the pauses between shots, `reflection: true` |
| Masks | `assets\Round-2-Mask`, `assets\Round-2-Cutout` | made 2026-11-12 with `cutout\` (SAM2 video for the capsule, colour-keyed cyan glow for the reflection); `measure.py` passes, 3 rings, no FAIL or WARNING |
| Solver and driver | `pose\run_turntable.py` | verified on Round 1 and on a synthetic shoot, never run on Round 2 |

The shoot has three camera heights: frames 0–64, 65–123 and 124–188. The set includes steep, near top-down views.

## Steps

### 1. Get the missing capture facts from the user

Ask for the blanks in `assets\Round-2\capture.md`: the capsule's real length in mm, which ring is which camera height, and whether the capsule was touched between heights. Write the answers into `capture.md`, and put the length into `shoot.json` as `capsule_length_mm`.

Done when `capture.md` has no blanks, or the user has said which ones to leave. Without the length the scale stays nominal; say so in the final report.

### 2. Make two sets of masks

The user plans to separate the layers of the developed frames. Ask how they want it done; no cutout method has been chosen.

Produce, for the same frames and under identical file names:

| Folder (suggested) | Content | Read by |
|---|---|---|
| `assets\Round-2-Cutout` | RGBA PNG: colour from `Round-2-Edited`, alpha = capsule plus reflection | Brush |
| `assets\Round-2-Mask` | PNG whose alpha or single channel = capsule alone | the solver |

Keep every file at the full 7008×4672 frame; the driver crops. Each capsule mask must be one solid piece that stays clear of the frame edge.

If frames are dropped, renumber `rings` in `shoot.json`: indices count the sorted mask files from 0, end-exclusive.

Done when both folders hold the same file names and this prints three rings with no `FAIL` or `WARNING`:

```
pose\.venv\Scripts\python.exe pose\measure.py assets\Round-2-Mask projects\round2\solve\measure.npz
```

Create `projects\round2\solve\` first. The rings it detects should match `shoot.json`; a mismatch means a mask is wrong or a frame is missing.

### 3. Run the driver

```
pose\.venv\Scripts\python.exe pose\run_turntable.py projects\round2 --images assets\Round-2-Cutout --solver-masks assets\Round-2-Mask
```

Expect 10 to 20 minutes: the `prep` stage reads 378 full-frame PNGs before the GPU work starts.

Done when it prints `done:` and exits 0. On a failed gate, follow "When a gate fails" in `HANDOFF.md`.

### 4. Inspect the two things Round 2 does for the first time

Do the inspection in `HANDOFF.md` step 3, then these:

- **Steep ring.** In `projects\round2\solve\fit_report.json`, each ring's `elev_deg` must agree with the heights the user gave in step 1. A near top-down ring is verified only on synthetic masks.
- **Reflection.** In `projects\round2\check\eval_6000\images`, the reflection must sit below the capsule, attached to it, in the held-out renders. `reflection: true` seeds start points mirrored through the table, and this is its first real use.

If the reflection is missing or detached while the capsule itself looks right, the poses are good and the reflection is the problem. Rerun from `export` with `reflection` set to `false` and compare. If that is no better, train a capsule-only splat (`--images` pointing at capsule-only RGBA cutouts) and report the reflection as unsolved.

Done when both checks pass, or the fallback result is in hand and the difference is written down for the user.

### 5. Video

Follow `HANDOFF.md` step 4. Before rendering, set the elevation range in `pose\make_track.py` (currently 6° to 28°, Round 1's heights) to sit inside Round 2's `elev_deg` values.

Done when a contact sheet of the video shows capsule and reflection centred, upright and intact from every angle.

### 6. Report to the user

State what was produced and where, the held-out PSNR, each ring's recovered height, whether the reflection worked, and whether the scale is measured or nominal. Include the limits listed at the end of `HANDOFF.md`. Ask the user to open the viewer and the video themselves.

## Round-2 risks

- **White balance.** The camera was on Auto, and the raw white balance drifts between frames. If held-out PSNR is low while silhouette IoU is good, compare colour across neighbouring frames in `Round-2-Edited` before touching the solver.
- **Reflection in the solver mask.** If any part of the reflection leaks into `Round-2-Mask`, the solver fits it as capsule shape. Symptoms: IoU below 0.99 or a lumpy underside in `fit_overlay.jpg`.
- **Lights fixed to the room.** Highlights and the reflection's brightness change as the capsule turns, so expect them softer than in the photos.

## Result, 2026-11-12

Done: `projects\round2\final.ply`, `final-viewer.html`, `orbit.mp4` (1080×1080, 12 s, elevation 6–24° via `make_track.py ... 6 24`).

| Ring | IoU mean | Solved height | Height estimated from silhouettes | Step |
|---|---|---|---|---|
| 0 | 0.9935 | 26.1° | ~23° | 8.2° per median interval |
| 1 | 0.9931 | 15.1° | ~12° | 8.2° |
| 2 | 0.9925 | 4.5° | ~3° | 8.3° |

Held-out PSNR 26.51 dB. Scale is measured (capsule 20 mm). The reflection rendered attached under the capsule with `reflection: true`. No ring is near top-down; the user did not remember the heights, so they are checked only against the silhouette estimate.

**Uneven shot timing.** The first fit failed every ring (uneven steps, centroids off the ellipse) because the camera fired at ~0.37 s for the first ~25 shots of each ring, then at 0.5–1.2 s once its buffer filled, while the table turned at constant speed. Fix: `capture_info.py --times` writes `projects\round2\frame_times.json`, and the new `shoot.json` key `frame_times` makes `fit_turntable.py` use capture time instead of frame index. Without the key it behaves as before. Any burst-mode shoot needs it.
