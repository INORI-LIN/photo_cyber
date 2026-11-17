"""Visible-watermark mode smoke tests.

Each mode must (a) run without raising, (b) preserve image dimensions, and
(c) actually modify pixels — guards against a silent no-op regression.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from photo_guard import config, subject, watermark_visible


@pytest.fixture
def textured_rgb() -> Image.Image:
    rng = np.random.default_rng(1)
    arr = rng.integers(40, 215, (400, 600, 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


def test_font_fallback_is_sized_when_no_ttf_is_available(monkeypatch) -> None:
    """Q2/N3: a system (or the Docker image) without a TTF must not render at ~10 px.

    Pillow >= 10.1 can size its built-in Aileron fallback; the dependency floor is 12.2.
    Only the OS font locations are made to fail: ``load_default(size=...)`` itself loads a
    bundled font through ``truetype``, so a blanket patch would break the fallback too.
    """
    from PIL import ImageFont

    real_truetype = ImageFont.truetype
    os_roots = ("/usr/share/fonts", "/System/Library/Fonts", "/Library/Fonts", "C:\\Windows\\Fonts")

    def _no_os_ttf(path, *args, **kwargs):
        if str(path).startswith(os_roots):
            raise OSError("no OS font")
        return real_truetype(path, *args, **kwargs)

    monkeypatch.setattr(ImageFont, "truetype", _no_os_ttf)
    box = watermark_visible._load_font(36).getbbox("Ag")
    height = box[3] - box[1]
    assert height >= 20, f"fallback rendered at {height}px"


@pytest.mark.parametrize("mode", ["subject", "tile", "center"])
def test_visible_modes_smoke(textured_rgb: Image.Image, mode: str) -> None:
    out = watermark_visible.apply(textured_rgb, "© test", mode=mode, alpha=0.30)
    assert out.size == textured_rgb.size
    assert out.mode == "RGB"

    # Output must differ from the input — otherwise the layer silently no-op'd.
    a = np.array(textured_rgb)
    b = np.array(out)
    assert not np.array_equal(a, b)


def test_unknown_mode_raises(textured_rgb: Image.Image) -> None:
    with pytest.raises(ValueError, match="unknown visible-mode"):
        watermark_visible.apply(textured_rgb, "© test", mode="bogus")


def test_tile_covers_the_bottom_band_of_a_tall_image() -> None:
    """P16: the row offset used to run off-canvas, leaving a tall image's last third blank.

    The offset accumulates ``diag`` per row without wrapping, so once it passed the canvas
    width the x-range went empty: measured 0 changed pixels in the bottom third of a
    1080x6000 image (the top two thirds were painted). 540x3000 still reproduces the empty
    band on the pre-fix loop (probe: bands [9969, 1234, 0]) while the fixed loop paints all
    three (probe: [11567, 11408, 12169]).
    """
    arr = np.full((3000, 540, 3), 128, dtype=np.uint8)
    out = watermark_visible.apply_tile(Image.fromarray(arr, "RGB"), "© test")

    changed = (np.array(out) != arr).any(axis=2)
    third = arr.shape[0] // 3
    bands = [int(changed[i * third : (i + 1) * third].sum()) for i in range(3)]
    assert min(bands) > 0, f"a band was left unpainted: {bands}"


# --- R6/P58: defaults follow config, and long/CJK text must fit its region ----------

LONG_CJK = "版权所有照片水印测试长文本示例二十字符"


def _changed_width(out: Image.Image, base: Image.Image) -> int:
    changed = (np.array(out) != np.array(base)).any(axis=2)
    xs = np.nonzero(changed)[1]
    return int(xs.max() - xs.min() + 1) if len(xs) else 0


def test_center_and_subject_default_alpha_matches_config() -> None:
    """P58: the direct-call defaults were 0.35 while config/AGENTS say 10%."""
    base = Image.new("RGB", (320, 240), (128, 128, 128))
    for function in (watermark_visible.apply_center, watermark_visible.apply_subject):
        default = np.array(function(base, "© test"))
        explicit = np.array(
            function(base, "© test", alpha=config.DEFAULT_VISIBLE_ALPHA)
        )
        assert np.array_equal(default, explicit), function.__name__


def test_long_cjk_text_fits_the_centre_region() -> None:
    """19 CJK characters used to render 291 px wide against a 192 px target."""
    base = Image.new("RGB", (320, 240), (128, 128, 128))

    out = watermark_visible.apply_center(base, LONG_CJK, alpha=0.30)

    assert _changed_width(out, base) <= int(320 * 0.6) + 4


def test_long_cjk_text_fits_the_subject_region() -> None:
    base = Image.new("RGB", (320, 240), (128, 128, 128))
    bgr = np.array(base)[:, :, ::-1].copy()
    box = subject.detect_subject(bgr)
    region_w = max(64, box.w - 2 * int(box.w * 0.05))

    out = watermark_visible.apply_subject(base, LONG_CJK, alpha=0.30)

    assert _changed_width(out, base) <= int(region_w * 0.95) + 4


def test_fit_font_only_shrinks_and_never_enlarges() -> None:
    """P58: the legacy estimate is the ceiling; fit narrows it only when it overflows.

    The targets are derived from the measured legacy width on purpose: glyph metrics
    differ per platform (Linux/Windows fall back to a wider font), so a hard-coded 192
    would assert "this font happens to fit", not the shrink-only rule.
    """
    legacy = watermark_visible._load_font(24)
    latin = "© photo-guard"
    legacy_width = watermark_visible._rendered_width(legacy, latin)

    # A target as wide as the legacy render must leave the size untouched (no enlargement).
    assert (
        watermark_visible._rendered_width(
            watermark_visible._fit_font(latin, legacy_width, 24), latin
        )
        == legacy_width
    )

    # A narrower target must shrink to fit, never grow.
    target = max(1, legacy_width // 2)
    assert watermark_visible._rendered_width(
        watermark_visible._fit_font(latin, target, 24), latin
    ) <= target

    cjk = watermark_visible._fit_font(LONG_CJK, 192, 24)
    assert watermark_visible._rendered_width(cjk, LONG_CJK) <= 192
    assert watermark_visible._rendered_width(cjk, LONG_CJK) < (
        watermark_visible._rendered_width(legacy, LONG_CJK)
    )
