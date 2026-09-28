"""Visible-watermark mode smoke tests.

Each mode must (a) run without raising, (b) preserve image dimensions, and
(c) actually modify pixels — guards against a silent no-op regression.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from photo_guard import watermark_visible


@pytest.fixture
def textured_rgb() -> Image.Image:
    rng = np.random.default_rng(1)
    arr = rng.integers(40, 215, (400, 600, 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


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
    1080x6000 image (the top two thirds were painted).
    """
    arr = np.full((6000, 1080, 3), 128, dtype=np.uint8)
    out = watermark_visible.apply_tile(Image.fromarray(arr, "RGB"), "© test")

    changed = (np.array(out) != arr).any(axis=2)
    third = arr.shape[0] // 3
    bands = [int(changed[i * third : (i + 1) * third].sum()) for i in range(3)]
    assert min(bands) > 0, f"a band was left unpainted: {bands}"
