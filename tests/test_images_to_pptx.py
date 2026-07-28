import importlib.util
import struct
import zlib
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "gpt-bridge"
    / "skills"
    / "gpt-bridge-worker"
    / "scripts"
    / "images_to_pptx.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("images_to_pptx", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_images_to_pptx_creates_ordered_full_bleed_slides(tmp_path):
    module = _load_module()
    first = tmp_path / "slide-01.png"
    second = tmp_path / "slide-02.png"
    first.write_bytes(_png(160, 90, (255, 0, 0)))
    second.write_bytes(_png(160, 100, (0, 0, 255)))
    output = tmp_path / "deck.pptx"

    module.create_pptx([first, second], output, "Visual deck")

    with ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "ppt/slides/slide1.xml" in names
        assert "ppt/slides/slide2.xml" in names
        assert "ppt/media/image1.png" in names
        assert "ppt/media/image2.png" in names
        assert archive.read("ppt/media/image1.png") == first.read_bytes()
        presentation = archive.read("ppt/presentation.xml").decode()
        assert presentation.count("<p:sldId ") == 2
        assert 'type="screen16x9"' in presentation
        slide_one = archive.read("ppt/slides/slide1.xml").decode()
        slide_two = archive.read("ppt/slides/slide2.xml").decode()
        assert "<a:srcRect" not in slide_one
        assert '<a:srcRect t="' in slide_two


def test_images_to_pptx_rejects_unsupported_input(tmp_path):
    module = _load_module()
    source = tmp_path / "slide.webp"
    source.write_bytes(b"not-an-image")

    try:
        module.create_pptx([source], tmp_path / "deck.pptx", "Bad")
    except ValueError as exc:
        assert "supported PNG or JPEG" in str(exc)
    else:
        raise AssertionError("unsupported image should fail")
