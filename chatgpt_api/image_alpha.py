"""Create a real PNG alpha channel from a flat generated-image matte."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw


DEFAULT_MATTE = (255, 0, 255)


class TransparencyError(ValueError):
    """Raised when an opaque image cannot be keyed safely."""


def _hex_color(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in color)


def _border_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    step = max(1, min(width, height) // 256)
    pixels = rgb.load()
    samples: list[tuple[int, int, int]] = []
    for x in range(0, width, step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, height - 1])
    for y in range(step, height - 1, step):
        samples.append(pixels[0, y])
        samples.append(pixels[width - 1, y])
    return samples


def _distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return max(abs(left[index] - right[index]) for index in range(3))


def _dominant_border_color(
    image: Image.Image,
    expected: tuple[int, int, int],
    tolerance: int,
) -> tuple[tuple[int, int, int], float]:
    samples = _border_pixels(image)
    if not samples:
        raise TransparencyError("image has no border pixels")
    expected_ratio = sum(_distance(sample, expected) <= tolerance * 2 for sample in samples) / len(samples)
    if expected_ratio >= 0.55:
        near = [sample for sample in samples if _distance(sample, expected) <= tolerance * 2]
        color = tuple(round(sum(sample[index] for sample in near) / len(near)) for index in range(3))
        return color, expected_ratio

    buckets = Counter(tuple(channel // 16 for channel in sample) for sample in samples)
    bucket, count = buckets.most_common(1)[0]
    members = [sample for sample in samples if tuple(channel // 16 for channel in sample) == bucket]
    color = tuple(round(sum(sample[index] for sample in members) / len(members)) for index in range(3))
    ratio = count / len(samples)
    if ratio < 0.55:
        raise TransparencyError(
            "generated background is not flat enough for safe alpha removal; "
            "retry with a perfectly flat solid #FF00FF background"
        )
    return color, ratio


def _difference_map(image: Image.Image, matte: tuple[int, int, int]) -> Image.Image:
    channels = image.convert("RGB").split()
    differences = [
        ImageChops.difference(channel, Image.new("L", image.size, matte[index]))
        for index, channel in enumerate(channels)
    ]
    return ImageChops.lighter(ImageChops.lighter(differences[0], differences[1]), differences[2])


def _edge_connected_mask(difference: Image.Image, threshold: int) -> Image.Image:
    candidates = difference.point(lambda value: 255 if value <= threshold else 0, mode="L")
    expanded = Image.new("L", (candidates.width + 2, candidates.height + 2), 255)
    expanded.paste(candidates, (1, 1))
    ImageDraw.floodfill(expanded, (0, 0), 128, thresh=0)
    connected = expanded.crop((1, 1, candidates.width + 1, candidates.height + 1))
    return connected.point(lambda value: 255 if value == 128 else 0, mode="L")


def _alpha_from_matte(
    image: Image.Image,
    matte: tuple[int, int, int],
    *,
    tolerance: int,
    feather: int,
) -> Image.Image:
    difference = _difference_map(image, matte)
    hard_background = _edge_connected_mask(difference, tolerance)
    soft_background = _edge_connected_mask(difference, tolerance + feather)
    distance_pixels = difference.load()
    hard_pixels = hard_background.load()
    soft_pixels = soft_background.load()
    alpha = Image.new("L", image.size, 255)
    alpha_pixels = alpha.load()
    for y in range(image.height):
        for x in range(image.width):
            if hard_pixels[x, y]:
                alpha_pixels[x, y] = 0
            elif soft_pixels[x, y]:
                distance = distance_pixels[x, y]
                alpha_pixels[x, y] = max(0, min(255, round((distance - tolerance) * 255 / feather)))
    return alpha


def _has_transparency(image: Image.Image) -> bool:
    if image.mode not in {"LA", "RGBA"}:
        return False
    minimum, _maximum = image.getchannel("A").getextrema()
    return minimum < 255


def _transparent_border_ratio(image: Image.Image) -> float:
    alpha = image.getchannel("A")
    width, height = image.size
    step = max(1, min(width, height) // 256)
    pixels = alpha.load()
    samples: list[int] = []
    for x in range(0, width, step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, height - 1])
    for y in range(step, height - 1, step):
        samples.append(pixels[0, y])
        samples.append(pixels[width - 1, y])
    return sum(value <= 8 for value in samples) / len(samples) if samples else 0.0


def ensure_transparent_png(
    source: str | Path,
    destination: str | Path | None = None,
    *,
    expected_matte: tuple[int, int, int] = DEFAULT_MATTE,
    tolerance: int = 28,
    feather: int = 36,
) -> dict[str, Any]:
    """Preserve real alpha or remove one flat edge-connected matte safely."""

    if tolerance < 0 or feather < 1 or tolerance + feather > 255:
        raise TransparencyError("tolerance and feather must define a range within 0..255")
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise TransparencyError(f"input image not found: {source_path}")
    output_path = Path(destination or source_path).expanduser().resolve()
    if output_path.suffix.lower() != ".png":
        raise TransparencyError("transparent output path must end in .png")

    with Image.open(source_path) as opened:
        opened.load()
        image = opened.convert("RGBA")

    existing_transparency = _has_transparency(image)
    border_alpha_ratio = _transparent_border_ratio(image)
    already_transparent = existing_transparency and border_alpha_ratio >= 0.9
    matte: tuple[int, int, int] | None = None
    border_confidence: float | None = None
    if not already_transparent:
        matte, border_confidence = _dominant_border_color(image, expected_matte, tolerance)
        alpha = _alpha_from_matte(image, matte, tolerance=tolerance, feather=feather)
        if existing_transparency:
            alpha = ImageChops.multiply(image.getchannel("A"), alpha)
        image.putalpha(alpha)

    alpha = image.getchannel("A")
    minimum, maximum = alpha.getextrema()
    histogram = alpha.histogram()
    transparent_pixels = sum(histogram[:255])
    if minimum == 255 or transparent_pixels == 0:
        raise TransparencyError(
            "output still has no transparent pixels; retry generation with a flat #FF00FF matte"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".png",
        prefix=f".{output_path.stem}-",
        dir=output_path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "ok": True,
        "path": str(output_path),
        "already_transparent": already_transparent,
        "matte": _hex_color(matte) if matte else None,
        "border_confidence": round(border_confidence, 3) if border_confidence is not None else None,
        "border_alpha_ratio": round(_transparent_border_ratio(image), 3),
        "alpha_min": minimum,
        "alpha_max": maximum,
        "transparent_pixels": transparent_pixels,
    }


def compact_transparency_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
