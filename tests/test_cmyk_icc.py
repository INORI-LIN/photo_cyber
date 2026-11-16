"""P48 — CMYK JPEGs and their ICC profiles.

A CMYK JPEG used to go through Pillow's naive ``convert("RGB")`` while the source *CMYK*
ICC profile was copied into the RGB product: the pixels and the profile described different
color spaces. The contract now is:

* CMYK with an ICC profile -> ImageCms transform to sRGB, and the product carries an sRGB
  profile (the source CMYK bytes are never copied);
* CMYK without an ICC profile -> naive conversion, profile dropped, and an actionable
  ``protect`` warning;
* an unreadable ICC profile -> exit 2, no product.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageCms

from photo_guard import pipeline
from photo_guard.cli import main
from tests.support import textured_rgb

SRGB_BYTES = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _cmyk_jpeg(path: Path, *, icc: bytes | None = None, size: tuple[int, int] = (640, 480)) -> Path:
    image = textured_rgb(size, seed=7, low=40, high=210).convert("CMYK")
    kwargs = {"quality": 92}
    if icc is not None:
        kwargs["icc_profile"] = icc
    image.save(path, **kwargs)
    return path


def test_cmyk_without_icc_converts_naively_and_warns(tmp_path, capsys) -> None:
    src = _cmyk_jpeg(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"

    info = pipeline.protect(src, out, pipeline.ProtectOptions())

    assert out.exists()
    assert any("CMYK" in note and "ICC" in note for note in info["warnings"])
    with Image.open(out) as image:
        assert image.mode == "RGB"
        assert not image.info.get("icc_profile")

    out2 = tmp_path / "out2.jpg"
    assert main(["protect", str(src), "-o", str(out2)]) == 0
    err = capsys.readouterr().err
    assert "CMYK" in err and "ICC" in err


def test_cmyk_with_icc_converts_to_srgb_and_writes_srgb_profile(tmp_path, monkeypatch) -> None:
    # A real CMYK profile is not redistributable here; pin the wiring and the output profile.
    source_icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    src = _cmyk_jpeg(tmp_path / "in.jpg", icc=source_icc)
    out = tmp_path / "out.jpg"
    real_profile = ImageCms.ImageCmsProfile

    class _FakeSource:
        def tobytes(self) -> bytes:
            return source_icc

    def fake_profile(argument):
        if isinstance(argument, io.BytesIO):
            return _FakeSource()
        return real_profile(argument)

    calls: list[str | None] = []

    def fake_convert(image, source, target, outputMode=None):
        calls.append(outputMode)
        return image.convert("RGB")

    monkeypatch.setattr(ImageCms, "ImageCmsProfile", fake_profile)
    monkeypatch.setattr(ImageCms, "profileToProfile", fake_convert)

    info = pipeline.protect(src, out, pipeline.ProtectOptions())

    assert out.exists()
    assert calls == ["RGB"]
    assert info["warnings"] == []
    with Image.open(out) as image:
        assert image.mode == "RGB"
        embedded = image.info.get("icc_profile")
    assert embedded
    assert embedded != source_icc
    assert real_profile(io.BytesIO(embedded)).profile.xcolor_space.strip() == "RGB"


def test_cmyk_with_unreadable_icc_is_refused(tmp_path, capsys) -> None:
    src = _cmyk_jpeg(tmp_path / "in.jpg", icc=b"not a profile")
    out = tmp_path / "out.jpg"

    with pytest.raises(ValueError, match="CMYK ICC"):
        pipeline.protect(src, out, pipeline.ProtectOptions())
    assert not out.exists()

    assert main(["protect", str(src), "-o", str(out)]) == 2
    assert "CMYK ICC" in capsys.readouterr().err
    assert not out.exists()


def test_cmyk_without_icc_png_output_has_no_profile(tmp_path) -> None:
    src = _cmyk_jpeg(tmp_path / "in.jpg")
    out = tmp_path / "out.png"

    pipeline.protect(
        src, out, pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_INVISIBLE}))
    )

    with Image.open(out) as image:
        assert image.mode == "RGB"
        assert not image.info.get("icc_profile")


def test_rgb_icc_is_still_passed_through(tmp_path) -> None:
    src = tmp_path / "in.jpg"
    textured_rgb((320, 320), seed=3).save(src, quality=92, icc_profile=SRGB_BYTES)
    out = tmp_path / "out.jpg"

    pipeline.protect(
        src, out, pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_VISIBLE}))
    )

    with Image.open(out) as image:
        assert image.info.get("icc_profile") == SRGB_BYTES
