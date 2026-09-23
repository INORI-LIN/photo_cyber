"""P10 / P11 — the carrier move and the detail-band swap fix.

P10: every JPEG 4:2:0 re-encode decimates chroma, which wiped the block votes of the old
chroma carrier (31/66 and 17/66 round trips over payload lengths 1..66). The carrier now
rides luma at step 72, and the read path tries the legacy carrier too so released images
stay readable.

P11: ``imwatermark`` hands ``idwt2`` the detail bands in the wrong order, injecting an
unintended distortion that scales with how much detail the image has. Measured on a noisy
image at the new luma carrier: mean |d| 17.09 / PSNR 19.37 dB unfixed versus 2.82 / 37.42 dB
fixed.
"""
from __future__ import annotations

import numpy as np
import pytest
from imwatermark import WatermarkDecoder, WatermarkEncoder
from PIL import Image

from photo_guard import config, pipeline, watermark_invisible as wi

LEGACY = (1, 36)
CURRENT = (config.CARRIER_CHANNEL, config.CARRIER_SCALE)
PAYLOAD = "owner:alice#001"


def _detailed(size: int = 256) -> np.ndarray:
    """Independent per-pixel noise: maximum detail, the worst case for the swap bug."""
    rng = np.random.default_rng(42)
    return rng.integers(60, 200, (size, size, 3), dtype=np.uint8)


def _library_embed(bgr: np.ndarray, payload: bytes, carrier: tuple[int, int]) -> np.ndarray:
    encoder = WatermarkEncoder()
    encoder.set_watermark("bytes", payload)
    return encoder.encode(bgr, "dwtDctSvd", scales=wi._scales_for(*carrier))


def test_the_carrier_is_luma_at_step_72() -> None:
    assert CURRENT == (0, 72)
    # Current first, then legacy: the order is the read policy, so it is pinned.
    assert wi.carrier_candidates()[0] == CURRENT
    assert LEGACY in wi.carrier_candidates()


def test_embed_round_trips_through_the_configured_carrier() -> None:
    bgr = _detailed()
    marked = wi.embed(bgr, PAYLOAD)
    assert wi.extract(marked, len(PAYLOAD.encode())) == PAYLOAD


def test_swap_fix_reduces_distortion_on_detailed_content() -> None:
    """The library's H/V swap costs an 18 dB PSNR drop on detailed content; ours does not."""
    bgr = _detailed()
    unfixed = _library_embed(bgr, PAYLOAD.encode(), CURRENT)
    fixed = wi.embed(bgr, PAYLOAD)

    d_unfixed = np.abs(unfixed.astype(int) - bgr.astype(int))
    d_fixed = np.abs(fixed.astype(int) - bgr.astype(int))
    assert d_fixed.mean() * 3 < d_unfixed.mean(), (d_fixed.mean(), d_unfixed.mean())
    assert d_unfixed.max() > 100 and d_fixed.max() <= 48


def test_swap_fix_keeps_images_mutually_readable() -> None:
    """cA is untouched by the fix, so old code can read new images and vice versa."""
    bgr = _detailed()
    unfixed = _library_embed(bgr, PAYLOAD.encode(), CURRENT)
    fixed = wi.embed(bgr, PAYLOAD)

    assert wi.extract(unfixed, len(PAYLOAD.encode())) == PAYLOAD
    assert wi.extract(fixed, len(PAYLOAD.encode())) == PAYLOAD
    for image in (unfixed, fixed):
        decoded = WatermarkDecoder("bytes", len(PAYLOAD.encode()) * 8).decode(
            image, "dwtDctSvd", scales=wi._scales_for(*CURRENT)
        )
        assert decoded.decode("utf-8") == PAYLOAD


# A "released" image: 1080x810 and a short payload. Both matter. At 256x256 the legacy
# chroma carrier loses a 14-byte payload to a 4:2:0 JPEG round trip (9 blocks per bit), which
# is the very defect P10 fixes; at 1080x810 the same carrier has ~213 blocks per bit and is
# comfortably reliable. Tests must sit in the reliable regime or they measure the defect
# instead of the read path.
RELEASED_PAYLOAD = "ci-test1"


@pytest.fixture(scope="module")
def released_image_legacy(tmp_path_factory) -> Path:
    """An image embedded the old way, saved as a finished JPEG."""
    rng = np.random.default_rng(7)
    bgr = rng.integers(60, 200, (810, 1080, 3), dtype=np.uint8)
    stored = wi.pack_payload(RELEASED_PAYLOAD)
    marked = _library_embed(bgr, stored.encode("utf-8"), LEGACY)
    path = tmp_path_factory.mktemp("carrier") / "released.jpg"
    Image.fromarray(marked[:, :, ::-1], "RGB").save(path, quality=85)
    return path


def test_envelope_on_a_legacy_carrier_still_verifies(released_image_legacy) -> None:
    """An image released before the carrier moved must keep working — that is the whole
    point of the candidate read path."""
    assert pipeline.discover_payload(released_image_legacy) == RELEASED_PAYLOAD
    assert (
        pipeline.verify_expected(released_image_legacy, RELEASED_PAYLOAD)["verified"] is True
    )


def test_envelope_on_the_current_carrier_verifies(tmp_path) -> None:
    stored = wi.pack_payload(PAYLOAD)
    marked = wi.embed(_detailed(), stored)
    current = tmp_path / "current.jpg"
    Image.fromarray(marked[:, :, ::-1], "RGB").save(current, quality=85)

    assert pipeline.discover_payload(current) == PAYLOAD
    assert pipeline.verify_expected(current, PAYLOAD)["verified"] is True


def test_legacy_extraction_reports_which_carrier_matched(tmp_path) -> None:
    """A checksum-less clue cannot confirm the carrier, so it must report the one it used."""
    marked = wi.embed(_detailed(), PAYLOAD)
    path = tmp_path / "clue.jpg"
    Image.fromarray(marked[:, :, ::-1], "RGB").save(path, quality=85)

    clue = pipeline.verify_legacy(path, len(PAYLOAD.encode()))
    assert clue.text == PAYLOAD
    assert clue.carrier == CURRENT
    assert "clue, not proof" in clue.notes


@pytest.fixture(scope="module")
def legacy_raw_image(tmp_path_factory) -> Path:
    """An old-style image carrying a *bare* payload (no CRC envelope).

    A separate image from ``released_image_legacy`` on purpose: that one carries the envelope
    string, so decoding it at the raw payload length is meaningless by construction.
    """
    rng = np.random.default_rng(11)
    bgr = rng.integers(60, 200, (810, 1080, 3), dtype=np.uint8)
    marked = _library_embed(bgr, RELEASED_PAYLOAD.encode("utf-8"), LEGACY)
    path = tmp_path_factory.mktemp("carrier-raw") / "old_raw.jpg"
    Image.fromarray(marked[:, :, ::-1], "RGB").save(path, quality=85)
    return path


def test_a_legacy_carrier_clue_is_also_reported_truthfully(legacy_raw_image) -> None:
    """The candidate loop must reach the legacy carrier and say so, not just the current one."""
    clue = pipeline.verify_legacy(legacy_raw_image, len(RELEASED_PAYLOAD.encode()))
    assert clue.text == RELEASED_PAYLOAD
    assert clue.carrier == LEGACY


def test_embed_keeps_the_library_size_floor() -> None:
    """The library refuses r*c < 256*256; our own embed must keep that guarantee."""
    with pytest.raises(RuntimeError, match="too small"):
        wi.embed(np.zeros((200, 300, 3), dtype=np.uint8), PAYLOAD)
