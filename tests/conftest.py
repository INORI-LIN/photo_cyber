"""Shared fixtures.

Texture parameters are picked to match what the manual end-to-end runs proved
robust: a 1600×1200 noisy gradient survives `dwtDctSvd` embed → JPEG q=85 →
visible WM → JPEG q=85 round-trip and still decodes the payload exactly.

Avoid Random.seed-by-clock — fixed seeds keep tests deterministic across CI.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def textured_jpg(tmp_path: Path) -> Path:
    """1600×1200 textured JPG that survives the full pipeline round-trip."""
    rng = np.random.default_rng(42)
    base = rng.integers(60, 200, (1200, 1600, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:1200, 0:1600]
    base[..., 0] = np.clip(base[..., 0].astype(int) + (xx // 8), 0, 255).astype(np.uint8)
    base[..., 1] = np.clip(base[..., 1].astype(int) + (yy // 8), 0, 255).astype(np.uint8)
    out = tmp_path / "textured.jpg"
    Image.fromarray(base, "RGB").save(out, quality=92)
    return out


@pytest.fixture
def flat_small_image() -> np.ndarray:
    """64×64 flat grey BGR — Sobel returns near-zero, used to drive Tier-3 fallback."""
    return np.full((64, 64, 3), 128, dtype=np.uint8)


@pytest.fixture
def checkerboard_bgr() -> np.ndarray:
    """High-contrast checkerboard — guaranteed to drive the saliency tier."""
    img = np.full((300, 400, 3), 50, dtype=np.uint8)
    for i in range(0, 400, 40):
        for j in range(0, 300, 40):
            if (i // 40 + j // 40) % 2 == 0:
                img[j:j + 40, i:i + 40] = 220
    return img
