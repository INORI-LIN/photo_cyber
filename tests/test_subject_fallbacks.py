"""Subject-detection three-tier fallback (P9).

We do NOT test Tier 1 (haar face) — synthesising a haar-friendly face is
brittle across OpenCV versions. We do verify detect_faces returns an empty
list for non-face inputs, then exercise the saliency tier on a checkerboard
and the centre tier on a flat image (where the saliency tier *declines* with
``None``) and on a saliency failure.

Coverage note (P9): ``test_centre_fallback_when_saliency_raises`` passes on the
pre-P9 code too (the inline fallback existed) — it is a pin for the extracted
helper, not new coverage. The renamed flat-image case is the one that goes red
on the old code (which returned the meaningless top-left window).
"""
from __future__ import annotations

import cv2
import numpy as np

from photo_guard import subject


def test_detect_faces_returns_empty_on_flat_image(flat_small_image: np.ndarray) -> None:
    assert subject.detect_faces(flat_small_image) == []


def test_detect_faces_returns_empty_on_random_noise() -> None:
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    assert subject.detect_faces(img) == []


def test_saliency_tier_lands_on_high_contrast(checkerboard_bgr: np.ndarray) -> None:
    salient = subject.detect_salient_box(checkerboard_bgr)
    assert salient is not None  # a checkerboard has edge energy everywhere
    box = subject.detect_subject(checkerboard_bgr)
    assert box == salient
    assert box.area > 0
    h, w = checkerboard_bgr.shape[:2]
    assert 0 <= box.x < w and 0 <= box.y < h
    assert box.x + box.w <= w and box.y + box.h <= h


def test_centre_fallback_on_flat_image(
    flat_small_image: np.ndarray, monkeypatch
) -> None:
    """A flat image has zero Sobel magnitude: the saliency tier must decline with
    ``None`` (not the top-left window), and ``detect_subject`` still returns the
    exact centre box."""
    monkeypatch.setattr(subject, "detect_faces", lambda _image: [])

    assert subject.detect_salient_box(flat_small_image) is None
    assert subject.detect_subject(flat_small_image) == subject.Box(13, 13, 38, 38)


def test_centre_fallback_when_saliency_raises(
    flat_small_image: np.ndarray, monkeypatch
) -> None:
    """The centre tier is also reached when the saliency tier itself fails."""
    monkeypatch.setattr(subject, "detect_faces", lambda _image: [])

    def _boom(_image, **_kwargs):
        raise cv2.error("synthetic saliency failure")

    monkeypatch.setattr(subject, "detect_salient_box", _boom)

    assert subject.detect_subject(flat_small_image) == subject.Box(13, 13, 38, 38)


def test_centre_box_is_never_empty() -> None:
    """P9 clamp: a 1x1 image must still yield a >=1px box (pre-P9 inline logic gave
    Box(0, 0, 1, 1); a naive extraction would give Box(0, 0, 0, 0))."""
    assert subject._centre_box(np.zeros((1, 1, 3), dtype=np.uint8)) == subject.Box(0, 0, 1, 1)


def test_box_helpers() -> None:
    b = subject.Box(10, 20, 100, 50)
    assert b.area == 5000
    assert b.center() == (60, 45)
