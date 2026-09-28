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

from photo_guard import config, pipeline, watermark_invisible as wi

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


def test_an_impossible_length_is_rejected_before_any_extraction(monkeypatch) -> None:
    """P14: a length beyond the image's capacity is an argument error, not a slow clue hunt.

    The spy proves the rejection happens *before* the block loop: the old code entered it
    (and spun for ``payload_bytes * 8`` iterations) even when success was impossible.
    """
    flat = np.full((256, 256, 3), 128, dtype=np.uint8)
    capacity = wi.max_stored_bytes(256, 256)
    calls: list[str] = []
    monkeypatch.setattr(wi, "_block_scores", lambda *a, **k: calls.append("scores"))

    with pytest.raises(ValueError, match="capacity") as excinfo:
        wi.extract_legacy(flat, capacity + 1)
    assert calls == []
    assert not isinstance(excinfo.value, wi.NoPayloadError)
    assert str(capacity + 1) in str(excinfo.value)
    assert str(capacity) in str(excinfo.value)


def test_the_capacity_boundary_itself_is_not_a_parameter_error() -> None:
    """The guard is ``>``, not ``>=``: a full-capacity request still runs and reports a clue."""
    flat = np.full((256, 256, 3), 128, dtype=np.uint8)
    capacity = wi.max_stored_bytes(256, 256)
    with pytest.raises(wi.NoPayloadError):
        wi.extract_legacy(flat, capacity)


@pytest.mark.parametrize("decode", [wi.extract, wi.extract_legacy])
def test_both_raw_entry_points_reject_an_impossible_length(decode) -> None:
    flat = np.full((256, 256, 3), 128, dtype=np.uint8)
    capacity = wi.max_stored_bytes(256, 256)
    with pytest.raises(ValueError, match="capacity"):
        decode(flat, capacity + 1)


def test_advisory_gate_is_decided_by_blocks_per_bit_at_the_floor(tmp_path) -> None:
    """P17 — the old version asserted ``LEGACY_MIN_BLOCKS_PER_BIT == 16`` against itself.

    This pins the *behaviour* the constant buys, at the 320x320 embedding floor: a 12-byte
    payload gets 16 blocks/bit and passes the gate; a 14-byte payload gets 14 and fails it —
    while the margin gate is satisfied in both cases, so blocks/bit is what decides.
    Flip the constant to 1 and the failing assertions go red.
    """
    source = tmp_path / "floor.jpg"
    rng = np.random.default_rng(7)
    Image.fromarray(rng.integers(40, 215, (320, 320, 3), dtype=np.uint8)).save(source, quality=92)

    def clue_for(payload: str) -> wi.LegacyExtraction:
        out = tmp_path / f"floor_{len(payload)}.jpg"
        pipeline.protect(
            source,
            out,
            pipeline.ProtectOptions(payload=payload, visible_mode="tile", visible_text="© t"),
        )
        return pipeline.verify_legacy(out, len(payload))

    passing = clue_for("owner:alice#"[:12])  # 12 bytes -> 16 blocks/bit
    failing = clue_for("owner:alice#01")  # 14 bytes -> 14 blocks/bit

    assert passing.text == "owner:alice#"
    assert failing.text == "owner:alice#01"
    for clue in (passing, failing):
        assert clue.mean_margin >= config.LEGACY_MIN_MEAN_MARGIN  # the other gate passes
        assert clue.advisory_pass is (clue.blocks_per_bit >= config.LEGACY_MIN_BLOCKS_PER_BIT)
    assert passing.blocks_per_bit >= config.LEGACY_MIN_BLOCKS_PER_BIT
    assert failing.blocks_per_bit < config.LEGACY_MIN_BLOCKS_PER_BIT
    assert f"{failing.blocks_per_bit} blocks/bit" in failing.notes


def test_mean_margin_gate_sits_below_the_statistic_ceiling() -> None:
    # The margin statistic cannot exceed ~0.5020 (spike P3-A), so a gate at or above that
    # would be unsatisfiable; this is a sanity bound, not a restatement of the value.
    assert 0.0 < config.LEGACY_MIN_MEAN_MARGIN < 0.5021


def test_boundary_margin_is_zero_for_a_constant_image() -> None:
    """A flat image cannot carry information: every block votes the same way."""
    flat = np.full((256, 256, 3), 128, dtype=np.uint8)
    scores = wi._block_scores(flat)
    assert len(set(scores.tolist())) == 1
    # All-zeros means every bit sits at the extreme, i.e. maximal nominal margin.
    assert wi.boundary_margin(scores, 4) == pytest.approx(127.0 / 255.0, abs=1e-9)
