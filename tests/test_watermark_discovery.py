"""P3 — blind discovery of the CRC envelope, and the rebuilt decoder underneath it.

The block scan in ``watermark_invisible`` is a transcription of ``imwatermark.dwtDctSvd``.
These tests pin it against the library's own decoder, so an "optimisation" that silently
diverges fails loudly instead of returning a wrong payload. Equivalence was proven for
4 images x n = 1..66 in spike P3-B; the fast tier keeps one 256x256 image (the library's
floor) and the full n range, which is what actually catches a mapping slip.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest
from imwatermark import WatermarkDecoder, WatermarkEncoder
from PIL import Image

from photo_guard import pipeline, watermark_invisible as wi

MIN_SIDE = 256  # the library refuses r*c < 256*256


@pytest.fixture(scope="module")
def probe_bgr() -> np.ndarray:
    """256x256 textured BGR: at the library's floor and cheap enough for 66 round trips."""
    rng = np.random.default_rng(42)
    arr = rng.integers(60, 200, (MIN_SIDE, MIN_SIDE, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:MIN_SIDE, 0:MIN_SIDE]
    arr[..., 0] = np.clip(arr[..., 0].astype(int) + (xx // 8), 0, 255).astype(np.uint8)
    arr[..., 1] = np.clip(arr[..., 1].astype(int) + (yy // 8), 0, 255).astype(np.uint8)
    return arr[:, :, ::-1].copy()


# The legacy carrier and the P10 carrier. The transcription is carrier-parameterised, so
# both are pinned: a (channel, scale) mismatch scrambles the reading rather than degrading it.
CARRIERS = ((1, 36), (0, 72))


def _embed(bgr: np.ndarray, payload: bytes, carrier: tuple[int, int] = (1, 36)) -> np.ndarray:
    encoder = WatermarkEncoder()
    encoder.set_watermark("bytes", payload)
    return encoder.encode(bgr, "dwtDctSvd", scales=wi._scales_for(*carrier))


@pytest.mark.parametrize("carrier", CARRIERS)
def test_reconstruction_is_byte_exact_for_every_length(
    probe_bgr: np.ndarray, carrier: tuple[int, int]
) -> None:
    """n = 1..66 must equal ``WatermarkDecoder`` byte for byte (spike P3-B), per carrier."""
    channel, scale = carrier
    mismatches = []
    for nbytes in range(1, 67):
        payload = bytes(((i * 37 + 16) % 256) for i in range(nbytes))
        marked = _embed(probe_bgr, payload, carrier=carrier)
        library = bytes(
            WatermarkDecoder("bytes", nbytes * 8).decode(
                marked, "dwtDctSvd", scales=wi._scales_for(channel, scale)
            )
        )
        mine = bytes(
            wi._reconstruct_bytes(
                wi._block_scores(marked, channel=channel, scale=scale), nbytes
            )
        )
        if mine != library:
            mismatches.append((nbytes, library.hex(), mine.hex()))
    assert not mismatches, (
        f"reconstruction diverged from the library on carrier {carrier}: {mismatches}"
    )


def test_block_geometry_and_capacity() -> None:
    assert wi.total_blocks(1200, 1600) == 30000
    assert wi.max_stored_bytes(1200, 1600) == 3750
    # The pipeline's default long edge, and the smallest image the library accepts.
    assert wi.max_stored_bytes(1080, 810) == 1704
    assert wi.max_stored_bytes(256, 256) == 128


def test_envelope_lengths_are_the_13_plus_4k_ladder() -> None:
    lengths = wi.envelope_lengths(64)
    assert lengths[:3] == [17, 21, 25]
    assert all(length % 4 == 1 for length in lengths)
    assert lengths[-1] <= 64


def test_discover_finds_the_envelope_without_the_length(textured_jpg, tmp_path) -> None:
    """The P0 capability: notarise, forget the payload length, still recover it."""
    out = tmp_path / "enveloped.jpg"
    payload = "owner:alice#001"
    pipeline.protect(
        textured_jpg,
        out,
        pipeline.ProtectOptions(
            payload=payload, visible_mode="tile", visible_text="© t", payload_envelope=True
        ),
    )
    assert pipeline.discover_payload(out) == payload


def test_discover_rejects_an_unmarked_image(tmp_path) -> None:
    clean = tmp_path / "clean.jpg"
    Image.new("RGB", (800, 600), (200, 220, 240)).save(clean, quality=92)
    with pytest.raises(wi.NoPayloadError):
        pipeline.discover_payload(clean)


def test_discover_does_not_invent_an_envelope_for_a_raw_payload(textured_jpg, tmp_path) -> None:
    """A checksum-less payload carries no envelope, so blind discovery must find nothing."""
    out = tmp_path / "raw.jpg"
    pipeline.protect(
        textured_jpg,
        out,
        pipeline.ProtectOptions(payload="test#cli", visible_mode="tile", visible_text="© t"),
    )
    with pytest.raises(wi.NoPayloadError):
        pipeline.discover_payload(out)


def test_extract_envelope_needs_an_envelope(probe_bgr: np.ndarray) -> None:
    with pytest.raises(wi.NoPayloadError):
        wi.extract_envelope(probe_bgr, 17)


def test_crc_failure_at_the_right_length_is_uncertain_not_a_mismatch(
    probe_bgr: np.ndarray, monkeypatch
) -> None:
    """P10: chroma clipping can flip bits at the correct length, so a CRC failure must be
    reported as *uncertain* rather than as a plain mismatch."""
    stored = "PG1:deadbeef:" + base64.urlsafe_b64encode(b"owner:alice").decode("ascii")
    monkeypatch.setattr(
        wi, "_reconstruct_bytes", lambda scores, nbytes: stored.encode("ascii")
    )
    with pytest.raises(wi.IntegrityUncertainError, match="CRC32 failed"):
        wi.extract_envelope(probe_bgr, len(stored))


def test_find_envelope_honours_a_zero_ceiling(probe_bgr: np.ndarray) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        wi.find_envelope(probe_bgr, 0)


def test_find_envelope_returns_none_when_capacity_is_below_an_envelope() -> None:
    tiny = np.zeros((256, 256, 3), dtype=np.uint8)
    # 128 stored bytes is the 256x256 ceiling, so a ceiling of 16 admits no envelope.
    assert wi.find_envelope(tiny, 16) is None
