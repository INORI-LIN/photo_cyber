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
    """Find a sized TTF on this system; fall back to Pillow's sized built-in font.

    Q2/N3: Pillow's unsized ``load_default()`` ignores ``size`` and renders at ~10 px —
    the Docker image installs no font package, so every visible mode silently produced a
    near-invisible watermark there. Pillow >= 10.1 accepts ``size`` and scales its built-in
    Aileron font; the project floor is 12.2. The TTF list stays first because a real OS font
    has better glyph coverage (notably CJK on some platforms).
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
    try:
        return ImageFont.load_default(size=size)
    except OSError:
        # A Pillow built without FreeType cannot load a scalable default; the unsized
        # bitmap is the only option left (same ~10 px result, but no crash).
        return ImageFont.load_default()


def _text_layer(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _alpha(value: float) -> int:
    return max(0, min(255, int(round(value * 255))))


def _rendered_width(font: ImageFont.ImageFont, text: str) -> int:
    bbox = font.getbbox(text)
    return max(1, bbox[2] - bbox[0])


def _fit_font(text: str, target_w: int, base_size: int) -> ImageFont.ImageFont:
    """Shrink ``base_size`` until ``text`` fits ``target_w`` (P58).

    The legacy ``target_w // len(text)`` estimate is the starting point on purpose: it
    keeps existing Latin renders byte-identical. That estimate assumes one em per character,
    so CJK glyphs (or the fallback tofu) and the 24 px floor overflowed the region; the
    correction is measured from the rendered bbox and only ever shrinks.
    """
    font = _load_font(base_size)
    width = _rendered_width(font, text)
    if width <= target_w or base_size <= 1:
        return font
    size = max(1, base_size * target_w // width)
    font = _load_font(size)
    # Hinting/rounding can leave a pixel or two over; correct once more.
    width = _rendered_width(font, text)
    if width > target_w:
        size = max(1, size * target_w // width)
        font = _load_font(size)
    return font


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
        # P16: wrap the diagonal shift, or rows far down start past the right edge and the
        # whole row goes unpainted (measured: the bottom third of a 1080x6000 image).
        row_offset = ((y // step_y) * diag) % step_x
        for x in range(-tile.width + row_offset, base.width + tile.width, step_x):
            overlay.alpha_composite(tile, (x, y))

    return Image.alpha_composite(base, overlay).convert("RGB")


def apply_center(
    image_rgb: Image.Image,
    text: str,
    *,
    alpha: float = config.DEFAULT_VISIBLE_ALPHA,
    font_size: int | None = None,
) -> Image.Image:
    """Stamp a single half-transparent watermark over the central 60% region."""
    base = image_rgb.convert("RGBA")
    w, h = base.size
    target_w = int(w * 0.6)

    # P58: an explicit font_size is the caller's choice (it may overflow); otherwise start
    # from the legacy estimate and shrink only if the measured width does not fit. A falsy
    # value keeps the pre-P58 "0 means auto" behaviour.
    if font_size:
        font = _load_font(font_size)
    else:
        font = _fit_font(text, target_w, max(24, target_w // max(len(text), 1)))

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
        return apply_center(image_rgb, text, alpha=alpha)
    if mode == "subject":
        return apply_subject(image_rgb, text, alpha=alpha)
    raise ValueError(
        f"unknown visible-mode {mode!r}; expected subject|tile|center"
    )


def apply_subject(
    image_rgb: Image.Image,
    text: str,
    *,
    alpha: float = config.DEFAULT_VISIBLE_ALPHA,
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
    # P58: keep the legacy estimate (and its large-image cap) as the starting point, then
    # shrink to the measured width so CJK or long text cannot leave the subject box.
    estimate = min(max(24, target_w // max(len(text), 1)), max(28, h // 6))
    font = _fit_font(text, target_w, estimate)

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
