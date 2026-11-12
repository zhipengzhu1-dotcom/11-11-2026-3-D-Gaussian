"""Shared pieces of the v2 recipe: fixed develop to 16-bit linear, fixed tone curve, fixed-strength denoise."""
import numpy as np
import rawpy

WB = [2.197, 1.0, 1.826, 1.0]   # white table neutral in the top-down ring
BASE_GAIN = 4.5                 # LibRaw stage: nothing clips in any frame at this gain (limit 4.67)
CROP = (12, 8, 7008, 4672)      # camera-JPEG frame inside LibRaw's 7028x4688 output


def develop_linear(path, fbdd=False, noise_thr=None):
    """ARW -> uint16 linear sRGB-primaries image at BASE_GAIN, cropped to the camera frame."""
    kw = {}
    if fbdd:
        kw["fbdd_noise_reduction"] = rawpy.FBDDNoiseReductionMode.Full
    if noise_thr:
        kw["noise_thr"] = float(noise_thr)
    with rawpy.imread(path) as r:
        rgb = r.postprocess(user_wb=WB, use_camera_wb=False, use_auto_wb=False, no_auto_bright=True,
                            adjust_maximum_thr=0.0, exp_shift=BASE_GAIN, exp_preserve_highlights=0.0,
                            highlight_mode=rawpy.HighlightMode.Clip, gamma=(1, 1),
                            output_color=rawpy.ColorSpace.sRGB, output_bps=16,
                            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, user_flip=0, **kw)
        thumb = None
        try:
            t = r.extract_thumb()
            if t.format == rawpy.ThumbFormat.JPEG:
                thumb = bytes(t.data)
        except Exception:
            pass
    x, y, w, h = CROP
    return np.ascontiguousarray(rgb[y:y + h, x:x + w]), thumb


def tone_lut(gain, knee=0.75):
    """uint16 linear (at BASE_GAIN) -> uint8 sRGB. Linear up to `knee`, then a smooth shoulder that
    approaches 1.0 and never reaches it, so highlights compress instead of clipping."""
    x = np.arange(65536, dtype=np.float64) / 65535.0 * (gain / BASE_GAIN)
    over = x > knee
    y = x.copy()
    y[over] = knee + (1 - knee) * (1 - np.exp(-(x[over] - knee) / (1 - knee)))
    s = np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(np.maximum(y, 1e-12), 1 / 2.4) - 0.055)
    return np.clip(np.round(s * 255), 0, 255).astype(np.uint8)
