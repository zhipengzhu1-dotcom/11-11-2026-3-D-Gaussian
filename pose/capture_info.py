"""Read what the camera recorded about a shoot: lens, exposure, white balance and pauses between shots.

usage: capture_info.py <originals_dir> [--times <out.json>]      (.ARW or .JPG)

--times writes each frame's capture time in seconds (sorted order), for shoot.json "frame_times".

A long pause usually means the camera was moved to a new height, so the pauses
give ring boundaries that do not depend on the masks.
"""
import glob
import os
import sys
from datetime import datetime

import exifread
import numpy as np

times_out = sys.argv[sys.argv.index("--times") + 1] if "--times" in sys.argv else None
files = sorted(p for p in glob.glob(os.path.join(sys.argv[1], "*")) if p.lower().endswith((".arw", ".jpg", ".jpeg")))
if not files:
    sys.exit(f"no .ARW or .JPG files in {sys.argv[1]}")
KEYS = {"focal mm": "EXIF FocalLength", "aperture": "EXIF FNumber", "shutter": "EXIF ExposureTime",
        "iso": "EXIF ISOSpeedRatings", "white balance": "EXIF WhiteBalance", "lens": "EXIF LensModel",
        "camera": "Image Model", "exposure mode": "EXIF ExposureMode"}
seen = {k: {} for k in KEYS}
times = []
for p in files:
    with open(p, "rb") as fh:
        tags = exifread.process_file(fh, details=False)
    for k, tag in KEYS.items():
        v = str(tags.get(tag, "?"))
        seen[k][v] = seen[k].get(v, 0) + 1
    t = str(tags.get("EXIF DateTimeOriginal", ""))
    sub = str(tags.get("EXIF SubSecTimeOriginal", "0"))
    times.append(datetime.strptime(t, "%Y:%m:%d %H:%M:%S").timestamp() + float("0." + sub) if t else np.nan)

print(f"{len(files)} files, {os.path.basename(files[0])} .. {os.path.basename(files[-1])}")
for k, counts in seen.items():
    print(f"{k:14s}", ", ".join(f"{v} (x{n})" for v, n in sorted(counts.items(), key=lambda kv: -kv[1])))
gaps = np.diff(times)
med = np.nanmedian(gaps)
print(f"time between shots: median {med:.1f} s")
cuts = [i + 1 for i, g in enumerate(gaps) if g > max(4 * med, med + 10)]
edges = [0] + cuts + [len(files)]
print("rings by pauses:", [[a, b] for a, b in zip(edges[:-1], edges[1:])])
for c in cuts:
    print(f"  pause of {gaps[c - 1]:.0f} s before frame {c} ({os.path.basename(files[c])})")
if times_out:
    import json
    with open(times_out, "w") as fh:
        json.dump([round(float(t) - float(times[0]), 3) for t in times], fh)
    print(f"wrote {len(times)} frame times to {times_out}")
