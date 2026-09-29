"""G1 — the in-repo DWT-DCT-SVD transcription and the contract it took over.

``invisible-watermark`` used to supply the arithmetic, the bits↔bytes conversion and the
256x256 floor. Since G1 all three live here: the arithmetic verbatim in
``photo_guard._dwt_dct_svd`` (equivalence proven by the A/A'/B/C/D/E/F spike), the conversion
inside ``watermark_invisible.embed``/``extract``. The PNG fixture below was produced *before*
the dependency was removed, so it still pins the transcription against the library's own
output rather than against ourselves.

The tiny-image CLI branch is pinned through ``protect``: ``verify --payload-bytes`` goes
through the legacy clue path, which has a capacity check (P14) but no 256x256 floor, so
``protect`` is the only command that maps "image too small" to exit 2.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_guard import config, watermark_invisible as wi
from photo_guard.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "dwtDctSvd_legacy_512.png"
# Embedded by the removed library at scales [72, 0, 0] into a 512x512 noise frame (spike C).
PAYLOAD = "owner:alice#001"


def _fixture_bgr() -> np.ndarray:
    with Image.open(FIXTURE) as image:
        rgb = np.array(image.convert("RGB"))
    return rgb[:, :, ::-1].copy()


def test_legacy_fixture_decodes_exact_payload() -> None:
    """A fixture written by the removed library decodes exactly at its true length."""
    assert wi.extract(_fixture_bgr(), len(PAYLOAD.encode())) == PAYLOAD


def test_tiny_image_raises_runtime_error() -> None:
    """The 256x256 floor moved from the library into our own embed/extract."""
    tiny = np.zeros((255, 255, 3), dtype=np.uint8)
    with pytest.raises(RuntimeError, match="too small"):
        wi.embed(tiny, "x")
    with pytest.raises(RuntimeError, match="too small"):
        wi.extract(tiny, 4)


def test_tiny_image_protect_exits_two(tmp_path, capsys) -> None:
    src = tmp_path / "tiny.jpg"
    out = tmp_path / "out.jpg"
    Image.fromarray(np.zeros((255, 255, 3), dtype=np.uint8), "RGB").save(src, quality=92)

    code = main(["protect", str(src), "-o", str(out), "--layers", "invisible"])
    assert code == 2
    assert "too small" in capsys.readouterr().err
    assert not out.exists()


def test_unsupported_method_is_refused(monkeypatch) -> None:
    """Only dwtDctSvd exists in-repo; the old "switch to the lighter variant" is gone."""
    monkeypatch.setattr(config, "WATERMARK_METHOD", "dwtDct")
    bgr = np.zeros((256, 256, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="dwtDctSvd"):
        wi.embed(bgr, PAYLOAD)
    with pytest.raises(ValueError, match="dwtDctSvd"):
        wi.extract(bgr, len(PAYLOAD.encode()))
    monkeypatch.undo()

    marked = wi.embed(bgr, PAYLOAD)
    assert wi.extract(marked, len(PAYLOAD.encode())) == PAYLOAD


def test_embed_extract_utf8_payload_roundtrip() -> None:
    """A non-ASCII payload whose byte length is not a multiple of 8 (spike A2's shape)."""
    payload = "© 水印"
    assert len(payload.encode()) % 8 != 0

    rng = np.random.default_rng(43)
    bgr = rng.integers(60, 200, (507, 511, 3), dtype=np.uint8)
    bits = list(np.unpackbits(np.frombuffer(payload.encode("utf-8"), dtype=np.uint8)))
    marked = wi._CarrierEmbed(
        watermarks=bits,
        wmLen=len(bits),
        scales=wi._scales_for(1, 36),
        block=wi._BLOCK,
    ).encode(bgr)

    assert wi.extract(marked, len(payload.encode()), carrier=(1, 36)) == payload
