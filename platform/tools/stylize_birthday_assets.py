# -*- coding: utf-8 -*-
"""Consistent birthday sticker pass.

- close holes in the alpha mask
- thin black edge on internal colour boundaries (Canny)
- cream/white outer outline
- extra thin black outline outside the white outline
- separate offset shadow on a padded canvas
- fully opaque foreground (alpha 0/255); shadow remains separate

Outputs <name>_styled.png (replacing the previous styled pass).
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "static", "birthday", "library")
BASE = os.path.join(ROOT, "static", "birthday")
CATS = ("cake", "balloon", "confetti", "star")
CANVAS = 512
CONTENT = 350
WHITE = 14
BLACK = 4
# Pantone-inspired flat card: each foreground pixel is snapped to one of these.
PANTONE = [
    ("Warm Gray 1", "#f6f1e7"), ("Vanilla Cream", "#f4e3bd"), ("Peach Fuzz", "#f2c9a8"),
    ("Coral", "#e98a7a"), ("Rose", "#d96f8e"), ("Honey Gold", "#e6b84a"),
    ("Mint", "#9ccfb8"), ("Sky Blue", "#a7cbe8"), ("Lavender", "#b8a8d9"),
    ("Cocoa", "#9a765d"), ("Charcoal", "#2f2a2e"), ("Paper White", "#fffaf2"),
]


def close_holes(alpha: Image.Image) -> Image.Image:
    # Fill every enclosed transparent island, but never remove a foreground pixel.
    a = np.array(alpha)
    binary = (a > 12).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(binary)
    cv2.drawContours(filled, contours, -1, 255, -1)
    # keep original foreground too (never erase pixels that were already subject)
    filled = cv2.bitwise_or(filled, binary)
    return Image.fromarray(filled, "L")


def style_one(src: str, dst: str) -> None:
    im = Image.open(src).convert("RGBA")
    im.thumbnail((CONTENT, CONTENT), Image.LANCZOS)
    alpha = close_holes(im.getchannel("A"))
    im.putalpha(alpha)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    if max(im.size) != CONTENT:
        im = im.resize((CONTENT, CONTENT), Image.LANCZOS)

    # Remove thin magenta guide/frame strokes left by some Qwen renders by
    # inpainting them (never deleting foreground pixels or making holes).
    arr = np.array(im.convert("RGB"))
    alpha_keep = np.array(im.getchannel("A"))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mag = ((r > 120) & (b > 95) & (g < 145) & ((r.astype(int) - g) > 35) & ((b.astype(int) - g) > 10)).astype(np.uint8)
    if mag.any():
        dist = cv2.distanceTransform(mag, cv2.DIST_L2, 5)
        thin = ((dist < 2.6) & (mag > 0)).astype(np.uint8)
        if thin.any():
            arr = cv2.inpaint(arr, thin, 3, cv2.INPAINT_TELEA)
            im = Image.fromarray(arr, "RGB").convert("RGBA")
            im.putalpha(Image.fromarray(alpha_keep, "L"))
    # Remove original dark line art completely: the final sticker must be
    # continuous colour blocks, with no internal edges. Inpaint the dark strokes
    # from surrounding colour before snapping to the Pantone card.
    gray0 = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    dark = ((gray0 < 92).astype(np.uint8) * 255)
    dark[~ (np.array(im.getchannel("A")) > 120)] = 0
    if dark.any():
        arr = cv2.inpaint(arr, dark, 4, cv2.INPAINT_TELEA)

    # Snap every foreground pixel to a discrete Pantone-inspired swatch.
    # No blur/k-means: tiny gradients and antialias differences disappear.
    fg = np.array(im.getchannel("A")) > 120
    pal = np.array([tuple(int(h[i:i+2], 16) for i in (1, 3, 5)) for _, h in PANTONE], np.uint8)
    pal_lab = cv2.cvtColor(pal.reshape(1, -1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.int32)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.int32)
    diff = lab[:, :, None, :] - pal_lab[None, None, :, :]
    idx = np.argmin((diff * diff).sum(axis=3), axis=2)
    # neighbourhood-majority smoothing on discrete labels: removes texture
    # without blurring RGB values; output stays exactly on the Pantone card.
    prob = np.stack([cv2.GaussianBlur((idx == l).astype(np.float32), (9, 9), 0)
                     for l in range(len(pal))], axis=2)
    idx = np.argmax(prob, axis=2)
    flat = pal[idx]
    flat[~fg] = 0
    # Remove tiny isolated palette islands (speckles and guide-line fragments)
    # by reassigning each small component to its dominant neighbouring swatch.
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(3):
        changed = False
        for label in range(len(pal)):
            mask = ((idx == label) & fg).astype(np.uint8)
            if not mask.any(): continue
            n, comps, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
            for ci in range(1, n):
                area = int(stats[ci, cv2.CC_STAT_AREA])
                if area >= 55: continue
                cm = (comps == ci).astype(np.uint8)
                ring = cv2.dilate(cm, kernel, iterations=1) - cm
                neigh = idx[(ring > 0) & fg]
                if len(neigh):
                    vals, counts = np.unique(neigh, return_counts=True)
                    idx[cm > 0] = vals[np.argmax(counts)]
                    flat[cm > 0] = pal[idx[cm > 0]]
                    changed = True
        if not changed: break
    flat[~fg] = 0
    # No internal outline: only adjacent flat colour blocks.
    rgb = flat.copy()
    im = Image.fromarray(np.dstack([rgb, np.array(im.getchannel("A"))]), "RGBA")

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ox = (CANVAS - im.width) // 2
    oy = (CANVAS - im.height) // 2

    silhouette = Image.new("L", (CANVAS, CANVAS), 0)
    silhouette.paste(im.getchannel("A"), (ox, oy))

    def dilate(px):
        m = silhouette.filter(ImageFilter.MaxFilter(px * 2 + 1))
        return m.filter(ImageFilter.GaussianBlur(0.8)).point(lambda v: 255 if v > 127 else 0)

    # PS-like concentric strokes:
    # art -> thin black (2px) -> white band (10px) -> thick black (3px, 1.5x)
    # -> thin white outer edge (2px). The outermost line is white, as requested.
    inner_black = dilate(2)
    white_band = dilate(12)
    outer_black = dilate(15)
    outer_white = dilate(19)

    def paint(mask, rgba):
        layer = Image.new("RGBA", (CANVAS, CANVAS), rgba)
        canvas.paste(layer, (0, 0), mask)

    paint(outer_white, (255, 250, 242, 255))
    paint(outer_black, (25, 19, 25, 255))
    paint(white_band, (255, 250, 242, 255))
    paint(inner_black, (25, 19, 25, 255))
    canvas.alpha_composite(im, (ox, oy))

    # fully opaque sticker: alpha is only 0 or 255
    fgmask = np.array(outer_white) > 0
    px = canvas.load()
    for y in range(CANVAS):
        for x in range(CANVAS):
            if fgmask[y, x]:
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, 255)
    canvas.save(dst)


def main() -> int:
    total = 0
    for cat in CATS:
        d = os.path.join(LIB, cat)
        os.makedirs(d, exist_ok=True)
        sources = []
        if os.path.isdir(d):
            sources = [os.path.join(d, n) for n in sorted(os.listdir(d))
                       if n.lower().endswith("_cut.png")]
        if not sources:
            fallback = os.path.join(BASE, cat + ".png")
            if os.path.isfile(fallback):
                sources = [fallback]
        for src in sources:
            name = os.path.splitext(os.path.basename(src))[0]
            base = name[:-4] if name.endswith("_cut") else name
            dst = os.path.join(d, base + "_styled.png")
            try:
                style_one(src, dst)
                total += 1
                print("styled", cat, os.path.basename(dst), flush=True)
            except Exception as e:
                print("ERR", src, e, flush=True)
    print("done", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
