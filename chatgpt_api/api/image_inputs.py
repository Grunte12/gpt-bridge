"""Image input and edit policy helpers for API request bodies."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from chatgpt_api.core.types import ContentPart, ImageInput

MAX_IMAGE_INPUTS_PER_REQUEST = 10

IMAGE_EDIT_ASPECT_RATIOS = {"auto", "1:1", "3:4", "9:16", "4:3", "16:9"}

IMAGE_EDIT_ASPECT_RATIO_WARNING = (
    "Image edits preserve layout best when the source image already matches one of "
    "the supported ratios: auto, 1:1, 3:4, 9:16, 4:3, or 16:9. If auto is used "
    "with an unusual source ratio, the result can shift, crop, or resize elements."
)


def image_inputs_from_body(body: dict[str, Any], *, require: bool) -> list[ImageInput]:
    raw_inputs: list[Any] = []
    containers: list[dict[str, Any]] = [body]
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    containers.append(metadata)
    for container in containers:
        for key in ("images", "input_images"):
            value = container.get(key)
            if isinstance(value, list):
                raw_inputs.extend(value)
        for key in ("image", "input_image", "image_url"):
            value = container.get(key)
            if value is not None:
                raw_inputs.append(value)
    if not raw_inputs and require:
        raise ValueError("image input is required; pass image, images, input_image, input_images, or image_url")
    if len(raw_inputs) > MAX_IMAGE_INPUTS_PER_REQUEST:
        raise ValueError(f"at most {MAX_IMAGE_INPUTS_PER_REQUEST} input images are supported per request")
    return [image_input_from_reference(reference, metadata) for reference in raw_inputs]


def image_input_from_reference(reference: Any, metadata: dict[str, Any] | None = None) -> ImageInput:
    metadata = metadata or {}
    if isinstance(reference, ContentPart) and reference.kind == "image_bytes" and reference.data is not None:
        return ImageInput(reference.data, reference.mime_type or "image/png", reference.name)
    if isinstance(reference, ImageInput):
        return reference
    if isinstance(reference, bytes):
        return ImageInput(
            reference,
            str_or_none(metadata.get("mime_type")) or str_or_none(metadata.get("mimeType")) or "image/png",
            str_or_none(metadata.get("name")) or str_or_none(metadata.get("filename")),
        )
    if isinstance(reference, dict):
        nested = reference.get("image_url")
        if isinstance(nested, dict):
            nested_url = str_or_none(nested.get("url"))
            if nested_url:
                return image_input_from_reference(nested_url, {**reference, **nested})
        nested_metadata = dict(metadata)
        for key in ("mime_type", "mimeType", "name", "filename"):
            if reference.get(key) is not None:
                nested_metadata[key] = reference.get(key)
        for key in ("data_url", "dataUrl", "url", "path", "image", "input_image", "base64", "b64_json", "data"):
            if reference.get(key) is not None:
                return image_input_from_reference(reference.get(key), nested_metadata)
        raise ValueError("image object must include one of: data_url, url, path, image, input_image, base64, b64_json, data")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("image reference must be a non-empty string, bytes, or object")

    value = reference.strip()
    if value.startswith("data:"):
        return image_input_from_data_url(value, metadata)
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return download_image_input(value, metadata)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        return image_input_from_path(path, metadata)
    local_path = Path(value).expanduser()
    if local_path.is_file():
        return image_input_from_path(local_path, metadata)
    if looks_like_base64_image(value):
        return ImageInput(
            base64.b64decode(value),
            str_or_none(metadata.get("mime_type")) or str_or_none(metadata.get("mimeType")) or "image/png",
            str_or_none(metadata.get("name")) or str_or_none(metadata.get("filename")),
        )
    return image_input_from_path(Path(value), metadata)


def image_input_from_data_url(value: str, metadata: dict[str, Any]) -> ImageInput:
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", value, flags=re.DOTALL)
    if not match:
        raise ValueError("invalid data URL image")
    mime_type = match.group(1) or "image/png"
    payload = match.group(3)
    data = base64.b64decode(payload) if match.group(2) else unquote(payload).encode("utf-8")
    return ImageInput(data, mime_type, str_or_none(metadata.get("name")) or str_or_none(metadata.get("filename")))


def looks_like_base64_image(value: str) -> bool:
    if len(value) < 64 or re.search(r"[^A-Za-z0-9+/=\s]", value):
        return False
    return True


def download_image_input(url: str, metadata: dict[str, Any]) -> ImageInput:
    request = UrlRequest(url, headers={"User-Agent": "gpt-bridge/0.1"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - local bridge intentionally accepts user-provided URLs.
        data = response.read()
        mime_type = response.headers.get_content_type() or str_or_none(metadata.get("mime_type")) or "image/png"
    name = str_or_none(metadata.get("name")) or str_or_none(metadata.get("filename")) or Path(urlparse(url).path).name
    return ImageInput(data, mime_type, name or None)


def image_input_from_path(path: Path, metadata: dict[str, Any]) -> ImageInput:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"image file not found: {path}")
    guessed, _ = mimetypes.guess_type(str(resolved))
    mime_type = str_or_none(metadata.get("mime_type")) or str_or_none(metadata.get("mimeType")) or guessed or "image/png"
    name = str_or_none(metadata.get("name")) or str_or_none(metadata.get("filename")) or resolved.name
    return ImageInput(resolved.read_bytes(), mime_type, name)


def image_aspect_ratio_from_body(body: dict[str, Any]) -> str:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    raw = (
        str_or_none(body.get("aspect_ratio"))
        or str_or_none(metadata.get("aspect_ratio"))
        or aspect_ratio_from_size(str_or_none(body.get("size")) or str_or_none(metadata.get("size")))
        or "auto"
    )
    normalized = raw.strip().lower()
    if normalized not in IMAGE_EDIT_ASPECT_RATIOS:
        raise ValueError("aspect_ratio must be one of: auto, 1:1, 3:4, 9:16, 4:3, 16:9")
    return normalized


def aspect_ratio_from_size(size: str | None) -> str | None:
    if not size:
        return None
    normalized = size.strip().lower().replace(" ", "")
    aliases = {
        "1024x1024": "1:1",
        "1024x1792": "9:16",
        "1792x1024": "16:9",
        "2048x1536": "4:3",
    }
    return aliases.get(normalized)


def image_edit_prompt(prompt: str, aspect_ratio: str) -> str:
    parts = [
        prompt.strip(),
        "Use the attached image input as visual reference. If multiple images are attached, combine or reconcile them into one new output image according to the prompt.",
        "Return exactly one edited/generated image.",
    ]
    if aspect_ratio != "auto":
        parts.append(f"Make the aspect ratio {aspect_ratio}.")
    return "\n\n".join(parts)


def default_vision_prompt(mode: str) -> str:
    if mode == "ocr":
        return "OCR the image. Extract all visible text faithfully, preserve reading order, and briefly note uncertain text."
    if mode == "describe":
        return "Describe the image with enough context for a developer or creative tool to understand the subject, layout, text, style, and important details."
    return "Analyze the attached image."


def str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
