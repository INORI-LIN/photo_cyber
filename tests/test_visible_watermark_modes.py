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
