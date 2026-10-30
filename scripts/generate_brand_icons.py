#!/usr/bin/env python3
"""Export the unchanged circular logo and a square icon with extended color.

Run from any directory:
    python scripts/generate_brand_icons.py

Requires Pillow and rsvg-convert (librsvg). Outputs go to branding/ by default.
The circle PNG is a byte-for-byte copy of the public source; its SVG embeds
the same PNG to preserve every detail. The square extends the sampled gradient
across the canvas and extracts the existing waveform without redrawing it.
The SVGs retain embedded raster artwork rather than approximating its shapes.
"""

from __future__ import annotations

import argparse
import base64
import bisect
import hashlib
import io
import shutil
import statistics
import subprocess
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "player-icon-borderless.png"


def gradient_stops(image: Image.Image) -> list[tuple[float, tuple[int, ...]]]:
    """Sample the existing diagonal background, excluding the white waveform.

    Median samples remove the original texture from the extension, while the
    embedded image keeps every original pixel inside the circle. Extrapolate
    the end colors into the formerly transparent corners of the square.
    """
    bins: list[list[tuple[int, ...]]] = [[] for _ in range(128)]
    width, height = image.size
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha != 255 or min(red, green, blue) > 160:
                continue
            offset = (x / (width - 1) + y / (height - 1)) / 2
            bins[round(offset * (len(bins) - 1))].append((red, green, blue))

    samples = []
    for index, values in enumerate(bins):
        if not values:
            continue
        neighborhood = [color for nearby in bins[max(0, index - 2):index + 3] for color in nearby]
        color = tuple(round(statistics.median(channel)) for channel in zip(*neighborhood))
        samples.append((index / (len(bins) - 1), color))
    if len(samples) < 20:
        raise ValueError("The source must contain the opaque, colored circular logo")

    def extend(offset: float, points: list[tuple[float, tuple[int, ...]]]) -> tuple[int, ...]:
        mean_x = statistics.mean(x for x, _ in points)
        variance = sum((x - mean_x) ** 2 for x, _ in points)
        result = []
        for channel in range(3):
            mean_y = statistics.mean(color[channel] for _, color in points)
            slope = sum((x - mean_x) * (color[channel] - mean_y) for x, color in points) / variance
            result.append(max(0, min(255, round(mean_y + slope * (offset - mean_x)))))
        return tuple(result)

    return [(0.0, extend(0.0, samples[:16])), *samples, (1.0, extend(1.0, samples[-16:]))]


def extract_waveform(image: Image.Image, stops: list[tuple[float, tuple[int, ...]]]) -> bytes:
    """Keep the five existing white strokes, including their antialiased edges.

    Find their connected white centers, then recover edge opacity against the
    sampled background. Restrict extraction to the stroke bounds so background
    texture cannot leave a circular outline on the square export.
    """
    width, height = image.size
    remaining = {
        (x, y) for y in range(height) for x in range(width)
        if min(image.getpixel((x, y))[:3]) > 180 and image.getpixel((x, y))[3] == 255
    }
    bounds = []
    while remaining:
        first = remaining.pop()
        queue = deque([first])
        points = [first]
        while queue:
            x, y = queue.popleft()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in remaining:
                    remaining.remove(point)
                    points.append(point)
                    queue.append(point)
        if len(points) >= width:
            xs, ys = zip(*points)
            bounds.append((max(0, min(xs) - 3), max(0, min(ys) - 3), min(width, max(xs) + 4), min(height, max(ys) + 4)))
    if len(bounds) != 5:
        raise ValueError("Expected the five white waveform strokes in the source")

    offsets = [offset for offset, _ in stops]
    waveform = Image.new("RGBA", image.size, (255, 255, 255, 0))
    for left, top, right, bottom in bounds:
        for y in range(top, bottom):
            for x in range(left, right):
                offset = (x / (width - 1) + y / (height - 1)) / 2
                index = min(len(stops) - 1, bisect.bisect_right(offsets, offset))
                start, first = stops[index - 1]
                end, last = stops[index]
                weight = (offset - start) / (end - start)
                background_green = first[1] + weight * (last[1] - first[1])
                alpha = round(255 * (image.getpixel((x, y))[1] - background_green) / (255 - background_green))
                waveform.putpixel((x, y), (255, 255, 255, max(0, min(255, alpha)) if alpha >= 12 else 0))
    result = io.BytesIO()
    waveform.save(result, format="PNG", optimize=True)
    return result.getvalue()


def generate(source: Path, output: Path, size: int = 512) -> None:
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise RuntimeError("Install rsvg-convert (librsvg) to render the square PNG")
    if size < 1:
        raise ValueError("PNG size must be positive")
    original = source.read_bytes()
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    width, height = image.size
    if width != height or width < 2:
        raise ValueError("The source icon must have a square canvas")
    if image.getchannel("A").getextrema() != (0, 255):
        raise ValueError("The source circle must have a transparent background")

    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(original).hexdigest()
    encoded = base64.b64encode(original).decode("ascii")
    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">\n'
        '  <title id="title">POD GOD</title>\n'
        '  <desc id="description">Original circular artwork preserved as an embedded PNG.</desc>\n'
        f'  <!-- Source PNG SHA-256: {digest} -->\n'
    )
    artwork = f'  <image width="{width}" height="{height}" href="data:image/png;base64,{encoded}"/>\n'
    circle = header + artwork + '</svg>\n'
    sampled_stops = gradient_stops(image)
    stops = "\n".join(
        f'      <stop offset="{offset:.6f}" stop-color="#{red:02x}{green:02x}{blue:02x}"/>'
        for offset, (red, green, blue) in sampled_stops
    )
    background = (
        '  <defs>\n'
        f'    <linearGradient id="background" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{width}" y2="{height}">\n'
        f'{stops}\n'
        '    </linearGradient>\n'
        '  </defs>\n'
        f'  <rect width="{width}" height="{height}" fill="url(#background)"/>\n'
    )
    waveform = base64.b64encode(extract_waveform(image, sampled_stops)).decode("ascii")
    square_header = header.replace(
        "Original circular artwork preserved as an embedded PNG.",
        "Full-square gradient with the waveform extracted from the original artwork.",
    )
    square_artwork = f'  <image width="{width}" height="{height}" href="data:image/png;base64,{waveform}"/>\n'
    square = square_header + background + square_artwork + '</svg>\n'

    (output / "pod-god-circle.png").write_bytes(original)
    (output / "pod-god-circle.svg").write_text(circle, encoding="utf-8")
    square_path = output / "pod-god-square.svg"
    square_path.write_text(square, encoding="utf-8")
    subprocess.run([
        renderer, "--width", str(size), "--height", str(size),
        "--output", str(output / "pod-god-square.png"), str(square_path),
    ], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "branding")
    parser.add_argument("--size", type=int, default=512, help="Square PNG export size (default: 512)")
    args = parser.parse_args()
    generate(args.source, args.output_dir, args.size)
    print(f"Exported circle and square PNG/SVG files to {args.output_dir}")


if __name__ == "__main__":
    main()
