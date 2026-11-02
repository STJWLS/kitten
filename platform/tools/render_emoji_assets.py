# -*- coding: utf-8 -*-
"""Render flat Twemoji SVGs to local PNG sticker sprites.

Why: emoji glyphs differ per OS/browser (Apple, Segoe, Noto ...), and some
characters render as tofu boxes. Twemoji is a flat, consistent artwork set,
so every client gets the same pixels.

Outputs, per emoji:
  static/birthday/emoji/<slug>.png          # flat emoji + white outline
  static/birthday/emoji/<slug>_v1.png ...   # hue-shifted colour variants
  static/birthday/emoji/emoji.js            # browser list of slugs

No black outline is added. Shadow is rendered by CSS in the browser.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time

import cairosvg
import requests
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "birthday", "emoji")
SVG_OUT = os.path.join(OUT, "svg")
SIZE = 512
CONTENT = 380
WHITE = 16

EMOJI = [
    ("🎂", 14), ("🍰", 10), ("🧁", 10),
    ("🎈", 5.5), ("🎁", 5.5), ("🎉", 5.5), ("🎊", 5.5), ("🥳", 5.5), ("🪅", 5.5),
    ("🎀", 8),
    ("🕯️", 0.5), ("🎩", 0.5), ("👑", 0.5), ("🍭", 0.5),
    ("🍬", 0.5), ("🍫", 0.5), ("🍩", 0.5), ("🌷", 0.5),
    ("🌸", 0.5), ("🌺", 0.5), ("🌹", 0.5), ("🌻", 0.5), ("💐", 0.5),
    ("💝", 4), ("💖", 4), ("💕", 4),
    ("🥂", 0.4), ("🍾", 0.4),
]


def slug(ch: str, keep_fe0f: bool = True) -> str:
    cps = [f"{ord(c):x}" for c in ch]
    if not keep_fe0f:
        cps = [c for c in cps if c != "fe0f"]
    return "-".join(cps)


def fetch_svg(ch: str) -> bytes:
    os.makedirs(SVG_OUT, exist_ok=True)
    for keep in (True, False):
        name = slug(ch, keep)
        url = f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/svg/{name}.svg"
        r = requests.get(url, timeout=25)
        if r.status_code == 200 and r.content.strip().startswith(b"<svg"):
            # keep the vector source next to the rendered PNGs
            with open(os.path.join(SVG_OUT, slug(ch, False) + ".svg"), "wb") as f:
                f.write(r.content)
            return r.content
    raise RuntimeError("no Twemoji SVG for %r" % ch)


def render(ch: str) -> Image.Image:
    svg = fetch_svg(ch)
    png = cairosvg.svg2png(bytestring=svg, output_width=SIZE, output_height=SIZE)
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    # fit into CONTENT box with room for the white outline
    im.thumbnail((CONTENT, CONTENT), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
    return canvas


def dilate(mask: Image.Image, px: int) -> Image.Image:
    return mask.filter(ImageFilter.MaxFilter(px * 2 + 1)).filter(ImageFilter.GaussianBlur(0.7)).point(
        lambda v: 255 if v > 120 else 0)


# Magic-wand region seeds, hand-picked per emoji. A seed selects its connected
# colour region; no preset geometric mask is used. Each region has one method.
SEMANTIC_SEEDS = {
    # 1 top hat: body (tiny HSV), band separate
    "1f3a9": [
        {"seeds": [(0.50, 0.32)], "method": "hue", "label": "hat_body"},
        {"seeds": [(0.50, 0.76)], "method": "hue", "label": "hat_band"},
    ],
    # 2 cupcake: sprinkles union, liner union, frosting yellow-white
    "1f9c1": [
        {"seeds": [(0.50, 0.38)], "method": "recolor", "label": "frosting"},
        {"seeds": [(0.41, 0.28), (0.59, 0.36), (0.28, 0.42), (0.47, 0.47), (0.72, 0.45)], "method": "hue", "label": "sprinkles"},
        {"seeds": [(0.50, 0.78)], "method": "recolor", "label": "liner"},
    ],
    # 3 hibiscus: petals red-white, leaves untouched
    "1f33a": [{"seeds": [(0.50, 0.22), (0.75, 0.42), (0.67, 0.68), (0.33, 0.68), (0.22, 0.45), (0.27, 0.30)], "method": "recolor", "label": "flower_red_white"}],
    # 4 sunflower: petals and core small change, leaves untouched
    "1f33b": [
        {"seeds": [(0.50, 0.16), (0.74, 0.32), (0.65, 0.62), (0.35, 0.62), (0.26, 0.32)], "method": "hue", "label": "sunflower_petals"},
        {"seeds": [(0.50, 0.50)], "method": "hue", "label": "sunflower_core"},
    ],
    # 5 chocolate: only outer wrapper changes
    "1f36b": [
        {"seeds": [(0.35, 0.28), (0.20, 0.32), (0.30, 0.35), (0.22, 0.22), (0.40, 0.24), (0.22, 0.40), (0.40, 0.40)], "method": "recolor", "label": "chocolate", "tolerance": 45},
        {"seeds": [(0.70, 0.58), (0.63, 0.55), (0.60, 0.62)], "method": "recolor", "label": "wrapper", "tolerance": 22},
        {"seeds": [(0.58, 0.50), (0.58, 0.55), (0.57, 0.60), (0.60, 0.58)], "method": "recolor", "label": "wrapper_line", "tolerance": 20},
    ],
    # 6 candy: non-white body can change
    "1f36c": [{"seeds": [(0.50, 0.50)], "method": "hue", "label": "candy"}],
    # 7 lollipop: spiral
    "1f36d": [{"seeds": [(0.30, 0.50), (0.48, 0.30), (0.55, 0.48), (0.48, 0.55)], "method": "hue", "label": "lollipop"}],
    # 8 bottle: body small red-brown..green, label beige-white
    "1f37e": [
        {"seeds": [(0.55, 0.50), (0.75, 0.60), (0.80, 0.50), (0.65, 0.45)], "method": "recolor", "label": "bottle_body"},
        {"seeds": [(0.65, 0.70)], "method": "recolor", "label": "bottle_label"},
    ],
    # 9 confetti-ball contents
    "1f38a": [{"seeds": [(0.28, 0.78), (0.33, 0.90), (0.55, 0.78), (0.55, 0.90), (0.20, 0.75), (0.60, 0.70), (0.75, 0.75), (0.35, 0.78), (0.48, 0.75)], "method": "hue", "label": "confetti_contents"}],
    # 10 heart unchanged, ribbon purple-yellow
    "1f49d": [{"seeds": [(0.18, 0.35), (0.25, 0.35), (0.20, 0.55), (0.25, 0.70), (0.35, 0.45), (0.42, 0.40), (0.45, 0.55), (0.60, 0.50), (0.75, 0.50)], "method": "recolor", "label": "ribbon_band", "protect_red": True}],
    # 11 candle wax purple-yellow
    "1f56f": [{"seeds": [(0.45, 0.70), (0.55, 0.76), (0.50, 0.65)], "method": "recolor", "label": "candle_wax"}],
    # 12 tulip
    "1f337": [{"seeds": [(0.50, 0.20), (0.40, 0.30), (0.60, 0.30)], "method": "hue", "label": "tulip_petals"}],
    # 13 blossom: everything but yellow centre / white stem -> purple-yellow
    "1f338": [
        {"seeds": [(0.50, 0.22), (0.75, 0.42), (0.67, 0.68), (0.33, 0.68), (0.22, 0.45), (0.27, 0.30)], "method": "recolor", "label": "flower_all"},
    ],
    # 14 rose: leaves untouched, flower purple-yellow
    "1f339": [{"seeds": [(0.50, 0.22), (0.66, 0.42), (0.34, 0.42)], "method": "recolor", "label": "rose_petals"}],
    # 15 donut: sprinkles arbitrary; other small jitter
    "1f369": [
        {"seeds": [(0.52, 0.29), (0.42, 0.32), (0.66, 0.32), (0.72, 0.45), (0.20, 0.45), (0.80, 0.40), (0.45, 0.68), (0.62, 0.65)], "method": "hue", "label": "sprinkles"},
        {"seeds": [(0.40, 0.35), (0.60, 0.40)], "method": "recolor", "label": "donut_jam"},
    ],
    # 16 cake slice
    "1f370": [
        {"seeds": [(0.45, 0.50), (0.55, 0.62), (0.38, 0.58)], "method": "recolor", "label": "cake_sponge"},
        {"seeds": [(0.50, 0.42), (0.40, 0.68)], "method": "hue", "label": "cake_trim"},
    ],
    # 17 ribbon: whole
    "1f380": [{"seeds": [(0.20, 0.22), (0.50, 0.30), (0.80, 0.22), (0.30, 0.45), (0.70, 0.45), (0.35, 0.75), (0.65, 0.75)], "method": "hue", "label": "ribbon_all"}],
    # 18 gift
    "1f381": [{"seeds": [(0.50, 0.55), (0.50, 0.20), (0.20, 0.50), (0.80, 0.50), (0.50, 0.45), (0.50, 0.70)], "method": "hue", "label": "gift_box"}],
    # 19 birthday cake: body red-yellow; plate/flame not seeded
    "1f382": [
        {"seeds": [(0.30, 0.45), (0.70, 0.45)], "method": "shade", "label": "cake_top_surface", "protect_plate": True},
        {"seeds": [(0.30, 0.55), (0.70, 0.55)], "method": "shade", "label": "cake_side_upper", "protect_plate": True},
        {"seeds": [(0.30, 0.68), (0.70, 0.68)], "method": "shade", "label": "cake_side_lower", "protect_plate": True},
        {"seeds": [(0.30, 0.72), (0.50, 0.76), (0.70, 0.72)], "method": "shade", "label": "cake_bottom_seam", "protect_plate": True},
    ],
    # 20 balloon: top + bottom closure
    "1f388": [{"seeds": [(0.50, 0.30), (0.50, 0.58), (0.50, 0.65), (0.50, 0.82)], "method": "hue", "label": "balloon"}],
    # 21 popper: cone group + other group
    "1f389": [
        {"seeds": [(0.30, 0.50), (0.40, 0.65), (0.38, 0.55), (0.50, 0.38), (0.45, 0.50), (0.55, 0.42), (0.48, 0.44)], "method": "hue", "label": "popper_cone"},
        {"seeds": [(0.62, 0.30), (0.72, 0.45), (0.20, 0.35), (0.80, 0.60)], "method": "hue", "label": "popper_other"},
    ],
    # 22 crown: crown unchanged, gems arbitrary
    "1f451": [{"seeds": [(0.30, 0.55), (0.50, 0.55), (0.70, 0.55)], "method": "hue", "label": "gems"}],
    # 23 bouquet: green untouched; red flowers group, yellow flowers group
    "1f490": [
        {"seeds": [(0.32, 0.30), (0.52, 0.55)], "method": "hue", "label": "flowers_red"},
        {"seeds": [(0.30, 0.50), (0.55, 0.30)], "method": "hue", "label": "flowers_yellow"},
    ],
    # 24-25 no variants; 26 glasses liquid
    "1f942": [{"seeds": [(0.30, 0.50), (0.70, 0.50)], "method": "recolor", "label": "glasses_liquid"}],
    # 27 face: horn union + hat
    "1f973": [
        {"seeds": [(0.80, 0.60), (0.85, 0.65)], "negatives": [(0.50, 0.50), (0.50, 0.35)], "method": "hue", "label": "whistle"},
        {"seeds": [(0.25, 0.20), (0.30, 0.25), (0.35, 0.20), (0.20, 0.25), (0.18, 0.35), (0.22, 0.30), (0.12, 0.20), (0.10, 0.25), (0.14, 0.30)], "negatives": [(0.50, 0.50), (0.50, 0.35)], "method": "hue", "label": "hat", "dilate": 3},
    ],
    # 28 piñata
    "1fa85": [{"seeds": [(0.50, 0.50)], "method": "hue", "label": "pinata"}],
}


RULE_LABELS = {
    "1f382": "cake_icing", "1f370": "cake_slice", "1f9c1": "frosting",
    "1f388": "balloon", "1f381": "gift_box", "1f389": "popper",
    "1f38a": "confetti_ball", "1f380": "ribbon", "1f56f": "candle_wax",
    "1f973": "hat", "1f3a9": "hat_band", "1f451": "crown",
    "1fa85": "pinata", "1f36d": "candy", "1f36c": "candy",
    "1f36b": "wrapper", "1f369": "donut_icing", "1f337": "petals",
    "1f338": "petals", "1f33a": "petals", "1f339": "petals",
    "1f33b": "petals", "1f490": "petals", "1f942": "liquid",
    "1f37e": "bottle", "1f49d": "heart", "1f496": "heart", "1f495": "hearts",
}

# HSV rules that reflect what the region actually is. Supported keys:
#   hsv:       allowed (h,s,v) ranges for mask pixels
#   method:    hue / recolor / keep
#   angles:    hue shifts per variant
#   targets:   target HSV per variant (for recolor)
HSV_POLICIES = {
    "cake_icing": {"hsv": ((0, 45), (12, 255), (75, 255)), "methods": "hue", "angles": (18, 32, 48)},
    "cake_slice": {"hsv": ((0, 45), (8, 255), (80, 255)), "methods": "hue", "angles": (18, 34, 50)},
    "frosting": {"hsv": ((4, 45), (5, 200), (120, 255)), "methods": "hue", "angles": (16, 28, 40)},
    "candle_wax": {"methods": "recolor",
                   "targets": [(150, 110, 235), (165, 90, 240), (25, 200, 250)]},
    "hat": {"methods": "hue", "angles": (38, 150, 238)},
    "hat_band": {"methods": "recolor",
                 "targets": [(145, 150, 125), (38, 150, 135), (95, 140, 130)]},
    "crown": {"hsv": ((3, 45), (20, 255), (70, 255)), "methods": "hue", "angles": (8, 16, 24)},
    "petals": {"methods": "hue", "angles": (36, 120, 240)},
    "liquid": {"methods": "recolor",
               "targets": [(25, 165, 245), (18, 175, 240), (30, 145, 250)]},
    "bottle": {"hsv": ((25, 90), (60, 255), (20, 255)), "methods": "hue", "angles": (12, 24, 36)},
    "balloon": {"methods": "hue", "angles": (38, 150, 238)},
    "ribbon": {"methods": "hue", "angles": (38, 150, 238)},
    "gift_box": {"methods": "hue", "angles": (38, 150, 238)},
    "popper": {"methods": "hue", "angles": (38, 150, 238)},
    "confetti_ball": {"methods": "hue", "angles": (38, 150, 238)},
    "pinata": {"methods": "hue", "angles": (38, 150, 238)},
    "candy": {"methods": "hue", "angles": (38, 150, 238)},
    "wrapper": {"methods": "recolor", "targets": [(0, 200, 230), (25, 200, 245), (60, 160, 190), (110, 180, 220)]},
    "chocolate": {"methods": "shade", "targets": [(170, 45, 250), (30, 55, 250), (15, 190, 95), (25, 120, 185)]},
    "wrapper_line": {"methods": "recolor", "targets": [(0, 200, 230), (25, 200, 245), (60, 160, 190), (110, 180, 220)]},
    "donut_icing": {"methods": "hue", "angles": (38, 150, 238)},
    "heart": {"methods": "hue", "angles": (38, 150, 238)},
    "hearts": {"methods": "hue", "angles": (38, 150, 238)},
    "hat_body": {"methods": "hue", "angles": (3, 6, 9)},
    "frosting": {"methods": "recolor", "targets": [(25, 140, 248), (28, 30, 252), (30, 200, 240)]},
    "sprinkles": {"methods": "hue", "angles": (38, 120, 238)},
    "liner": {"methods": "recolor", "targets": [(100, 120, 245), (105, 20, 252), (95, 60, 250)]},
    "flower_red_white": {"methods": "recolor", "targets": [(0, 190, 230), (170, 120, 245), (170, 30, 250)]},
    "sunflower_petals": {"methods": "hue", "angles": (6, 12, 18)},
    "sunflower_core": {"methods": "hue", "angles": (4, 8, 12)},
    "bottle_body": {"methods": "recolor", "targets": [(15, 170, 150), (35, 180, 150), (75, 160, 140)]},
    "bottle_label": {"methods": "recolor", "targets": [(28, 45, 248), (30, 15, 252), (25, 70, 245)]},
    "confetti_contents": {"methods": "hue", "angles": (38, 150, 238)},
    "ribbon_band": {"methods": "recolor", "targets": [(150, 120, 230), (165, 100, 235), (25, 200, 250)]},
    "flower_all": {"methods": "recolor", "targets": [(150, 110, 230), (165, 90, 240), (25, 200, 250)]},
    "rose_petals": {"methods": "hue_keep", "targets_h": (150, 175, 25)},
    "donut_jam": {"methods": "recolor", "targets": [(0, 210, 220), (10, 190, 205), (15, 175, 180)]},
    "ribbon_all": {"methods": "hue", "angles": (38, 150, 238)},
    "cake_body": {"methods": "hue", "angles": (10, 25, 40)},
    "popper_cone": {"methods": "hue", "angles": (38, 150, 238)},
    "popper_other": {"methods": "hue", "angles": (38, 150, 238)},
    "gems": {"methods": "hue", "angles": (38, 150, 238)},
    "flowers_red": {"methods": "hue", "angles": (38, 150, 238)},
    "flowers_yellow": {"methods": "hue", "angles": (38, 150, 238)},
    "whistle": {"methods": "hue", "angles": (38, 150, 238)},
    "glasses_liquid": {"methods": "recolor", "targets": [(15, 190, 150), (170, 210, 155), (0, 0, 255)]},
    "pinata": {"methods": "hue", "angles": (38, 150, 238)},
    "lollipop": {"methods": "lollipop", "palette": [
        [(0, 200, 230), (12, 220, 245), (25, 220, 245)],
        [(0, 200, 230), (25, 220, 245), (90, 130, 240)],
        [(0, 200, 230), (0, 0, 255), (170, 100, 245)],
    ]},
    "tulip_petals": {"methods": "hue", "angles": (38, 150, 238)},
    "cake_sponge": {"methods": "recolor", "targets": [(25, 200, 245), (20, 180, 190), (15, 160, 135)]},
    "cake_top_surface": {"methods": "shade", "targets": [(175, 190, 175), (15, 170, 125), (0, 0, 250)]},
    "cake_side_upper": {"methods": "shade", "targets": [(175, 160, 210), (20, 140, 175), (35, 50, 245)]},
    "cake_side_lower": {"methods": "shade", "targets": [(0, 0, 255), (40, 115, 180), (25, 180, 245)]},
    "cake_bottom_seam": {"methods": "shade", "targets": [(175, 220, 150), (35, 150, 150), (0, 0, 250)]},
    "cake_trim": {"methods": "hue", "angles": (0, 20, 40)},
    "gift_box": {"methods": "hue", "angles": (38, 150, 238)},
}

NO_VARIANTS = {"1f495", "1f496"}
VARIANT_COUNT = {"1f382": 3, "1f36b": 4}


def mask_postprocess(mask_im: Image.Image, alpha: "Image.Image", rule) -> "Image.Image":
    import cv2
    import numpy as np
    m = (np.array(mask_im) > 127).astype(np.uint8)
    a = np.array(alpha) > 0
    m &= a.astype(np.uint8)
    # close small SAM holes / bridges, remove isolated specks
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if rule.get("dilate"):
        m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=int(rule["dilate"]))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    cleaned = np.zeros_like(m)
    for i in range(1, n):
        if int(stats[i, cv2.CC_STAT_AREA]) >= 40:
            cleaned[labels == i] = 1
    return Image.fromarray((cleaned * 255).astype(np.uint8), "L")


SAM_CKPT = os.path.join(ROOT, "data", "models", "sam_vit_b_01ec64.pth")
_SAM_PREDICTOR = None


def _sam_predictor():
    global _SAM_PREDICTOR
    if _SAM_PREDICTOR is not None:
        return _SAM_PREDICTOR
    import torch
    from segment_anything import sam_model_registry, SamPredictor
    if not os.path.isfile(SAM_CKPT):
        raise FileNotFoundError(SAM_CKPT)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    sam = sam_model_registry["vit_b"](checkpoint=SAM_CKPT).to(device)
    _SAM_PREDICTOR = SamPredictor(sam)
    return _SAM_PREDICTOR


def sam_masks(im: Image.Image, rules) -> list:
    """True SAM mask prompts: each semantic seed is a positive point prompt."""
    try:
        import numpy as np
        pred = _sam_predictor()
    except Exception as e:
        print("SAM unavailable, falling back to watershed:", e, flush=True)
        return semantic_masks(im, rules)
    arr = np.array(im.convert("RGBA"))
    alpha = np.array(im.getchannel("A")) > 0
    rgb = arr[:, :, :3].copy()
    rgb[~alpha] = 245
    pred.set_image(rgb)
    masks = []
    for rule in rules:
        union = np.zeros(alpha.shape, bool)
        neg = []
        for nx, ny in rule.get("negatives", []):
            x, y = int(nx * im.width), int(ny * im.height)
            if 0 <= x < im.width and 0 <= y < im.height and alpha[y, x]:
                neg.append([x, y])
        for nx, ny in rule["seeds"]:
            x, y = int(nx * im.width), int(ny * im.height)
            if not (0 <= x < im.width and 0 <= y < im.height and alpha[y, x]):
                continue
            pts = [[x, y]] + neg
            labels = [1] + [0] * len(neg)
            ms, scores, _ = pred.predict(
                point_coords=np.array(pts), point_labels=np.array(labels),
                multimask_output=True)
            union |= (ms[int(np.argmax(scores))] & alpha)
        masks.append(Image.fromarray((union * 255).astype(np.uint8), "L"))
    return masks


def semantic_masks(im: Image.Image, rules) -> list:
    """Watershed segmentation from semantic seeds.

    Each seed is a semantic marker; markers with the same rule (e.g. two
    disconnected heart lobes) are unioned after watershed. Regions follow
    image edges, not a fixed colour tolerance, so the same semantic part can
    have different colours / disconnected pieces.
    """
    try:
        import numpy as np
        from skimage.segmentation import watershed
        from skimage.filters import sobel
        from skimage.color import rgb2gray
    except Exception:
        return [Image.new("L", im.size, 0) for _ in rules]
    arr = np.array(im.convert("RGB"))
    alpha = np.array(im.getchannel("A")) > 0
    gray = rgb2gray(arr)
    grad = sobel(gray)
    grad[~alpha] = 1.0
    markers = np.zeros(gray.shape, np.int32)
    next_id = 1
    groups, cands = [], []
    for rule in rules:
        ids = []
        cand = np.zeros(alpha.shape, bool)
        tol = int(rule.get("tolerance", 42))
        for nx, ny in rule["seeds"]:
            x, y = int(nx * im.width), int(ny * im.height)
            if 0 <= x < im.width and 0 <= y < im.height and alpha[y, x]:
                markers[y, x] = next_id
                ids.append(next_id)
                next_id += 1
                target = arr[y, x].astype(np.int32)
                diff = arr.astype(np.int32) - target
                cand |= ((diff * diff).sum(axis=2) <= tol * tol) & alpha
        groups.append(ids)
        cands.append(cand)
    ws = watershed(grad, markers, mask=alpha)
    out = []
    for rule, ids, cand in zip(rules, groups, cands):
        if not ids:
            out.append(Image.new("L", im.size, 0))
            continue
        # Watershed gives semantic boundaries; the seed-colour candidate keeps
        # the region from swallowing unrelated neighbouring parts.
        m = (cand if rule.get("mode") == "semantic" else (np.isin(ws, ids) & cand))
        out.append(Image.fromarray((m * 255).astype(np.uint8), "L"))
    return out


def manual_variant(main: Image.Image, slug: str, variant: int, masks=None) -> Image.Image:
    rules = SEMANTIC_SEEDS.get(slug)
    if not rules or variant <= 0:
        return main
    import cv2
    import numpy as np
    arr = np.array(main.convert("RGBA"))
    hsv = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2HSV)
    if masks is None:
        masks = semantic_masks(main, rules)
    for rule, mask_im in zip(rules, masks):
        mask_im = mask_postprocess(mask_im, main.getchannel("A"), rule)
        mask = np.array(mask_im) > 127
        rgb = arr[:, :, :3]
        alpha_b = arr[:, :, 3] > 0
        tol = int(rule.get("tolerance", 42))
        cand = np.zeros(mask.shape, bool)
        for nx, ny in rule["seeds"]:
            x, y = int(nx * main.width), int(ny * main.height)
            if 0 <= x < main.width and 0 <= y < main.height and alpha_b[y, x]:
                target = rgb[y, x].astype(np.int32)
                diff = rgb.astype(np.int32) - target
                cand |= ((diff * diff).sum(axis=2) <= tol * tol) & alpha_b
        mask &= cand
        if not mask.any():
            continue
        label = rule.get("label") or RULE_LABELS.get(slug, "")
        policy = HSV_POLICIES.get(label, {})
        if policy.get("hsv"):
            (h0, h1), (s0, s1), (v0, v1) = policy["hsv"]
            allowed = ((hsv[:, :, 0] >= h0) & (hsv[:, :, 0] <= h1) &
                       (hsv[:, :, 1] >= s0) & (hsv[:, :, 1] <= s1) &
                       (hsv[:, :, 2] >= v0) & (hsv[:, :, 2] <= v1))
            mask &= allowed
            if not mask.any():
                continue
        method = policy.get("method") or policy.get("methods") or rule.get("method")
        if method == "hue":
            deg = (policy.get("angles") or rule.get("angles", (38, 150, 238)))[variant - 1]
            shift = int(round(deg / 2.0))
            hsv[mask, 0] = (hsv[mask, 0].astype(np.int16) + shift) % 180
        elif method == "hue_keep":
            target_h = policy["targets_h"][min(variant - 1, len(policy["targets_h"]) - 1)]
            hsv[mask, 0] = target_h
        elif method == "cream_wave":
            ci = min(variant - 1, len(policy["cream_targets"]) - 1)
            wi = min(variant - 1, len(policy["wave_targets"]) - 1)
            cream = mask & (hsv[:, :, 2] >= 165)
            wave = mask & (hsv[:, :, 2] < 165)
            for sel, target in ((cream, policy["cream_targets"][ci]), (wave, policy["wave_targets"][wi])):
                hsv[sel, 0] = target[0]; hsv[sel, 1] = target[1]; hsv[sel, 2] = target[2]
        elif method == "shade":
            targets = policy.get("targets") or rule.get("targets")
            target = targets[min(variant - 1, len(targets) - 1)]
            if mask.any():
                med_s = max(1.0, float(np.median(hsv[mask, 1])))
                med_v = max(1.0, float(np.median(hsv[mask, 2])))
                s_ratio = hsv[mask, 1].astype(np.float32) / med_s
                v_ratio = hsv[mask, 2].astype(np.float32) / med_v
                hsv[mask, 0] = target[0]
                hsv[mask, 1] = np.clip(target[1] * s_ratio, 0, 255).astype(np.uint8)
                hsv[mask, 2] = np.clip(target[2] * v_ratio, 0, 255).astype(np.uint8)
        elif method == "cake_layers":
            vi = min(variant - 1, 2)
            yy = np.arange(main.height)[:, None]
            top = mask & (yy < main.height * 0.52)
            upper = mask & (yy >= main.height * 0.52) & (yy < main.height * 0.67)
            lower = mask & (yy >= main.height * 0.67)
            for sel, key in ((top, "top_targets"), (upper, "upper_targets"), (lower, "lower_targets")):
                target = policy[key][vi]
                if not sel.any():
                    continue
                med_s = max(1.0, float(np.median(hsv[sel, 1])))
                med_v = max(1.0, float(np.median(hsv[sel, 2])))
                s_ratio = hsv[sel, 1].astype(np.float32) / med_s
                v_ratio = hsv[sel, 2].astype(np.float32) / med_v
                hsv[sel, 0] = target[0]
                hsv[sel, 1] = np.clip(target[1] * s_ratio, 0, 255).astype(np.uint8)
                hsv[sel, 2] = np.clip(target[2] * v_ratio, 0, 255).astype(np.uint8)
        elif method == "recolor":
            targets = policy.get("targets") or rule.get("targets")
            target = targets[min(variant - 1, len(targets) - 1)]
            hsv[mask, 0] = target[0]
            hsv[mask, 1] = target[1]
            hsv[mask, 2] = target[2]
        elif method == "lollipop":
            pal = policy["palette"][variant - 1]
            hv = hsv[:, :, 0].astype(np.int16)
            red = (hv < 15) | (hv > 160)
            green = (hv >= 55) & (hv <= 110)
            yellow = ~(red | green)
            for m, target in ((red, pal[0]), (yellow, pal[1]), (green, pal[2])):
                sel = mask & m
                hsv[sel, 0] = target[0]
                hsv[sel, 1] = target[1]
                hsv[sel, 2] = target[2]
    arr[:, :, :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    if any(r.get("protect_red") for r in rules):
        orig = np.array(main.convert("RGB"))
        oh = cv2.cvtColor(orig, cv2.COLOR_RGB2HSV)
        red = (((oh[:, :, 0] < 8) | (oh[:, :, 0] > 170)) & (oh[:, :, 1] > 100) & (oh[:, :, 2] > 50))
        arr[red, :3] = orig[red]
    if any(r.get("protect_white") for r in rules):
        orig = np.array(main.convert("RGB"))
        oh = cv2.cvtColor(orig, cv2.COLOR_RGB2HSV)
        white = (oh[:, :, 1] < 45) & (oh[:, :, 2] > 210)
        arr[white, :3] = orig[white]
    if any(r.get("protect_plate") for r in rules):
        orig = np.array(main.convert("RGB"))
        oh = cv2.cvtColor(orig, cv2.COLOR_RGB2HSV)
        plate = ((oh[:, :, 0] >= 80) & (oh[:, :, 0] <= 140) & (oh[:, :, 1] >= 8) & (oh[:, :, 2] > 120))
        arr[plate, :3] = orig[plate]
    return Image.fromarray(arr, "RGBA")


FACE_SKIN = {  # OpenCV HSV (h 0..179, s/v 0..255)
    "1f973": (12, 78, 240),  # warm flesh tone for the party face
}


def face_mask(im: Image.Image) -> Image.Image:
    import cv2
    import numpy as np
    arr = np.array(im.convert("RGB"))
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    warm = ((h >= 8) & (h <= 35) & (s >= 60) & (v >= 110)).astype(np.uint8)
    n, comps, stats, _ = cv2.connectedComponentsWithStats(warm, connectivity=8)
    if n <= 1:
        return Image.new("L", im.size, 0)
    # largest warm component that covers the centre area
    best, best_area = 0, 0
    for i in range(1, n):
        x, y, w, hh, area = stats[i]
        if area > best_area and x < im.width * 0.7 and y < im.height * 0.75:
            best, best_area = i, area
    mask = np.zeros_like(warm)
    if best:
        mask[comps == best] = 255
    return Image.fromarray(mask, "L")


def apply_face_skin(im: Image.Image, slug: str, variant: int = 0) -> Image.Image:
    if slug not in FACE_SKIN:
        return im
    import cv2
    import numpy as np
    mask = np.array(face_mask(im))
    if not mask.any():
        return im
    arr = np.array(im.convert("RGBA"))
    hsv = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2HSV)
    h0, s0, v0 = FACE_SKIN[slug]
    # small per-variant flesh tone changes, not a hue rotation
    h0 = h0 + (variant - 1) * 2
    s0 = max(40, min(150, s0 + (variant - 1) * 6))
    v0 = max(190, min(255, v0 - abs(variant) * 4))
    sel = mask > 0
    hsv[sel, 0] = h0
    hsv[sel, 1] = s0
    hsv[sel, 2] = v0
    arr[:, :, :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return Image.fromarray(arr, "RGBA")


# Optional per-emoji region recolours. Each rule selects an HSV band, so a
# cream/frosting area can change independently of candles/plate/artwork.
REGION_RULES = {
    "1f382": [  # birthday cake: cream/frosting band
        {"name": "cream", "hsv": ((8, 38), (8, 95), (165, 255)),
         "targets": [(24, 60, 245), (20, 68, 240), (30, 48, 250)]},
    ],
    "1f9c1": [  # cupcake: pale frosting band
        {"name": "frosting", "hsv": ((12, 40), (5, 80), (175, 255)),
         "targets": [(27, 55, 248), (22, 62, 242), (33, 45, 252)]},
    ],
}


def apply_region_rules(im: Image.Image, slug: str, variant: int) -> Image.Image:
    rules = REGION_RULES.get(slug)
    if not rules or variant <= 0:
        return im
    import cv2
    import numpy as np
    arr = np.array(im.convert("RGBA"))
    hsv = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    for ri, rule in enumerate(rules):
        (h0, h1), (s0, s1), (v0, v1) = rule["hsv"]
        mask = (h >= h0) & (h <= h1) & (s >= s0) & (s <= s1) & (v >= v0) & (v <= v1)
        target = rule["targets"][min(variant - 1, len(rule["targets"]) - 1)]
        hsv[mask, 0] = target[0]
        hsv[mask, 1] = target[1]
        hsv[mask, 2] = target[2]
    arr[:, :, :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return Image.fromarray(arr, "RGBA")


def hue_variant(main: Image.Image, degrees: int) -> Image.Image:
    import cv2
    import numpy as np
    arr = np.array(main.convert("RGBA"))
    rgb = arr[:, :, :3]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    shift = int(round(degrees / 2.0))  # OpenCV hue is 0..179
    h, s, v = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1], hsv[:, :, 2]
    # Skin/face range (Twemoji yellow face, hands, warm skin): do not accept
    # a full hue rotation; only a tiny nudge. Black/white already have no sat.
    skin = (h >= 4) & (h <= 30) & (s >= 35) & (v >= 45)
    mask = (s > 28) & (~skin)
    hsv[mask, 0] = (hsv[mask, 0].astype(np.int16) + shift) % 180
    hsv[skin, 0] = (hsv[skin, 0].astype(np.int16) + int(round(shift * 0.08))) % 180
    out = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    arr[:, :, :3] = out
    return Image.fromarray(arr, "RGBA")


def build(ch: str, name: str) -> list:

    im = render(ch)
    alpha = im.getchannel("A")
    seg_rules = SEMANTIC_SEEDS.get(name, [])
    seg_masks = sam_masks(im, seg_rules) if seg_rules else []
    outline_mask = dilate(alpha, WHITE)
    outline = Image.new("RGBA", (SIZE, SIZE), (255, 252, 247, 255))
    main = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    main.paste(outline, (0, 0), outline_mask)
    main.alpha_composite(im)
    # make the artwork/outline fully opaque, no semi-transparent fringe
    a = main.getchannel("A").point(lambda v: 255 if v > 0 else 0)
    main.putalpha(a)
    main.save(os.path.join(OUT, name + ".png"))
    made = [name]
    if name in NO_VARIANTS:
        return made
    count = VARIANT_COUNT.get(name, 3)
    for i in range(1, count + 1):
        var = manual_variant(main, name, i, seg_masks)
        var_name = "%s_v%d" % (name, i)
        var.save(os.path.join(OUT, var_name + ".png"))
        made.append(var_name)
    return made


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    groups = []
    for ch, relevance in EMOJI:
        name = slug(ch, keep_fe0f=False)
        try:
            made = build(ch, name)
            groups.append({"base": name, "relevance": relevance, "variants": made})
            print("emoji", name, relevance, len(made), flush=True)
        except Exception as e:
            print("ERR", name, e, flush=True)
        time.sleep(0.1)
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "emoji.js"), "w", encoding="utf-8") as f:
        f.write("window.KP_BIRTHDAY_EMOJI = " + json.dumps(groups, ensure_ascii=False) + ";\n")
    print("done", len(groups), "groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
