"""Layer ③ — visible watermark (AGENTS.md 三③).

Two modes:
- tile: low-alpha rotated text grid across the whole image (5%–15% per doc).
- center: half-transparent text bound to the central 60% region — a
  no-face-detection stand-in for "压在主体关键纹理上".

Compositing uses Image.alpha_composite, which is closest to the doc's
overlay/multiply intent without pulling in OpenCV just for this step.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from . import config


def _load_font(size: int) -> ImageFont.ImageFont:
    # Pillow's default bitmap font ignores size; try a common TTF first.
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_layer(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _alpha(value: float) -> int:
    return max(0, min(255, int(round(value * 255))))


def apply_tile(
    image_rgb: Image.Image,
    text: str,
    *,
    alpha: float = config.DEFAULT_VISIBLE_ALPHA,
    font_size: int = config.DEFAULT_VISIBLE_FONT_SIZE,
    angle: float = config.DEFAULT_VISIBLE_ANGLE,
    gap: int = config.DEFAULT_VISIBLE_TILE_GAP,
) -> Image.Image:
    """Tile the watermark across the entire image at low alpha."""
    base = image_rgb.convert("RGBA")
    font = _load_font(font_size)

    # Render one tile then paste rotated copies.
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = max(tw, th)

    tile = _text_layer((tw + pad, th + pad))
    ImageDraw.Draw(tile).text(
        (pad // 2, pad // 2), text, font=font, fill=(255, 255, 255, _alpha(alpha))
    )
    tile = tile.rotate(angle, expand=True, resample=Image.BICUBIC)

    overlay = _text_layer(base.size)
    step_x = max(tile.width, gap)
    step_y = max(tile.height, gap)
    # offset rows for a denser visual lock
    diag = int(math.tan(math.radians(angle)) * step_y)
    for y in range(-tile.height, base.height + tile.height, step_y):
        row_offset = (y // step_y) * diag
        for x in range(-tile.width + row_offset, base.width + tile.width, step_x):
            overlay.alpha_composite(tile, (x, y))

    return Image.alpha_composite(base, overlay).convert("RGB")


def apply_center(
    image_rgb: Image.Image,
    text: str,
    *,
    alpha: float = 0.35,
    font_size: int | None = None,
) -> Image.Image:
    """Stamp a single half-transparent watermark over the central 60% region."""
    base = image_rgb.convert("RGBA")
    w, h = base.size
    target_w = int(w * 0.6)

    size = font_size or max(24, target_w // max(len(text), 1))
    font = _load_font(size)

    overlay = _text_layer(base.size)
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pos = ((w - tw) // 2, (h - th) // 2)
    ImageDraw.Draw(overlay).text(
        pos, text, font=font, fill=(255, 255, 255, _alpha(alpha))
    )
    # Soft shadow for legibility on bright photos
    shadow = _text_layer(base.size)
    ImageDraw.Draw(shadow).text(
        (pos[0] + 2, pos[1] + 2), text, font=font, fill=(0, 0, 0, _alpha(alpha * 0.6))
    )

    composed = Image.alpha_composite(base, shadow)
    composed = Image.alpha_composite(composed, overlay)
    return composed.convert("RGB")


def apply(
    image_rgb: Image.Image,
    text: str,
    *,
    mode: str = config.DEFAULT_VISIBLE_MODE,
    alpha: float = config.DEFAULT_VISIBLE_ALPHA,
) -> Image.Image:
    if mode == "tile":
        return apply_tile(image_rgb, text, alpha=alpha)
    if mode == "center":
        return apply_center(image_rgb, text, alpha=max(alpha, 0.25))
    raise ValueError(f"unknown visible-mode {mode!r}; expected tile|center")
