#!/usr/bin/env python3
"""Draw a CAD-style illustration for every /worth item that has no real listing photo.

Every item on /worth must carry an image (Aidan, 2026-10-01). A real photo from a listing comes
first; this script covers the rest with a clean technical rendering from Gemini's image model, so a
person can at least orient visually around the piece of equipment. The drawing is labelled as such on
the page — it is an illustration, never evidence.

    scripts/make_item_images.py --limit 300        # draw the next 300 items that need one, in rank order
    scripts/make_item_images.py --estimate         # how many are left and what the tail would cost

Model: gemini-2.5-flash-image (1,290 output tokens per image at $30/M = $0.0387; measured 2026-10-01,
5s per image). gemini-3-pro-image-preview draws a slightly cleaner module for 3.5x the price; not worth
it for a 512px thumbnail. Key: GEMINI_API_KEY in ~/Desktop/bricks/.env (the make-art skill's keyring).

Raw PNGs are cached under data/cache/images/<item id>.png (gitignored, never re-drawn); the page gets
site/worth/img/<item id>.jpg at 512px. data/cache/images/ledger.jsonl records every call's tokens.
Reads data/worth_items.json, written by scripts/build_worth.py; run build_worth.py again afterwards so
the page knows which items now have a drawing.
"""
import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "cache" / "images"
OUT = ROOT / "site" / "worth" / "img"
LEDGER = RAW / "ledger.jsonl"
MODEL = "gemini-2.5-flash-image"
USD_PER_OUTPUT_TOKEN = 30 / 1_000_000
USD_PER_INPUT_TOKEN = 0.30 / 1_000_000
STYLE = ("Clean technical product illustration in the style of a manufacturer's catalog CAD rendering. Isometric three-quarter "
         "view of the single object, centered, filling most of the frame, on a flat light warm-grey background. Thin precise "
         "outlines, soft studio shading, muted industrial palette (grey, graphite, one muted accent colour at most). "
         "No people, no hands, no scene, no text, no lettering, no logos, no labels, no watermark, no border.")


def load_key() -> str:
    for line in (Path.home() / "Desktop" / "bricks" / ".env").read_text().splitlines():
        if line.startswith("GEMINI_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("GEMINI_API_KEY not found in bricks/.env")


def prompt_for(item: dict) -> str:
    what = ", ".join(x for x in (item.get("manufacturer"), item.get("model"), item.get("part")) if x)
    cls = item.get("equipment_class") or ""
    return f"{STYLE}\n\nThe object: {what}. Equipment type: {cls or 'industrial equipment part'}. Draw what this part physically looks like."


def draw(item: dict, key: str) -> dict:
    body = {"contents": [{"parts": [{"text": prompt_for(item)}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.read().decode()[:300]}")
    for p in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        blob = p.get("inlineData") or p.get("inline_data")
        if blob and blob.get("data"):
            u = resp.get("usageMetadata") or {}
            return {"png": base64.b64decode(blob["data"]), "in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0)}
    raise RuntimeError("no image in response: " + json.dumps(resp)[:300])


def publish(png: bytes, item_id: str):
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((512, 512))
    im.save(OUT / f"{item_id}.jpg", "JPEG", quality=78, optimize=True)


def needing(items: list[dict]) -> list[dict]:
    """Items with no real photo and no drawing yet, best-evidenced first (the order the page ranks them)."""
    return [it for it in items if not it.get("photo") and not (RAW / f"{it['id']}.png").exists()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--estimate", action="store_true")
    args = ap.parse_args()
    items = json.loads((ROOT / "data" / "worth_items.json").read_text())
    todo = needing(items)
    drawn = sum(1 for it in items if not it.get("photo") and (RAW / f"{it['id']}.png").exists())
    est = len(todo) * (1290 * USD_PER_OUTPUT_TOKEN + 120 * USD_PER_INPUT_TOKEN)
    print(f"{len(items)} items: {sum(1 for it in items if it.get('photo'))} with a real photo, {drawn} drawn, {len(todo)} still need a drawing (~${est:,.2f} at {MODEL} rates)")
    # republish any cached PNG whose jpg is missing (a fresh checkout)
    for it in items:
        if (RAW / f"{it['id']}.png").exists() and not (OUT / f"{it['id']}.jpg").exists():
            publish((RAW / f"{it['id']}.png").read_bytes(), it["id"])
    if args.estimate or not args.limit:
        return
    key = load_key()
    RAW.mkdir(parents=True, exist_ok=True)
    spent_in = spent_out = n = 0
    t0 = time.time()
    for it in todo[:args.limit]:
        try:
            r = draw(it, key)
        except RuntimeError as e:
            print(f"  {it['id']}: {e}", file=sys.stderr)
            if "429" in str(e):
                time.sleep(20)
            continue
        (RAW / f"{it['id']}.png").write_bytes(r["png"])
        publish(r["png"], it["id"])
        spent_in += r["in"]
        spent_out += r["out"]
        n += 1
        with LEDGER.open("a") as f:
            f.write(json.dumps({"id": it["id"], "model": MODEL, "in": r["in"], "out": r["out"], "at": datetime.now(timezone.utc).isoformat()}) + "\n")
        if n % 25 == 0:
            print(f"  {n} drawn, {time.time() - t0:.0f}s, ${spent_in * USD_PER_INPUT_TOKEN + spent_out * USD_PER_OUTPUT_TOKEN:.2f}", flush=True)
    cost = spent_in * USD_PER_INPUT_TOKEN + spent_out * USD_PER_OUTPUT_TOKEN
    print(f"drew {n} images in {time.time() - t0:.0f}s: {spent_in:,} input + {spent_out:,} output tokens = ${cost:.2f} "
          f"(${cost / n:.4f} each)" if n else "drew nothing")


if __name__ == "__main__":
    main()
