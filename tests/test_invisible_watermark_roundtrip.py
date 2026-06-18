"""Invisible-watermark round-trip — the load-bearing test.

Two cases. The second is the regression that pins down `dwtDctSvd` (vs plain
`dwtDct`): if someone changes config.WATERMARK_METHOD back to "dwtDct", the
JPEG q=85 round-trip breaks immediately and this test goes red.
"""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from photo_guard import compress, watermark_invisible, watermark_visible


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))[:, :, ::-1].copy()


def _bgr_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr[:, :, ::-1].copy(), mode="RGB")


def _open_textured_bgr(path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    img = compress.fit_long_edge(img, 1080)
    return _pil_to_bgr(img)


@pytest.mark.parametrize(
    "payload",
    ["abcdef", "owner:test#001", "photo-guard-2026-06-18"],
)
def test_embed_extract_no_compression(textured_jpg, payload: str) -> None:
    bgr = _open_textured_bgr(textured_jpg)
    embedded = watermark_invisible.embed(bgr, payload)
    recovered = watermark_invisible.extract(embedded, len(payload.encode()))
    assert recovered == payload


def test_embed_survives_jpeg85_and_visible_watermark(textured_jpg) -> None:
    """Regression for the dwtDctSvd choice: must survive JPEG q=85 + tile WM + JPEG q=85."""
    payload = "owner:test#001"
    bgr = _open_textured_bgr(textured_jpg)
    embedded = watermark_invisible.embed(bgr, payload)

    # First JPEG round trip
    pil = _bgr_to_pil(embedded)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85, optimize=True)
    buf.seek(0)
    pil = Image.open(buf)
    pil.load()

    # Visible watermark + second JPEG round trip
    visible = watermark_visible.apply_tile(pil, "© test", alpha=0.10)
    buf2 = io.BytesIO()
    visible.save(buf2, format="JPEG", quality=85, optimize=True)
    buf2.seek(0)
    final = _pil_to_bgr(Image.open(buf2))

    recovered = watermark_invisible.extract(final, len(payload.encode()))
    assert recovered == payload, (
        "invisible watermark did not survive JPEG q=85 + visible WM. "
        "Check config.WATERMARK_METHOD — must be 'dwtDctSvd', not 'dwtDct'."
    )
