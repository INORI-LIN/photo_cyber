"""P7 — the output container follows the destination extension.

Rules: ``.jpg``/``.jpeg``/no extension → JPEG; ``.png`` → PNG; anything else
(including a trailing dot or trailing space) is rejected before the input is
read.  PNG output ignores ``--quality``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photo_guard import outputs, pipeline


def test_save_format_maps_known_extensions() -> None:
    assert pipeline.save_format(Path("out.jpg")) == "JPEG"
    assert pipeline.save_format(Path("out.JPG")) == "JPEG"
    assert pipeline.save_format(Path("out.jpeg")) == "JPEG"
    assert pipeline.save_format(Path("out.png")) == "PNG"
    assert pipeline.save_format(Path("out.PNG")) == "PNG"
    assert pipeline.save_format(Path("out")) == "JPEG"
    assert pipeline.save_format(Path("out_v2")) == "JPEG"


@pytest.mark.parametrize("name", ["out.bmp", "out.", "out.jpg "])
def test_save_format_rejects_unknown_extension(name: str) -> None:
    with pytest.raises(ValueError, match="unsupported output extension"):
        pipeline.save_format(Path(name))


def test_protect_rejects_bad_extension_before_reading_input(monkeypatch, tmp_path) -> None:
    source = tmp_path / "in.jpg"
    source.write_bytes(b"not decoded")
    monkeypatch.setattr(
        pipeline.Image, "open", lambda *a, **k: pytest.fail("must reject before the loader")
    )

    with pytest.raises(ValueError, match="unsupported output extension"):
        pipeline.protect(
            source, tmp_path / "out.bmp", pipeline.ProtectOptions()
        )


def test_png_output_is_png_and_round_trips(textured_jpg: Path, tmp_path) -> None:
    destination = tmp_path / "out.png"
    payload = "test#png"

    info = pipeline.protect(
        textured_jpg,
        destination,
        pipeline.ProtectOptions(payload=payload, payload_envelope=True),
    )

    assert info["output"] == str(destination)
    with Image.open(destination) as image:
        image.load()
        assert image.format == "PNG"
    assert pipeline.discover_payload(destination) == payload


def test_png_gets_no_quality_but_jpeg_gets_configured_quality(
    monkeypatch, textured_jpg: Path, tmp_path
) -> None:
    calls: list[dict] = []

    def fake_save(image, path, **kwargs):
        calls.append({"path": Path(path), **kwargs})

    monkeypatch.setattr(outputs, "save_image_atomic", fake_save)

    pipeline.protect(
        textured_jpg,
        tmp_path / "out.png",
        pipeline.ProtectOptions(payload="test#png", quality=91),
    )
    pipeline.protect(
        textured_jpg,
        tmp_path / "out.jpg",
        pipeline.ProtectOptions(payload="test#jpg", quality=91),
    )

    png, jpg = calls
    assert png["image_format"] == "PNG" and png["quality"] is None
    assert jpg["image_format"] == "JPEG" and jpg["quality"] == 91
