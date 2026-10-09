"""P8 — orientation must be applied at decode, EXIF stripped, ICC preserved.

Pre-fix ``protect``/``verify`` read the stored pixel matrix (``convert("RGB")``) and never
looked at EXIF: a phone photo tagged ``Orientation=6`` came out sideways, the EXIF was
dropped silently, and the ICC profile never reached the output. The single loader
``pipeline._load_oriented_rgb`` fixes all three at once.

The corrupt-EXIF cases reproduce the spike's ``jfif_unit=0/1`` observation as an injected
unparseable APP1 segment: Pillow swallows the ``SyntaxError`` while opening (JpegImagePlugin
falls back to an empty Exif), so only a fresh ``Image.Exif().load(...)`` re-parse can see it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageOps

from photo_guard import pipeline
from photo_guard.cli import main

ORIENTATION_TAG = 0x0112
# Synthetic ICC blob: the pass-through contract is byte equality, and Pillow embeds the
# bytes verbatim (a real lcms profile would make the test depend on ImageCms availability).
ICC_BYTES = b"PG-TEST-ICC\x00" + bytes(range(64))


def _textured(size: tuple[int, int], *, seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(40, 210, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


def _app1(orientation: int) -> bytes:
    """A minimal, valid EXIF APP1 segment carrying only the orientation tag."""
    body = b"II*\x00" + (8).to_bytes(4, "little")
    body += (1).to_bytes(2, "little")
    body += (ORIENTATION_TAG).to_bytes(2, "little")
    body += (3).to_bytes(2, "little") + (1).to_bytes(4, "little")
    body += orientation.to_bytes(2, "little") + b"\x00" * 2
    body += (0).to_bytes(4, "little")
    payload = b"Exif\x00\x00" + body
    return b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload


def _tagged_jpeg(source: Path, target: Path, orientation: int) -> None:
    """Byte-insert the APP1 orientation segment so the pixels stay untouched."""
    data = source.read_bytes()
    assert data[:2] == b"\xff\xd8"
    target.write_bytes(data[:2] + _app1(orientation) + data[2:])


def _corrupt_exif_jpeg(source: Path, target: Path) -> None:
    """Byte-insert an APP1 whose TIFF body cannot be parsed (synthetic corrupt EXIF)."""
    payload = b"Exif\x00\x00" + b"not a tiff at all"
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    data = source.read_bytes()
    target.write_bytes(data[:2] + segment + data[2:])


def _upright_source(tmp_path: Path) -> tuple[Path, Image.Image]:
    """A stored 600x300 JPEG tagged Orientation=6, plus the 300x600 display image.

    Orientation 6 means "rotate 90° clockwise to display", i.e. ``exif_transpose`` applies
    ``ROTATE_270`` — so the stored pixels are the display transposed ``ROTATE_90`` (the
    obverse). The self-check verifies *content* (a corner marker), not just the dimensions:
    both rotations swap width/height, so a size check alone cannot catch a 180° mistake.
    """
    display = _textured((300, 600))
    display.paste(Image.new("RGB", (24, 24), (255, 0, 0)), (0, 0))
    stored = display.transpose(Image.ROTATE_90)
    assert stored.size == (600, 300)
    base = tmp_path / "upright-base.jpg"
    stored.save(base, quality=92)
    tagged = tmp_path / "upright.jpg"
    _tagged_jpeg(base, tagged, 6)
    with Image.open(tagged) as opened:
        restored = ImageOps.exif_transpose(opened)
        corner = np.asarray(restored)[8:16, 8:16]
    assert restored.size == (300, 600)
    assert corner[:, :, 0].mean() > 150 and corner[:, :, 1].mean() < 100
    return tagged, display


def _protect(src: Path, out: Path, **overrides) -> dict:
    options = pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_VISIBLE}))
    for key, value in overrides.items():
        setattr(options, key, value)
    return pipeline.protect(src, out, options)


def test_orientation6_output_is_upright(tmp_path) -> None:
    tagged, _ = _upright_source(tmp_path)
    out = tmp_path / "out.jpg"

    info = _protect(tagged, out, visible_text="© t", long_edge=0)

    assert info["size"] == (300, 600)
    with Image.open(out) as image:
        assert image.size == (300, 600)


def test_orientation_tagged_output_carries_no_exif(tmp_path) -> None:
    tagged, _ = _upright_source(tmp_path)
    out = tmp_path / "out.jpg"

    _protect(tagged, out, visible_text="© t", long_edge=0)

    with Image.open(out) as image:
        assert not image.getexif()
        assert "exif" not in image.info


def test_orientation6_protect_verify_round_trip(tmp_path) -> None:
    tagged, _ = _upright_source(tmp_path)
    out = tmp_path / "out.jpg"
    payload = "owner:upright"
    pipeline.protect(
        tagged,
        out,
        pipeline.ProtectOptions(payload=payload, payload_envelope=True),
    )

    assert pipeline.verify_expected(out, payload)["verified"] is True


def test_tagged_suspect_is_read_in_display_orientation(tmp_path) -> None:
    """A tag added *after* protection points extraction at rotated pixels.

    The refusal shape varies with how much the rotation damages the decode — nothing
    recovered (``NoPayloadError``, CLI exit 1) or an uncertain/mismatched envelope (exit 2)
    — so the assertion is the invariant both share: the payload must not verify.
    """
    source = tmp_path / "flat.jpg"
    _textured((420, 260), seed=8).save(source, quality=92)
    payload = "owner:tagged"
    out = tmp_path / "out.jpg"
    pipeline.protect(
        source, out, pipeline.ProtectOptions(payload=payload, payload_envelope=True)
    )
    # Control: untagged, the same file verifies — the tag below is what breaks it.
    assert pipeline.verify_expected(out, payload)["verified"] is True

    suspect = tmp_path / "suspect.jpg"
    _tagged_jpeg(out, suspect, 6)

    with pytest.raises(ValueError):
        pipeline.verify_expected(suspect, payload)


def test_subject_watermark_lands_in_display_region(tmp_path) -> None:
    """The subject box must be computed on the display-oriented image, not the stored one."""
    from photo_guard import subject

    display = _textured((360, 540), seed=5)
    # A strong high-frequency patch in the display image's upper-left quadrant.
    patch = np.zeros((140, 140, 3), dtype=np.uint8)
    patch[::4, :, :] = 255
    patch[:, ::4, :] = 255
    display.paste(Image.fromarray(patch, "RGB"), (20, 20))
    stored = display.transpose(Image.ROTATE_90)
    base = tmp_path / "subj-base.jpg"
    stored.save(base, quality=92)
    tagged = tmp_path / "subj.jpg"
    _tagged_jpeg(base, tagged, 6)

    quiet = tmp_path / "quiet.jpg"
    loud = tmp_path / "loud.jpg"
    info = _protect(tagged, quiet, visible_mode="subject", visible_text="© subj", visible_alpha=0.0, long_edge=0)
    _protect(tagged, loud, visible_mode="subject", visible_text="© subj", visible_alpha=0.6, long_edge=0)
    assert info["size"] == (360, 540)

    with Image.open(quiet) as a, Image.open(loud) as b:
        diff = np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max(axis=2)

    mask = diff > 24
    coverage = mask.mean()
    assert 0.001 <= coverage <= 0.25, coverage

    # The painted region must sit inside the box the detector finds on the *display* image.
    display_bgr = np.asarray(display, dtype=np.uint8)[:, :, ::-1].copy()
    box = subject.detect_subject(display_bgr)
    ys, xs = np.nonzero(mask)
    assert box.x - 30 <= xs.mean() <= box.x + box.w + 30
    assert box.y - 30 <= ys.mean() <= box.y + box.h + 30


def test_rotating_a_protected_image_breaks_extraction(tmp_path) -> None:
    """Rotating the pixels without a tag is a real re-orientation: the payload must fail."""
    source = tmp_path / "flat.jpg"
    _textured((420, 260), seed=9).save(source, quality=92)
    payload = "owner:rotate"
    out = tmp_path / "out.jpg"
    pipeline.protect(
        source, out, pipeline.ProtectOptions(payload=payload, payload_envelope=True)
    )
    assert pipeline.verify_expected(out, payload)["verified"] is True

    rotated = tmp_path / "rotated.jpg"
    with Image.open(out) as image:
        image.rotate(90, expand=True).save(rotated, quality=95)

    # As in the tagged-suspect case the refusal shape varies; success is what must not happen.
    with pytest.raises(ValueError):
        pipeline.verify_expected(rotated, payload)


def test_untagged_source_is_not_rotated(tmp_path) -> None:
    source = tmp_path / "flat.jpg"
    _textured((420, 260), seed=10).save(source, quality=92)
    out = tmp_path / "out.jpg"

    info = _protect(source, out, visible_text="© t", long_edge=0)

    assert info["size"] == (420, 260)


def test_source_icc_profile_is_preserved(tmp_path) -> None:
    source = tmp_path / "icc.jpg"
    _textured((420, 260), seed=11).save(source, quality=92, icc_profile=ICC_BYTES)
    out = tmp_path / "out.jpg"

    _protect(source, out, visible_text="© t", long_edge=0)

    with Image.open(out) as image:
        assert image.info.get("icc_profile") == ICC_BYTES


def test_tagged_png_source_is_transposed(tmp_path) -> None:
    display = _textured((240, 400), seed=12)
    stored = display.transpose(Image.ROTATE_90)
    source = tmp_path / "tagged.png"
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = 6
    stored.save(source, exif=exif)
    out = tmp_path / "out.jpg"

    info = _protect(source, out, visible_text="© t", long_edge=0)

    assert info["size"] == (240, 400)


def test_tagged_tiff_is_not_double_rotated(tmp_path) -> None:
    display = _textured((240, 400), seed=13)
    stored = display.transpose(Image.ROTATE_90)
    source = tmp_path / "tagged.tiff"
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = 6
    stored.save(source, exif=exif)
    out = tmp_path / "out.jpg"

    info = _protect(source, out, visible_text="© t", long_edge=0)

    assert info["size"] == (240, 400)


@pytest.mark.parametrize(
    "magic", [b"not a tiff at all", b"JJ\x00*\x08\x00\x00\x00"], ids=["bad-magic-le", "bad-magic-be"]
)
def test_corrupt_exif_exits_two(tmp_path, capsys, magic: bytes) -> None:
    """P8/§4.3: a new exit-2 class — EXIF present but unparseable is refused, not guessed.

    Pillow 12.2.0 only hard-fails on an unparseable TIFF header (other damage — bogus IFD
    offsets, truncated entries — degrades to a warning), so both variants carry a malformed
    header. The spike's ``jfif_unit=0/1`` repro had the same shape; its materials live
    outside the repo (fix-plan §10.13 records the reconstruction).
    """
    base = tmp_path / "base.jpg"
    _textured((420, 260), seed=14).save(base, quality=92)
    payload = b"Exif\x00\x00" + magic
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    corrupt = tmp_path / "corrupt.jpg"
    data = base.read_bytes()
    corrupt.write_bytes(data[:2] + segment + data[2:])

    out = tmp_path / "out.jpg"
    assert main(["protect", str(corrupt), "-o", str(out)]) == 2
    assert "EXIF" in capsys.readouterr().err
    assert not out.exists()


def test_missing_exif_is_not_rejected(tmp_path) -> None:
    """The corrupt-EXIF refusal must not swallow the common no-EXIF case."""
    source = tmp_path / "plain.jpg"
    _textured((420, 260), seed=15).save(source, quality=92)
    out = tmp_path / "out.jpg"

    info = _protect(source, out, visible_text="© t", long_edge=0)

    assert info["size"] == (420, 260)


def test_long_edge_zero_keeps_the_original_size(tmp_path) -> None:
    """README:167 promises 0 = keep original size; the loader must not draft in that mode."""
    source = tmp_path / "big.jpg"
    _textured((3200, 2400), seed=16).save(source, quality=92)
    out = tmp_path / "out.jpg"

    info = _protect(source, out, visible_text="© t", long_edge=0)

    assert info["size"] == (3200, 2400)


def test_verify_side_corrupt_exif_exits_two(tmp_path, capsys) -> None:
    """R11: the input contract is shared with verify, not protect-only."""
    base = tmp_path / "base.jpg"
    _textured((420, 260), seed=17).save(base, quality=92)
    corrupt = tmp_path / "corrupt.jpg"
    _corrupt_exif_jpeg(base, corrupt)

    assert main(["verify", str(corrupt), "--payload-bytes", "7"]) == 2
    assert "EXIF" in capsys.readouterr().err


def test_loader_drops_exif_from_the_returned_image(tmp_path) -> None:
    """The helper's own contract: the returned image must not carry EXIF/XMP forward."""
    tagged, _ = _upright_source(tmp_path)

    image, icc = pipeline._load_oriented_rgb(tagged)

    assert image.size == (300, 600)
    assert icc is None
    assert "exif" not in image.info and "xmp" not in image.info
