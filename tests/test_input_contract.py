"""G4 — the input contract: format, pixel ceiling, single frame, alpha matte.

Before G4 ``convert("RGB")`` was an unconditional normaliser: any format decoded full-size,
multi-frame files silently lost every frame after the first, transparent pixels leaked their
hidden RGB, and the only size ceiling was Pillow's own warn-then-decode threshold. All four
are now decided in ``pipeline._load_oriented_rgb`` before ``.load()``.
"""
from __future__ import annotations

import struct
import warnings
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_guard import config, pipeline
from photo_guard.cli import main


def _textured(size: tuple[int, int], *, seed: int = 4) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(40, 210, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


def _protect(src: Path, out: Path, **overrides) -> dict:
    options = pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_VISIBLE}), visible_text="© t")
    for key, value in overrides.items():
        setattr(options, key, value)
    return pipeline.protect(src, out, options)


def _png_header_only(path: Path, width: int, height: int) -> None:
    """A PNG whose header claims huge dimensions and whose body has no pixel data."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("suffix", "fmt"),
    [(".jpg", "JPEG"), (".png", "PNG"), (".webp", "WEBP"), (".bmp", "BMP"), (".tiff", "TIFF")],
)
def test_supported_formats_round_trip(tmp_path, suffix: str, fmt: str) -> None:
    path = tmp_path / f"img{suffix}"
    Image.new("RGB", (64, 48), (120, 130, 140)).save(path)
    with Image.open(path) as image:
        assert image.format == fmt
    assert fmt in config.SUPPORTED_INPUT_FORMATS


def test_formats_policy_pinned() -> None:
    assert config.SUPPORTED_INPUT_FORMATS == ("JPEG", "PNG", "WEBP", "BMP", "TIFF")
    assert config.MAX_INPUT_PIXELS == 64_000_000
    assert config.ALPHA_MATTE == (255, 255, 255)


def test_ceiling_rejects_strictly_above_the_cap(tmp_path, capsys) -> None:
    """> MAX_INPUT_PIXELS is refused on the header alone — and with no bomb warning."""
    over = tmp_path / "over.png"
    _png_header_only(over, 8001, 8001)  # 64_016_001 > 64_000_000, below Pillow's warn line
    out = tmp_path / "out.jpg"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert main(["protect", str(over), "-o", str(out)]) == 2

    assert "pixels" in capsys.readouterr().err
    assert not any(
        issubclass(w.category, Image.DecompressionBombWarning) for w in caught
    )
    assert not out.exists()


def test_bomb_sized_header_is_refused_before_decode(tmp_path, capsys) -> None:
    bomb = tmp_path / "bomb.png"
    _png_header_only(bomb, 20000, 10000)  # 200 MP, beyond Pillow's hard error line
    out = tmp_path / "out.jpg"

    assert main(["protect", str(bomb), "-o", str(out)]) == 2
    assert "pixels" in capsys.readouterr().err
    assert not out.exists()


def test_multiframe_is_rejected(tmp_path, capsys) -> None:
    frames = [
        Image.new("RGB", (320, 260), (10, 20, 30)),
        Image.new("RGB", (320, 260), (200, 180, 160)),
    ]
    multi = tmp_path / "two.tiff"
    frames[0].save(multi, save_all=True, append_images=frames[1:])
    out = tmp_path / "out.jpg"

    assert main(["protect", str(multi), "-o", str(out)]) == 2
    assert "frames" in capsys.readouterr().err

    single = tmp_path / "one.tiff"
    frames[0].save(single)
    assert main(["protect", str(single), "-o", str(tmp_path / "one-out.jpg")]) == 0


def test_transparent_png_goes_white(tmp_path) -> None:
    """Fully transparent pixels must flatten onto white — hidden RGB must not leak."""
    source = tmp_path / "alpha.png"
    arr = np.zeros((256, 256, 4), dtype=np.uint8)
    arr[..., :3] = (10, 20, 30)
    arr[..., 3] = 0
    Image.fromarray(arr, "RGBA").save(source)
    out = tmp_path / "out.jpg"

    _protect(source, out, visible_alpha=0.0, long_edge=0)

    with Image.open(out) as image:
        pixels = np.asarray(image, dtype=np.int16)
    assert pixels.mean() >= 220
    assert np.abs(pixels - np.array([10, 20, 30])).max() > 100


def test_half_transparent_blends_by_alpha_weight(tmp_path) -> None:
    source = tmp_path / "half.png"
    arr = np.zeros((256, 256, 4), dtype=np.uint8)  # black at alpha 128 → ≈127 over white
    arr[..., 3] = 128
    Image.fromarray(arr, "RGBA").save(source)
    out = tmp_path / "out.jpg"

    _protect(source, out, visible_alpha=0.0, long_edge=0)

    with Image.open(out) as image:
        mean = np.asarray(image, dtype=np.int16).mean()
    assert 115 <= mean <= 140, mean


def test_palette_transparency_goes_white(tmp_path) -> None:
    palette = Image.new("P", (256, 256))
    palette.putpalette([10, 20, 30] * 256)
    source = tmp_path / "pal.png"
    palette.save(source, transparency=0)
    out = tmp_path / "out.jpg"

    _protect(source, out, visible_alpha=0.0, long_edge=0)

    with Image.open(out) as image:
        pixels = np.asarray(image, dtype=np.int16)
    assert pixels.mean() >= 220
    assert np.abs(pixels - np.array([10, 20, 30])).max() > 100


def test_large_jpeg_is_drafted_before_decode(tmp_path, monkeypatch) -> None:
    """4000x3000 asks for a scale-2 draft, and the long edge must still land on 1080."""
    from PIL import JpegImagePlugin

    calls: list[tuple[str, tuple[int, int]]] = []
    original = JpegImagePlugin.JpegImageFile.draft  # the JPEG plugin overrides the base no-op

    def spy(self, mode, size):
        calls.append((mode, size))
        return original(self, mode, size)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", spy)
    source = tmp_path / "large.jpg"
    _textured((4000, 3000), seed=22).save(source, quality=92)
    out = tmp_path / "out.jpg"

    info = _protect(source, out)

    assert calls and calls[0][1] == (1080, 1080)
    assert max(info["size"]) == 1080


def test_unsupported_formats_are_rejected_actionably(tmp_path, capsys) -> None:
    gif = tmp_path / "single.gif"
    Image.new("P", (64, 64)).save(gif, format="GIF")
    out = tmp_path / "out.jpg"

    assert main(["protect", str(gif), "-o", str(out)]) == 2
    assert "unsupported input format" in capsys.readouterr().err
    assert not out.exists()

    assert main(["verify", str(gif), "--payload-bytes", "7"]) == 2
    assert "unsupported input format" in capsys.readouterr().err


def test_heic_like_input_is_refused_with_a_hint(tmp_path, capsys) -> None:
    heic = tmp_path / "photo.heic"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(24))
    out = tmp_path / "out.jpg"

    assert main(["protect", str(heic), "-o", str(out)]) == 2
    assert "HEIC" in capsys.readouterr().err
    assert not out.exists()


def test_verify_side_shares_the_input_contract(tmp_path, capsys) -> None:
    """R11: verify uses the same loader — frames and pixels are refused there too."""
    frames = [
        Image.new("RGB", (320, 260), (10, 20, 30)),
        Image.new("RGB", (320, 260), (200, 180, 160)),
    ]
    multi = tmp_path / "two.tiff"
    frames[0].save(multi, save_all=True, append_images=frames[1:])

    assert main(["verify", str(multi), "--payload-bytes", "7"]) == 2
    assert "frames" in capsys.readouterr().err

    over = tmp_path / "over.png"
    _png_header_only(over, 8001, 8001)
    assert main(["verify", str(over), "--payload-bytes", "7"]) == 2
    assert "pixels" in capsys.readouterr().err
