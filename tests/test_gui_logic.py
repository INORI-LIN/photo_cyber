from __future__ import annotations

from pathlib import Path

from photo_guard import pipeline


def test_gui_defaults_are_safe() -> None:
    options = pipeline.ProtectOptions(payload_envelope=True)
    assert options.layers == frozenset({"invisible", "visible"})
    assert "perturb" not in options.layers
    pipeline.validate_options(options)


def test_unique_output_policy(tmp_path: Path) -> None:
    first = tmp_path / "image_protected.jpg"
    first.write_bytes(b"x")
    candidate = first
    number = 2
    while candidate.exists():
        candidate = tmp_path / f"image_protected_{number}.jpg"
        number += 1
    assert candidate.name == "image_protected_2.jpg"
