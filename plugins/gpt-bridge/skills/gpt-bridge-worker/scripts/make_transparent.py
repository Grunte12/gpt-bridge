#!/usr/bin/env python3
"""Verify real PNG alpha or remove a flat generated-image matte."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chatgpt_api.image_alpha import (
    TransparencyError,
    compact_transparency_result,
    ensure_transparent_png,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = ensure_transparent_png(args.input, args.out)
    except TransparencyError as exc:
        print(f"transparent asset error: {exc}", file=sys.stderr)
        return 2
    print(compact_transparency_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
