# -*- coding: utf-8 -*-
"""Generate birthday sticker assets with the local ComfyUI API.

Prompts render each sticker on a solid magenta chroma-key background; the
background is removed afterwards so the PNGs can be layered over any theme.

Usage:
  python generate_birthday_assets.py --per-category 10
  python generate_birthday_assets.py --categories cake,balloon --per-category 10
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import uuid

import requests
from PIL import Image

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "birthday", "library")

PROMPTS = {
    "cake": (
        "a simple flat vector illustration of a cute birthday cake, two layers, one candle, "
        "solid pastel colour fills, no outlines, no strokes, no line art, no border, no frame, "
        "single centered object, isolated on plain solid magenta background, no text"
    ),
    "balloon": (
        "a simple flat vector illustration of a bunch of three party balloons with thin strings, "
        "solid pastel colour fills, no outlines, no strokes, no line art, no border, no frame, "
        "single centered object, isolated on plain solid magenta background, no text, no characters"
    ),
    "confetti": (
        "a simple flat vector illustration of a burst of colourful confetti pieces and ribbons, "
        "solid colour fills, no outlines, no strokes, no line art, no border, no frame, "
        "centered, isolated on plain solid magenta background, no text, no letters"
    ),
    "star": (
        "a simple flat vector illustration of a five-point star, warm cream and gold solid fills, "
        "small sparkle, no outlines, no strokes, no line art, no border, no frame, "
        "single centered object, isolated on plain solid magenta background, no text"
    ),
}

NEGATIVE = (
    "outline, outlines, stroke, line art, border, frame, dotted line, cut line, die-cut guide, "
    "crop marks, page edge, square border, mockup, multiple objects, text, letters, watermark, "
    "logo, shadow, floor, scenery, collage, grid, realistic photo, dark background, green background"
)

def workflow(category: str, batch: int, seed: int, prefix: str, size: int = 1024, steps: int = 28) -> dict:
    positive = PROMPTS[category]
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "QwenImage21Cache",
              "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"clip": ["3", 0], "prompt": positive, "negative_prompt": NEGATIVE,
                         "resolution": 1024, "images": []}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": size, "height": size, "batch_size": batch}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["2", 0], "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps,
                         "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }

def submit(wf: dict) -> str:
    payload = {"prompt": wf, "client_id": "kp-birthday-" + uuid.uuid4().hex[:8]}
    r = requests.post(COMFY + "/prompt", json=payload, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(str(body["error"]))
    return str(body["prompt_id"])


def wait_history(prompt_id: str, timeout: int = 1800) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = requests.get(COMFY + "/history/" + prompt_id, timeout=20)
            if r.ok:
                d = r.json() or {}
                if prompt_id in d:
                    return d[prompt_id]
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError("ComfyUI generation timed out: " + prompt_id)


def download_image(item: dict) -> bytes:
    params = {"filename": item.get("filename", ""), "subfolder": item.get("subfolder", ""),
              "type": item.get("type", "output")}
    r = requests.get(COMFY + "/view", params=params, timeout=60)
    r.raise_for_status()
    return r.content


def chroma_to_alpha(raw: bytes, size: int = 512) -> Image.Image:
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    pix = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pix[x, y]
            # magenta screen: high red+blue, low green
            if r > 145 and b > 145 and g < 115:
                pix[x, y] = (r, g, b, 0)
            elif r > 120 and b > 120 and g < 150:
                # soft edge: partially transparent
                pix[x, y] = (r, g, b, max(0, min(a, int((150 - g) * 1.8))))
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    if size and side != size:
        canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def run_category(category: str, per_category: int, batch: int, size: int = 1024, steps: int = 28) -> int:
    out_dir = os.path.join(OUT, category)
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    remaining = per_category
    round_no = 0
    while remaining > 0:
        round_no += 1
        n = min(batch, remaining)
        seed = int(time.time() * 1000) % 2147483647
        prefix = "kp_birthday_%s_%d" % (category, round_no)
        print("[%s] submitting batch %d (%d images)" % (category, round_no, n), flush=True)
        pid = submit(workflow(category, n, seed, prefix, size, steps))
        hist = wait_history(pid)
        for node in (hist.get("outputs") or {}).values():
            for item in node.get("images") or []:
                if made >= per_category:
                    break
                try:
                    raw = download_image(item)
                    im = Image.open(io.BytesIO(raw)).convert("RGB")
                    fn = "%s-%02d.png" % (category, made + 1)
                    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
                    im.save(os.path.join(out_dir, "raw", fn))
                    made += 1
                    print("  saved", fn, flush=True)
                except Exception as e:
                    print("  skip:", e, flush=True)
        remaining = per_category - made
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", default="cake,balloon,confetti,star")
    ap.add_argument("--per-category", type=int, default=10)
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--steps", type=int, default=28)
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip() in PROMPTS]
    total = 0
    for c in cats:
        total += run_category(c, max(1, args.per_category), max(1, args.batch), max(256, args.size), max(8, args.steps))
    print("done:", total, "assets in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
