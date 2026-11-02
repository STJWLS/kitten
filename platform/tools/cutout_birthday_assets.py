# -*- coding: utf-8 -*-
"""Remove the baked-in studio background from generated birthday stickers.

The local ComfyUI checkpoint tends to add a pastel backdrop/frame even when
prompted for magenta chroma-key. This post-process floods from the image border
through background-like pixels, then crops and pads the foreground.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, deque

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "static", "birthday", "library")
CATS = ("cake", "balloon", "confetti", "star")


def dist(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def is_white(p):
    return p[0] > 238 and p[1] > 238 and p[2] > 238


def process(path: str, out_path: str, out_size: int = 512) -> None:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    # remove the model's baked-in outer frame before flooding
    margin = max(8, int(min(w, h) * 0.045))
    if w > margin * 3 and h > margin * 3:
        im = im.crop((margin, margin, w - margin, h - margin))
        w, h = im.size
    rgb = im.load()
    # dominant border colours (quantized)
    counts = Counter()
    for x in range(0, w, max(1, w // 16)):
        for y in (0, h - 1):
            counts[rgb[x, y][:3]] += 1
    for y in range(0, h, max(1, h // 16)):
        for x in (0, w - 1):
            counts[rgb[x, y][:3]] += 1
    bg_colors = [c for c, _ in counts.most_common(4)]

    def bg_like(p):
        if is_white(p):
            return True
        # only remove colours very close to a sampled border colour.
        # (65^2 was far too broad and erased visibly different magentas.)
        return any(dist(p[:3], c) < 24 * 24 for c in bg_colors)

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if bg_like(rgb[x, y]) and not seen[y * w + x]:
                seen[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if bg_like(rgb[x, y]) and not seen[y * w + x]:
                seen[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        p = rgb[x, y]
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                np = rgb[nx, ny]
                if bg_like(np):
                    seen[ny * w + nx] = 1
                    q.append((nx, ny))
    for y in range(h):
        for x in range(w):
            if seen[y * w + x]:
                r, g, b, _ = rgb[x, y]
                rgb[x, y] = (r, g, b, 0)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    canvas = canvas.resize((out_size, out_size), Image.LANCZOS)
    canvas.save(out_path)


def main() -> int:
    total = 0
    for cat in CATS:
        d = os.path.join(LIB, cat)
        if not os.path.isdir(d):
            continue
        rawdir = os.path.join(d, "raw")
        src_dir = rawdir if os.path.isdir(rawdir) else d
        for name in sorted(os.listdir(src_dir)):
            if not name.lower().endswith(".png"):
                continue
            src = os.path.join(src_dir, name)
            dst = os.path.join(d, name[:-4] + "_cut.png")
            try:
                process(src, dst)
                total += 1
                print("cut", cat, name, flush=True)
            except Exception as e:
                print("ERR", cat, name, e, flush=True)
    print("done", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
