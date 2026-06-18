"""End-to-end pipeline regression — pins the resize-before-embed ordering.

If someone "fixes" pipeline.py to move resize after embed (matching AGENTS.md
§2 literally), DWT-DCT-SVD breaks under resampling and the round-trip fails.
"""
from __future__ import annotations

from photo_guard import pipeline


def test_protect_then_verify_round_trip(textured_jpg, tmp_path) -> None:
    out_path = tmp_path / "out.jpg"
    payload = "owner:test#order"
    info = pipeline.protect(
        textured_jpg,
        out_path,
        pipeline.ProtectOptions(
            payload=payload,
            perturber="noop",
            visible_mode="tile",
            visible_text="© test",
            long_edge=1080,
            quality=85,
        ),
    )
    assert out_path.exists()
    assert max(info["size"]) == 1080
    assert info["payload_bytes"] == len(payload.encode())

    recovered = pipeline.verify(out_path, len(payload.encode()))
    assert recovered == payload


def test_protect_with_noise_perturber_still_round_trips(textured_jpg, tmp_path) -> None:
    """Noise perturber adds ε≈2/255 — must not bury the watermark."""
    out_path = tmp_path / "out.jpg"
    payload = "owner:test#noise"
    pipeline.protect(
        textured_jpg,
        out_path,
        pipeline.ProtectOptions(
            payload=payload,
            perturber="noise",
            visible_mode="subject",
            visible_text="© test",
            long_edge=1080,
            quality=85,
        ),
    )
    recovered = pipeline.verify(out_path, len(payload.encode()))
    assert recovered == payload
