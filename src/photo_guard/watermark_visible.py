"""Layer ③ — visible watermark (AGENTS.md 三③).

Three modes:
- subject: detect the dominant subject (face → saliency → center) and stamp
  the watermark *across* it so erasing the watermark = repainting the subject
  = destroying the photo. This is the most faithful realisation of the doc's
  「半透明压在脸部 / 主体关键纹理上」 requirement.
- tile: low-alpha rotated text grid across the whole image (5%–15% per doc).
- center: half-transparent text fixed to the geometric centre.

Compositing uses Image.alpha_composite, which is closest to the doc's
overlay/multiply intent without leaving Pillow.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config, subject as subject_mod


def _load_font(size: int) -> ImageFont.ImageFont:
    """Find a sized TTF on this system; fall back to Pillow's default bitmap.

    Pillow's default font ignores the ``size`` argument, so on a system with
    no usable TTF the watermark renders at ~10 px regardless of
    ``--visible-alpha`` / ``--visible-text``. Try the conventional sans-serif
    locations on each major OS before that fallback.
    """
    candidates = (
        # Linux (Debian/Ubuntu — what Docker image and most distros ship)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # Linux (RHEL/Fedora/Alpine)
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        # Windows — both 32-bit and 64-bit installs put fonts here
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    )
    for path in candidates:
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
    if mode == "subject":
        return apply_subject(image_rgb, text, alpha=max(alpha, 0.30))
    raise ValueError(
        f"unknown visible-mode {mode!r}; expected subject|tile|center"
    )


def apply_subject(
    image_rgb: Image.Image,
    text: str,
    *,
    alpha: float = 0.35,
    padding_frac: float = 0.05,
) -> Image.Image:
    """Stamp the watermark across the detected subject region.

    Uses `subject.detect_subject` (face → saliency → center fallback) so the
    output binds the watermark to high-importance pixels: erasing it forces
    a full subject repaint, which is the deterrent AGENTS.md 三③ describes.
    """
    base = image_rgb.convert("RGBA")
    w, h = base.size

    bgr = np.array(image_rgb.convert("RGB"))[:, :, ::-1].copy()
    box = subject_mod.detect_subject(bgr)

    pad_x = int(box.w * padding_frac)
    pad_y = int(box.h * padding_frac)
    region_w = max(64, box.w - 2 * pad_x)
    region_h = max(40, box.h - 2 * pad_y)

    target_w = int(region_w * 0.95)
    size = max(24, target_w // max(len(text), 1))
    # cap so a tiny face on a large image doesn't get a 200px font
    size = min(size, max(28, h // 6))
    font = _load_font(size)

    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    cx, cy = box.center()
    pos_x = max(0, min(w - tw, cx - tw // 2))
    pos_y = max(0, min(h - th, cy - th // 2))

    shadow = _text_layer(base.size)
    ImageDraw.Draw(shadow).text(
        (pos_x + 2, pos_y + 2),
        text,
        font=font,
        fill=(0, 0, 0, _alpha(alpha * 0.6)),
    )
    overlay = _text_layer(base.size)
    ImageDraw.Draw(overlay).text(
        (pos_x, pos_y),
        text,
        font=font,
        fill=(255, 255, 255, _alpha(alpha)),
    )

    composed = Image.alpha_composite(base, shadow)
    composed = Image.alpha_composite(composed, overlay)
    return composed.convert("RGB")
