"""Track the capsule through each turntable ring with SAM2 video (transformers port).

Writes full-frame capsule-only masks (uint8 0/255 PNG) with the source file names.
Usage: python sam_track.py <src_dir> <out_dir> [ring ...]
"""
import glob
import json
import os
import sys

import cv2
import numpy as np
import torch
from transformers import Sam2VideoModel, Sam2VideoProcessor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RINGS = json.load(open(os.path.join(ROOT, "projects", "round2", "shoot.json")))["rings"]
# Box around the capsule on each ring's first frame, full-frame pixels (x1, y1, x2, y2).
BOXES = [(3560, 1680, 4250, 2160), (3110, 1800, 3890, 2200), (3170, 1990, 3970, 2310)]
CROP_W, CROP_H = 3000, 2000  # fixed per-ring window, so SAM sees the capsule larger
MODEL = "facebook/sam2.1-hiera-large"


def crop_window(box, w, h):
    cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    x0 = int(np.clip(cx - CROP_W // 2, 0, w - CROP_W))
    y0 = int(np.clip(cy - CROP_H // 2, 0, h - CROP_H))
    return x0, y0


def main():
    src, out = sys.argv[1], sys.argv[2]
    rings = [int(r) for r in sys.argv[3:]] or range(len(RINGS))
    os.makedirs(out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, "*.png")))
    dev = "cuda"
    model = Sam2VideoModel.from_pretrained(MODEL).to(dev, dtype=torch.bfloat16)
    proc = Sam2VideoProcessor.from_pretrained(MODEL)

    for r in rings:
        a, b = RINGS[r]
        first = cv2.imread(files[a])
        h, w = first.shape[:2]
        x0, y0 = crop_window(BOXES[r], w, h)
        frames = []
        for f in files[a:b]:
            im = cv2.imread(f) if f != files[a] else first
            frames.append(cv2.cvtColor(im[y0:y0 + CROP_H, x0:x0 + CROP_W], cv2.COLOR_BGR2RGB))
        sess = proc.init_video_session(video=frames, inference_device=dev, dtype=torch.bfloat16)
        bx = BOXES[r]
        proc.add_inputs_to_inference_session(
            inference_session=sess, frame_idx=0, obj_ids=1,
            input_boxes=[[[bx[0] - x0, bx[1] - y0, bx[2] - x0, bx[3] - y0]]])
        model(inference_session=sess, frame_idx=0)
        n = 0
        for o in model.propagate_in_video_iterator(sess):
            m = proc.post_process_masks([o.pred_masks], original_sizes=[[CROP_H, CROP_W]],
                                        binarize=False)[0]
            prob = torch.sigmoid(m[0, 0].float()).cpu().numpy()
            full = np.zeros((h, w), np.uint8)
            full[y0:y0 + CROP_H, x0:x0 + CROP_W] = (prob * 255).astype(np.uint8)
            name = os.path.basename(files[a + o.frame_idx])
            cv2.imwrite(os.path.join(out, name), full)
            n += 1
        print(f"ring {r}: {n} masks, crop origin {x0},{y0}", flush=True)
        del sess, frames
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
