from __future__ import annotations

import io

from PIL import Image


def mean_luma(png_bytes: bytes) -> float:
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    pixels = image.getdata()
    count = len(pixels)
    if count == 0:
        raise ValueError("empty screenshot")
    return sum(pixels) / count


def is_black(luma: float, luma_black: float) -> bool:
    return luma < luma_black
