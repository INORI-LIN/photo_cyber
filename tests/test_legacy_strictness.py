"""P3 — the checksum-less raw path is a clue, never proof.

Spike P3-A (2026-09-23, 335 rows over this repo's own fixtures) measured real products at
``mean_margin`` 0.2567-0.3247 against printable garbage at 0.2005-0.5000 — overlapping
bands, with a corrupted real product sitting at 0.2567 inside the "true" band. No threshold
can separate them, so these tests pin the *structural* rules that do work (strict UTF-8,
zero-tolerance printability, anti-repetition) and the honesty contract (every clue says it
is a clue). The advisory margin gate is deliberately NOT asserted as a discriminator.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from photo_guard import pipeline, watermark_invisible as wi

# 15 bytes: a length the existing round-trip tests already prove this fixture recovers
# exactly (tests/test_pipeline_order.py uses the same length).
PROVEN_PAYLOAD = "owner:test#order"


@pytest.mark.parametrize("raw", [b"\xff\xfe", b"\x80abc", b"\xc3\x28"])
def test_invalid_utf8_is_rejected(raw: bytes) -> None:
    assert wi.is_recoverable_text(raw) is False


def test_a_single_control_character_is_enough() -> None:
    """Zero tolerance replaces the old ">= 50% bad characters" rule.

    ``b"owner\\x00alice"`` is 1 bad character in 11, which the old heuristic accepted and
    then reported with exit code 0.
    """
    assert wi.is_recoverable_text(b"owner\x00alice") is False


@pytest.mark.parametrize(
    "text", ["owner:alice#001", "ci-test", "test#cli", "photo-guard-2026-06-18", "© test"]
)
def test_printable_payloads_pass(text: str) -> None:
    assert wi.is_recoverable_text(text.encode("utf-8")) is True


@pytest.mark.parametrize(
    "raw",
    [b"layers-testlayers-test", b"rurururururu", b"abab", b"aaaaaa", b"PG1:PG1:PG1:PG1:"],
)
def test_repetition_is_rejected(raw: bytes) -> None:
    """The multiple-length false-accept family: reading at m*N yields a printable repeat."""
    assert wi.is_recoverable_text(raw) is False


def test_ordinary_payloads_are_not_mistaken_for_repetition() -> None:
    for text in ("test#cli", "owner:alice#001", "aab"):
        assert wi.is_recoverable_text(text.encode("utf-8")) is True


def test_empty_decode_is_rejected() -> None:
    assert wi.is_recoverable_text(b"") is False


def test_legacy_extraction_recovers_a_real_product(textured_jpg, tmp_path) -> None:
    out = tmp_path / "raw.jpg"
    pipeline.protect(
        textured_jpg,
        out,
        pipeline.ProtectOptions(
            payload=PROVEN_PAYLOAD, visible_mode="tile", visible_text="© t"
        ),
    )
    clue = pipeline.verify_legacy(out, len(PROVEN_PAYLOAD.encode()))
    assert clue.text == PROVEN_PAYLOAD
    assert clue.blocks_per_bit > 0
    assert 0.0 <= clue.mean_margin <= 1.0
    assert isinstance(clue.advisory_pass, bool)


def test_every_clue_states_that_it_is_a_clue(textured_jpg, tmp_path) -> None:
    """The honesty contract: the raw path must never read as a verification result."""
    out = tmp_path / "raw.jpg"
    pipeline.protect(
        textured_jpg,
        out,
        pipeline.ProtectOptions(
            payload=PROVEN_PAYLOAD, visible_mode="tile", visible_text="© t"
        ),
    )
    clue = pipeline.verify_legacy(out, len(PROVEN_PAYLOAD.encode()))
    assert "clue, not proof" in clue.notes


def test_legacy_path_rejects_a_clean_image(tmp_path) -> None:
    clean = tmp_path / "clean.jpg"
    Image.new("RGB", (800, 600), (200, 220, 240)).save(clean, quality=92)
    with pytest.raises(wi.NoPayloadError):
        pipeline.verify_legacy(clean, 10)


def test_zero_payload_bytes_is_a_value_error(tmp_path) -> None:
    """Argument errors stay exit code 2: NoPayloadError is what maps to 1."""
    clean = tmp_path / "clean.jpg"
    Image.new("RGB", (800, 600), (200, 220, 240)).save(clean, quality=92)
    with pytest.raises(ValueError, match="positive") as excinfo:
        pipeline.verify_legacy(clean, 0)
    assert not isinstance(excinfo.value, wi.NoPayloadError)


def test_advisory_constants_exist_and_are_not_proof_thresholds() -> None:
    from photo_guard import config

    assert config.DEFAULT_MAX_PAYLOAD_BYTES == 128
    assert 0.0 < config.LEGACY_MIN_MEAN_MARGIN < 0.5021  # below the statistic's ceiling
    assert config.LEGACY_MIN_BLOCKS_PER_BIT == 16


def test_boundary_margin_is_zero_for_a_constant_image() -> None:
    """A flat image cannot carry information: every block votes the same way."""
    flat = np.full((256, 256, 3), 128, dtype=np.uint8)
    scores = wi._block_scores(flat)
    assert len(set(scores.tolist())) == 1
    # All-zeros means every bit sits at the extreme, i.e. maximal nominal margin.
    assert wi.boundary_margin(scores, 4) == pytest.approx(127.0 / 255.0, abs=1e-9)
