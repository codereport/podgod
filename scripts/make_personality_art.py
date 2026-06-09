#!/usr/bin/env python3
"""Generate branded cover art for personality meta-podcasts.

Run LOCALLY (not in CI) whenever a personality is added or you want to refresh
art. For each person in personalities.config.json it:

  1. Pulls a lead photo from Wikipedia/Wikimedia Commons (known, attributable
     licenses) for that person's `wikimedia` page title.
  2. Removes the background with rembg (local ML model).
  3. Composites the cutout onto a PodGod brand gradient, adds the circular
     PodGod logo badge (top-left) and the person's name across the bottom.
  4. Writes data/v1/personalities/art/<id>.png (3000x3000, Apple-podcast safe).

It also records the source image URL + license in art-credits.json for
attribution, since the podgod repo is PUBLIC.

People are processed in parallel across all CPU cores.

Usage:
  python scripts/make_personality_art.py            # all personalities
  python scripts/make_personality_art.py --only jensen-huang
  python scripts/make_personality_art.py --no-bg    # skip rembg (square crop)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

# Keep each worker's ML runtime single-threaded. Without this, every rembg/
# onnxruntime session grabs one thread per CPU core; with many parallel workers
# on a high-core machine that oversubscribes threads and crashes the pool
# (BrokenProcessPool). Must be set before onnxruntime is imported (workers fork
# this process, so they inherit these).
for _var in ("OMP_NUM_THREADS", "ONNXRUNTIME_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "personalities.config.json"
ART_DIR = REPO_ROOT / "data" / "v1" / "personalities" / "art"
ASSETS_DIR = SCRIPT_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "logo-circle.png"
# Bundled blocky display font for the name (OFL-licensed, committed to the repo).
NAME_FONT_PATH = ASSETS_DIR / "fonts" / "Bungee-Regular.ttf"
# Optional hand-picked source photos: drop "<id>.<ext>" here to override Wikimedia.
LOCAL_PHOTO_DIR = SCRIPT_DIR / "photos"
# The real PodGod mobile-app icon (public, also shown on the website). Used as
# the badge on every personality cover so the art matches the app's branding.
APP_ICON_PATH = REPO_ROOT / "player-icon.png"
CACHE_DIR = SCRIPT_DIR / ".cache"
CREDITS_PATH = SCRIPT_DIR / "art-credits.json"

USER_AGENT = "PodGod-ArtBot/1.0 (+https://podgod.ca; contact: bot@podgod.ca)"
CANVAS = 3000
LOGO_SIZE = 460
MARGIN = 150

# PodGod brand gradient (matches index.html): pink -> magenta -> indigo.
GRAD_TOP = (255, 77, 141)     # #ff4d8d
GRAD_MID = (200, 80, 242)     # #c850f2
GRAD_BOTTOM = (108, 99, 255)  # #6c63ff
DARK = (11, 14, 23)           # #0b0e17


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
def _font_candidates() -> list[str]:
    out: list[str] = []
    # Prefer Inter (the brand font), then any heavy sans, then DejaVu.
    import glob

    patterns = [
        "/home/linuxbrew/.linuxbrew/Cellar/texlive/*/share/texmf-dist/fonts/opentype/public/inter/Inter-Black.otf",
        "/home/linuxbrew/.linuxbrew/Cellar/texlive/*/share/texmf-dist/fonts/opentype/public/inter/Inter-Bold.otf",
        "/usr/share/fonts/**/Inter-Black.*",
        "/usr/share/fonts/**/Inter-Bold.*",
        "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for pat in patterns:
        out.extend(sorted(glob.glob(pat, recursive=True)))
    return out


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _font_candidates():
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def name_font(size: int) -> ImageFont.FreeTypeFont:
    """Blocky display font for the personality name (bundled Archivo Black)."""
    if NAME_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(NAME_FONT_PATH), size)
        except OSError:
            pass
    return load_font(size)


# --------------------------------------------------------------------------- #
# Brand assets
# --------------------------------------------------------------------------- #
def _gradient_small(n: int = 256) -> Image.Image:
    """Render the diagonal 3-stop brand gradient at low res (smooth, so it
    upscales cleanly without a numpy dependency)."""
    grad = Image.new("RGB", (n, n))
    px = grad.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            if t < 0.5:
                k = t / 0.5
                a, b3 = GRAD_TOP, GRAD_MID
            else:
                k = (t - 0.5) / 0.5
                a, b3 = GRAD_MID, GRAD_BOTTOM
            px[x, y] = tuple(int(a[i] + (b3[i] - a[i]) * k) for i in range(3))
    return grad


def diagonal_gradient(size: int) -> Image.Image:
    """A smooth top-left -> bottom-right brand gradient on a dark base."""
    grad = _gradient_small().resize((size, size), Image.BILINEAR)
    base = Image.new("RGB", (size, size), DARK)
    # Blend slightly toward dark so white text/cutout pop.
    return Image.blend(grad, base, 0.18)


def _row_gradient(size: int) -> Image.Image:
    """Brand gradient at an arbitrary size (rendered small, upscaled)."""
    return _gradient_small().resize((size, size), Image.BILINEAR)


def _circular_mask(size: int) -> Image.Image:
    """Anti-aliased circular alpha mask (supersampled then downscaled)."""
    ss = size * 4
    big = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(big).ellipse([0, 0, ss - 1, ss - 1], fill=255)
    return big.resize((size, size), Image.LANCZOS)


def build_logo(size: int = 1024) -> Image.Image:
    """Fallback PodGod mark when the app icon is unavailable: brand-gradient
    disc with a white 'PG'."""
    grad = _row_gradient(size).convert("RGBA")
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    disc.paste(grad, (0, 0), _circular_mask(size))

    draw = ImageDraw.Draw(disc)
    font = load_font(int(size * 0.46))
    text = "PG"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )
    return disc


def load_app_icon(size: int = 1024) -> Image.Image | None:
    """Load the public PodGod app icon and mask it to a clean circle so any
    white/opaque corners are dropped, while preserving its own transparency."""
    if not APP_ICON_PATH.exists():
        return None
    try:
        icon = Image.open(APP_ICON_PATH).convert("RGBA").resize((size, size), Image.LANCZOS)
    except OSError:
        return None
    circle = _circular_mask(size)
    existing = icon.split()[3]
    # Combine the icon's own alpha with the circle so corners become transparent.
    combined = Image.composite(existing, Image.new("L", (size, size), 0), circle)
    icon.putalpha(combined)
    return icon


def ensure_logo() -> Image.Image:
    """Prefer the real app icon; fall back to a generated PG disc."""
    icon = load_app_icon()
    if icon is not None:
        return icon
    if LOGO_PATH.exists():
        try:
            return Image.open(LOGO_PATH).convert("RGBA")
        except OSError:
            pass
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    logo = build_logo()
    logo.save(LOGO_PATH)
    print(f"  app icon not found; rendered fallback logo -> {LOGO_PATH.relative_to(REPO_ROOT)}")
    return logo


# --------------------------------------------------------------------------- #
# Source photo (Wikipedia / Wikimedia Commons)
# --------------------------------------------------------------------------- #
def fetch_wikimedia_image(title: str) -> tuple[bytes, dict[str, Any]] | None:
    """Return (image_bytes, credit) for a Wikipedia page's lead image."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}"
    try:
        resp = session.get(summary_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  ! wikimedia summary failed for '{title}': {exc}", file=sys.stderr)
        return None

    img_url = (data.get("originalimage") or {}).get("source") or (
        data.get("thumbnail") or {}
    ).get("source")
    if not img_url:
        print(f"  ! no lead image for '{title}'", file=sys.stderr)
        return None

    try:
        img_resp = session.get(img_url, timeout=60)
        img_resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! image download failed for '{title}': {exc}", file=sys.stderr)
        return None

    credit = {
        "wikipedia_title": title,
        "wikipedia_url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        "image_url": img_url,
        "note": "Source image via Wikimedia/Wikipedia. Verify the file's license/attribution on Wikimedia Commons before publishing.",
    }
    return img_resp.content, credit


# --------------------------------------------------------------------------- #
# Compositing
# --------------------------------------------------------------------------- #
_session = None
_session_model: str | None = None


def get_session(model: str):
    """Create (and cache per-process) a rembg session, falling back to
    progressively safer models if the requested one can't be loaded."""
    global _session, _session_model
    if _session is not None and _session_model == model:
        return _session
    from rembg import new_session

    for name in [model, "isnet-general-use", "u2net"]:
        try:
            _session = new_session(name)
            _session_model = name
            if name != model:
                print(f"  (rembg model '{model}' unavailable; using '{name}')", file=sys.stderr)
            return _session
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not load rembg model '{name}': {exc}", file=sys.stderr)
    return None


def refine_alpha(img: Image.Image, erode: int) -> Image.Image:
    """Trim the matte edge to remove the dark halo left by background removal,
    then feather it slightly so the cutout blends onto the gradient."""
    alpha = img.split()[3]
    if erode > 0:
        alpha = alpha.filter(ImageFilter.MinFilter(erode * 2 + 1))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    img.putalpha(alpha)
    return img


def cutout_subject(raw: bytes, remove_bg: bool, model: str, edge_erode: int) -> Image.Image:
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    if not remove_bg:
        return img
    try:
        from rembg import remove
    except ImportError:
        print("  ! rembg not installed; using photo as-is (run pip install -r scripts/requirements-art.txt)", file=sys.stderr)
        return img
    session = get_session(model)
    if session is None:
        return img
    out = remove(img, session=session, post_process_mask=True)
    if isinstance(out, bytes):
        out = Image.open(io.BytesIO(out))
    return refine_alpha(out.convert("RGBA"), edge_erode)


def autocrop_alpha(img: Image.Image) -> Image.Image:
    bbox = img.split()[3].getbbox()
    return img.crop(bbox) if bbox else img


def to_grayscale(img: Image.Image) -> Image.Image:
    """Desaturate the RGB channels while preserving the cutout's alpha."""
    alpha = img.split()[3]
    gray = ImageOps.grayscale(img.convert("RGB"))
    return Image.merge("RGBA", (gray, gray, gray, alpha))


def compose(name: str, subject: Image.Image, grayscale: bool = True) -> Image.Image:
    canvas = diagonal_gradient(CANVAS).convert("RGBA")

    subj = autocrop_alpha(subject)
    if grayscale:
        subj = to_grayscale(subj)
    # Scale the subject to ~78% of canvas height, anchored to the bottom so the
    # face sits in the upper-middle and the name has room below.
    target_h = int(CANVAS * 0.80)
    scale = target_h / subj.height
    target_w = int(subj.width * scale)
    if target_w > CANVAS:
        scale = CANVAS / subj.width
        target_w = CANVAS
        target_h = int(subj.height * scale)
    subj = subj.resize((target_w, target_h), Image.LANCZOS)
    sx = (CANVAS - target_w) // 2
    sy = CANVAS - target_h
    canvas.alpha_composite(subj, (sx, sy))

    # Bottom scrim for text legibility.
    scrim = Image.new("L", (CANVAS, CANVAS), 0)
    sdraw = ImageDraw.Draw(scrim)
    band = int(CANVAS * 0.34)
    for i in range(band):
        y = CANVAS - band + i
        sdraw.line([(0, y), (CANVAS, y)], fill=int(225 * (i / band)))
    dark_layer = Image.new("RGBA", (CANVAS, CANVAS), DARK + (0,))
    dark_layer.putalpha(scrim)
    canvas.alpha_composite(dark_layer)

    # Name, bottom-centered, auto-fit to width.
    draw = ImageDraw.Draw(canvas)
    max_w = CANVAS - 2 * MARGIN
    font_size = 250
    while font_size > 80:
        font = name_font(font_size)
        bbox = draw.textbbox((0, 0), name, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            break
        font_size -= 10
    font = name_font(font_size)
    bbox = draw.textbbox((0, 0), name, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (CANVAS - tw) / 2 - bbox[0]
    ty = CANVAS - MARGIN - th - bbox[1]
    # Soft shadow then white fill.
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((tx, ty), name, font=font, fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(shadow)
    draw.text((tx, ty), name, font=font, fill=(255, 255, 255, 255))

    return canvas.convert("RGB")


# --------------------------------------------------------------------------- #
# Per-person worker
# --------------------------------------------------------------------------- #
def find_local_photo(pid: str):
    """Return a hand-picked source photo at scripts/photos/<id>.<ext>, if present."""
    if not LOCAL_PHOTO_DIR.is_dir():
        return None
    for ext in ("png", "jpg", "jpeg", "webp", "avif"):
        candidate = LOCAL_PHOTO_DIR / f"{pid}.{ext}"
        if candidate.exists():
            return candidate
    return None


def process_person(person: dict[str, Any], remove_bg: bool, model: str, edge_erode: int, grayscale: bool) -> dict[str, Any]:
    pid = person["id"]
    name = person["name"]
    title = person.get("wikimedia") or name
    result: dict[str, Any] = {"id": pid}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{pid}.src"

    raw: bytes | None = None
    credit: dict[str, Any] | None = None
    local_photo = find_local_photo(pid)
    if local_photo is not None:
        raw = local_photo.read_bytes()
        credit = {"local_photo": str(local_photo.relative_to(REPO_ROOT)),
                  "note": "Hand-picked source photo. Verify license/attribution before publishing."}
    elif cache_file.exists():
        raw = cache_file.read_bytes()
        credit = {"wikipedia_title": title, "cached": True}
    else:
        fetched = fetch_wikimedia_image(title)
        if fetched is None:
            result["status"] = "no_image"
            return result
        raw, credit = fetched
        cache_file.write_bytes(raw)

    try:
        subject = cutout_subject(raw, remove_bg, model, edge_erode)
        art = compose(name, subject, grayscale)
        ART_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ART_DIR / f"{pid}.png"
        art.save(out_path, "PNG")
        result["status"] = "ok"
        result["path"] = str(out_path.relative_to(REPO_ROOT))
        result["credit"] = credit
    except Exception as exc:  # noqa: BLE001 - report and continue other people
        result["status"] = "error"
        result["error"] = str(exc)
    return result


def auto_jobs(remove_bg: bool) -> int:
    """Pick a worker count that won't OOM. Each rembg/birefnet worker needs
    ~9-10GB resident, so cap by free RAM (MemAvailable). Without background
    removal the work is light, so just use the cores (capped)."""
    cpu = os.cpu_count() or 1
    if not remove_bg:
        return min(cpu, 8)
    gb_per_worker = 12
    headroom_gb = 8  # leave room for the base process + avoid leaning on swap
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            avail_kb = next(int(l.split()[1]) for l in fh if l.startswith("MemAvailable"))
        avail_gb = avail_kb // (1024 * 1024)
        by_mem = max(1, (avail_gb - headroom_gb) // gb_per_worker)
    except (OSError, StopIteration, ValueError):
        by_mem = 2
    return max(1, min(cpu, by_mem, 6))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", metavar="ID", help="Limit to one or more ids (repeatable).")
    parser.add_argument("--no-bg", action="store_true", help="Skip background removal.")
    parser.add_argument("--color", action="store_true", help="Keep the portrait in color (default: black & white).")
    parser.add_argument(
        "--model",
        default="birefnet-portrait",
        help="rembg model. 'birefnet-portrait' (default) gives the cleanest hair/edges for people; "
             "falls back to isnet-general-use / u2net if unavailable.",
    )
    parser.add_argument(
        "--edge-erode",
        type=int,
        default=1,
        help="Pixels to trim from the cutout edge to remove the background halo (default: 1, 0 disables).",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Parallel workers. Default (0) auto-sizes from free RAM, since the "
             "birefnet model uses ~9GB per worker and over-parallelizing OOMs.",
    )
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    people = config.get("personalities", [])
    if args.only:
        wanted = set(args.only)
        people = [p for p in people if p["id"] in wanted]
    if not people:
        print("No personalities to process.", file=sys.stderr)
        return 2

    remove_bg = not args.no_bg
    requested_jobs = args.jobs if args.jobs > 0 else auto_jobs(remove_bg)
    jobs = max(1, min(requested_jobs, len(people)))
    print(f"Generating art for {len(people)} personality(ies) with {jobs} worker(s)...")

    credits: dict[str, Any] = {}
    if CREDITS_PATH.exists():
        try:
            credits = json.loads(CREDITS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            credits = {}

    grayscale = not args.color
    results: list[dict[str, Any]] = []
    if jobs == 1:
        results = [process_person(p, remove_bg, args.model, args.edge_erode, grayscale) for p in people]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {
                pool.submit(process_person, p, remove_bg, args.model, args.edge_erode, grayscale): p
                for p in people
            }
            for fut in as_completed(futures):
                results.append(fut.result())

    ok = 0
    for r in sorted(results, key=lambda x: x["id"]):
        status = r.get("status")
        if status == "ok":
            ok += 1
            print(f"  {r['id']}: OK -> {r['path']}")
            if r.get("credit"):
                credits[r["id"]] = r["credit"]
        else:
            print(f"  {r['id']}: {status} {r.get('error', '')}".rstrip(), file=sys.stderr)

    CREDITS_PATH.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Done. {ok}/{len(people)} succeeded. Credits -> {CREDITS_PATH.relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
