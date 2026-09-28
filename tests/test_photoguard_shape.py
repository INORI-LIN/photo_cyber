"""P17 — pin the *real* padding contract instead of restating its arithmetic.

The previous version recomputed ``height + (-height) % 8`` inside the test and never called
the attack code, so it could not fail when the implementation changed. It now calls the
shipped helper. ``photoguard`` keeps torch/diffusers lazy, so this file stays in the fast
tier and needs no importorskip.
"""
from __future__ import annotations

import numpy as np
import pytest

from photo_guard import photoguard


@pytest.mark.parametrize(
    ("height", "width"), [(8, 8), (9, 7), (240, 320), (1, 1), (13, 130)]
)
def test_padding_rounds_up_to_a_multiple_of_eight(height: int, width: int) -> None:
    rgb = np.random.default_rng(11).random((height, width, 3), dtype=np.float32)

    padded = photoguard.pad_to_multiple_of_8(rgb)

    assert padded.shape[:2] == (((height + 7) // 8) * 8, ((width + 7) // 8) * 8)
    assert padded.shape[0] % 8 == 0 and padded.shape[1] % 8 == 0
    # The attack crops back with [:h, :w] after the VAE round trip, so the padding must
    # leave the original region untouched.
    assert np.array_equal(padded[:height, :width], rgb)


def test_padding_repeats_the_edge_pixel() -> None:
    rgb = np.zeros((9, 9, 3), dtype=np.float32)
    rgb[8, :, :] = 1.0
    rgb[:, 8, :] = 2.0  # (8, 8) ends up 2.0: the column wins

    padded = photoguard.pad_to_multiple_of_8(rgb)

    assert np.all(padded[9:, :8] == 1.0)  # added rows copy the last row
    assert np.all(padded[:, 9:] == 2.0)  # added columns copy the last column
