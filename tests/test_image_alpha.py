from pathlib import Path

import pytest
from PIL import Image

from chatgpt_api.image_alpha import TransparencyError, ensure_transparent_png


def test_flat_matte_becomes_real_png_alpha(tmp_path):
    source = tmp_path / "opaque.png"
    output = tmp_path / "asset.png"
    image = Image.new("RGB", (40, 40), (255, 0, 255))
    for y in range(10, 30):
        for x in range(10, 30):
            image.putpixel((x, y), (20, 80, 220))
    image.save(source)

    result = ensure_transparent_png(source, output)

    assert result["ok"] is True
    assert result["already_transparent"] is False
    assert result["matte"] == "#FF00FF"
    with Image.open(output) as rendered:
        assert rendered.mode == "RGBA"
        assert rendered.getpixel((0, 0))[3] == 0
        assert rendered.getpixel((20, 20)) == (20, 80, 220, 255)


def test_existing_alpha_is_preserved(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "asset.png"
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    for y in range(5, 15):
        for x in range(5, 15):
            image.putpixel((x, y), (230, 50, 40, 255))
    image.save(source)

    result = ensure_transparent_png(source, output)

    assert result["already_transparent"] is True
    with Image.open(output) as rendered:
        assert rendered.getpixel((0, 0))[3] == 0
        assert rendered.getpixel((10, 10)) == (230, 50, 40, 255)


def test_sparse_internal_alpha_does_not_skip_opaque_matte_removal(tmp_path):
    source = tmp_path / "partial.png"
    image = Image.new("RGBA", (24, 24), (255, 0, 255, 255))
    for y in range(7, 17):
        for x in range(7, 17):
            image.putpixel((x, y), (30, 110, 230, 255))
    image.putpixel((12, 12), (30, 110, 230, 120))
    image.save(source)

    result = ensure_transparent_png(source, tmp_path / "asset.png")

    assert result["already_transparent"] is False
    assert result["border_alpha_ratio"] == 1.0
    with Image.open(tmp_path / "asset.png") as rendered:
        assert rendered.getpixel((0, 0))[3] == 0
        assert rendered.getpixel((12, 12))[3] == 120


def test_non_flat_border_is_rejected_instead_of_damaging_asset(tmp_path):
    source = tmp_path / "busy.png"
    image = Image.new("RGB", (32, 32), (20, 20, 20))
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for x in range(32):
        image.putpixel((x, 0), colors[x % len(colors)])
        image.putpixel((x, 31), colors[(x + 1) % len(colors)])
    for y in range(1, 31):
        image.putpixel((0, y), colors[(y + 2) % len(colors)])
        image.putpixel((31, y), colors[(y + 3) % len(colors)])
    image.save(source)

    with pytest.raises(TransparencyError, match="not flat enough"):
        ensure_transparent_png(source, tmp_path / "asset.png")


def test_transparent_output_requires_png_extension(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(source)

    with pytest.raises(TransparencyError, match="must end in .png"):
        ensure_transparent_png(source, tmp_path / "asset.webp")
