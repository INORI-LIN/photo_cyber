"""Pre-publish compression (AGENTS.md 五 checklist + 四 反二次压缩)."""
from __future__ import annotations

from PIL import Image

from . import config


def fit_long_edge(
    image: Image.Image, long_edge: int = config.DEFAULT_LONG_EDGE
) -> Image.Image:
    """Downscale to ``long_edge``; zero preserves size and negatives are invalid."""
    if long_edge < 0:
        raise ValueError("long_edge must be zero (keep original) or a positive integer")
    if long_edge == 0:
        return image
    w, h = image.size
    longest = max(w, h)
    if longest <= long_edge:
        return image
    scale = long_edge / longest
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return image.resize(new_size, Image.Resampling.LANCZOS)
