"""v2: develop every Sony ARW to a full-resolution 8-bit sRGB PNG with ONE fixed recipe, brighter and denoised.

Same for every frame: white balance, gain, tone curve, denoise strength. Nothing is fitted per image.

usage: python develop_v2.py <raw_dir> <out_dir> [stats.json] [stem ...]
"""
import sys, glob, os, io, json, time
from multiprocessing import Pool
import numpy as np
import cv2
from PIL import Image
from recipe2 import develop_linear, tone_lut, WB, CROP

GAIN = 7.0            # linear, +2.81 EV: white table lands near 203/255 in the top-down ring
KNEE = 0.75           # linear below this (the table stays linear); highlights above roll off, never clip
NLM = (2.5, 8.0)      # non-local-means strength: luminance, colour (5 px patch, 15 px search)
PNG_LEVEL = 4
LUT = tone_lut(GAIN, KNEE)


def develop(job):
    src, dst = job
    cv2.setNumThreads(2)
    stem = os.path.basename(src)[:-4]
    out = {"name": stem}
    lin, thumb = develop_linear(src)
    rgb = LUT[lin]
    del lin
    rgb = cv2.fastNlMeansDenoisingColored(rgb, None, NLM[0], NLM[1], 5, 15)
    exif = None
    if thumb:
        try:
            exif = Image.open(io.BytesIO(thumb)).getexif()
            exif[0x0112] = 1
        except Exception as e:
            out["exif_err"] = repr(e)
    im = Image.fromarray(rgb)
    path = os.path.join(dst, stem + ".png")
    tmp = path + ".part"
    try:
        im.save(tmp, format="PNG", compress_level=PNG_LEVEL, **({"exif": exif} if exif is not None else {}))
    except Exception as e:
        out["exif_err"] = repr(e)
        im.save(tmp, format="PNG", compress_level=PNG_LEVEL)
    for attempt in range(60):                 # Explorer's thumbnailer can hold the old file open for a moment
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 59:
                raise
            time.sleep(0.5)

    h, w = rgb.shape[:2]
    out["size"] = [w, h]
    out["bytes"] = os.path.getsize(path)
    out["hi"] = int((rgb.max(axis=2) >= 255).sum())
    out["lo"] = int((rgb.min(axis=2) <= 0).sum())
    s = rgb[::2, ::2].astype(np.float32) / 255.0
    lin = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)
    g = lin[..., 1]
    g99 = np.percentile(g, 99)
    m = (g > 0.6 * g99) & (g < 1.05 * g99)
    out["surf_lin"] = [float(np.median(lin[..., c][m])) for c in range(3)]
    out["surf_srgb"] = [float(np.median(rgb[::2, ::2, c][m])) for c in range(3)]
    y8 = 0.2126 * rgb[::2, ::2, 0] + 0.7152 * rgb[::2, ::2, 1] + 0.0722 * rgb[::2, ::2, 2]
    out["lum_pct"] = [float(v) for v in np.percentile(y8, [0.1, 1, 50, 99, 99.9])]
    out["max"] = [int(rgb[..., c].max()) for c in range(3)]
    # noise left on a flat patch of table (left-centre of frame), luminance high-pass
    p = cv2.cvtColor(np.ascontiguousarray(rgb[2136:2536, 700:1100]), cv2.COLOR_RGB2GRAY).astype(np.float32)
    out["noise"] = float((p - cv2.GaussianBlur(p, (0, 0), 6)).std())
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    stats = sys.argv[3] if len(sys.argv) > 3 else None
    only = set(sys.argv[4:])
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, "*.ARW")))
    if only:
        files = [f for f in files if os.path.basename(f)[:-4] in only]
    t0 = time.time()
    rows = []
    with Pool(min(12, len(files))) as pool:
        for i, row in enumerate(pool.imap(develop, [(f, dst) for f in files]), 1):
            rows.append(row)
            if i % 20 == 0 or i == len(files):
                print(f"{i}/{len(files)}  {row['name']}  {time.time() - t0:.0f}s", flush=True)
    if stats:
        json.dump({"recipe": {"wb": WB, "gain": GAIN, "knee": KNEE, "nlm": NLM, "crop": CROP}, "frames": rows},
                  open(stats, "w"), indent=1)
    print("done:", len(rows), "frames in", f"{time.time() - t0:.0f}s")
