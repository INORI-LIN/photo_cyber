"""P4 — the write-side capacity gate: floor first, then the structural ceiling.

The read side has had capacity guards since P14/P27; this file pins the numbers the write
side must agree with. The ceiling is deliberately NOT a reliability threshold: the 448-cell
measurement (docs/fix-plan.md §6 P4 / §10.14) showed every possible ``blocks/bit`` threshold
rejects legal products (25.7% at bpb≥16, non-monotone), so the write side only refuses what
cannot possibly fit and leaves reliability to the product self-check.
"""
from __future__ import annotations

import numpy as np
import pytest

from photo_guard import pipeline, watermark_invisible


def test_max_stored_bytes_matches_block_arithmetic() -> None:
    # Equivalence pin for the P3 function the write side now consumes (values also pinned by
    # tests/test_watermark_discovery.py): one byte per 8 blocks, 8x8 blocks.
    assert watermark_invisible.max_stored_bytes(320, 320) == 200
    assert watermark_invisible.max_stored_bytes(1080, 810) == 1704
    assert watermark_invisible.max_stored_bytes(256, 256) == 128


def test_validate_capacity_boundaries() -> None:
    height, width = 1080, 810
    limit = watermark_invisible.max_stored_bytes(height, width)

    pipeline.validate_capacity(limit, height, width)  # exactly at the ceiling passes

    with pytest.raises(ValueError, match="can carry at most") as excinfo:
        pipeline.validate_capacity(limit + 1, height, width)
    assert str(limit) in str(excinfo.value)


def test_validate_capacity_floor_message_carries_both_strings() -> None:
    """The floor message must satisfy the historic `too small` pin AND state 65536."""
    with pytest.raises(ValueError) as excinfo:
        pipeline.validate_capacity(1, 200, 200)

    message = str(excinfo.value)
    assert "too small" in message
    assert "65536" in message


def test_validate_capacity_accepts_the_floor_itself(tmp_path) -> None:
    # 256x256 is the library floor: capacity 128 bytes, and the smallest payload fits.
    pipeline.validate_capacity(1, 256, 256)

    image = np.random.default_rng(3).integers(40, 210, (256, 256, 3), dtype=np.uint8)
    stored = "photo-guard"
    recovered = watermark_invisible.extract(
        watermark_invisible.embed(image, stored), len(stored.encode("utf-8"))
    )
    assert recovered == stored
