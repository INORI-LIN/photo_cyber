"""Subject-detection three-tier fallback.

We do NOT test Tier 1 (haar face) — synthesising a haar-friendly face is
brittle across OpenCV versions. We do verify detect_faces returns an empty
list for non-face inputs, then exercise the saliency tier on a checkerboard
and the centre tier on a tiny flat image.
"""
from __future__ import annotations

import numpy as np

from photo_guard import subject


def test_detect_faces_returns_empty_on_flat_image(flat_small_image: np.ndarray) -> None:
    assert subject.detect_faces(flat_small_image) == []


def test_detect_faces_returns_empty_on_random_noise() -> None:
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    assert subject.detect_faces(img) == []


def test_saliency_tier_lands_on_high_contrast(checkerboard_bgr: np.ndarray) -> None:
    box = subject.detect_subject(checkerboard_bgr)
    assert box.area > 0
    h, w = checkerboard_bgr.shape[:2]
    assert 0 <= box.x < w and 0 <= box.y < h
    assert box.x + box.w <= w and box.y + box.h <= h


def test_centre_fallback_on_tiny_flat(flat_small_image: np.ndarray) -> None:
    """Sobel on a flat image yields zero magnitude — saliency degenerates,
    detect_subject must still produce a sane box (centre fallback)."""
    box = subject.detect_subject(flat_small_image)
    h, w = flat_small_image.shape[:2]
    # Box must lie inside the image
    assert 0 <= box.x and 0 <= box.y
    assert box.x + box.w <= w
    assert box.y + box.h <= h
    assert box.area > 0


def test_box_helpers() -> None:
    b = subject.Box(10, 20, 100, 50)
    assert b.area == 5000
    assert b.center() == (60, 45)
