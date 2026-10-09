"""P4 — ``protect`` refuses the impossible and verifies its own product.

Two defects are pinned here (docs/fix-plan.md §6 P4 / §10.14):

* an over-capacity payload used to embed what fits, write the file and exit 0 — the product
  was silently unverifiable (the tail bits decode as 0x00);
* nothing re-read the written JPEG, so a product the decoder cannot recover was still
  reported as success.

The self-check runs on the **temp** file before ``os.replace`` (M-A), so a failure leaves
neither a new product nor damage to a previous one.
"""
from __future__ import annotations

import pytest
from PIL import Image

from photo_guard import outputs, pipeline, watermark_invisible


def _solid(path, size=(320, 260), color=(10, 20, 30)):
    Image.new("RGB", size, color).save(path, quality=92)
    return path


def test_protect_refuses_over_capacity_before_writing(tmp_path) -> None:
    source = _solid(tmp_path / "in.jpg", (320, 320))  # capacity = 200 stored bytes
    out = tmp_path / "out.jpg"
    options = pipeline.ProtectOptions(
        payload="A" * 201, layers=frozenset({"invisible", "visible"})
    )

    with pytest.raises(ValueError, match="can carry at most"):
        pipeline.protect(source, out, options)

    assert not out.exists()
    assert not list(tmp_path.glob(f"{outputs._TEMP_PREFIX}*"))


def test_protect_refuses_below_the_pixel_floor(tmp_path) -> None:
    source = _solid(tmp_path / "small.jpg", (200, 200))
    out = tmp_path / "out.jpg"

    with pytest.raises(ValueError) as excinfo:
        pipeline.protect(source, out, pipeline.ProtectOptions())

    message = str(excinfo.value)
    assert "too small" in message and "65536" in message
    assert not out.exists()


def test_the_capacity_gate_is_scoped_to_the_invisible_layer(tmp_path) -> None:
    """A long payload is irrelevant when the layer that would carry it does not run."""
    source = _solid(tmp_path / "in.jpg", (320, 320))
    out = tmp_path / "out.jpg"
    options = pipeline.ProtectOptions(
        payload="A" * 201, layers=frozenset({"visible"}), visible_text="© t"
    )

    pipeline.protect(source, out, options)

    assert out.exists()


@pytest.mark.parametrize("envelope", [False, True], ids=["raw", "envelope"])
def test_self_check_failure_is_loud_and_leaves_no_file(tmp_path, monkeypatch, envelope: bool) -> None:
    source = _solid(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    if envelope:
        monkeypatch.setattr(watermark_invisible, "extract_envelope", lambda *_a, **_k: "wrong")
    else:
        monkeypatch.setattr(watermark_invisible, "extract", lambda *_a, **_k: "wrong")
    options = pipeline.ProtectOptions(
        payload="owner:x", payload_envelope=envelope, layers=frozenset({"invisible", "visible"})
    )

    with pytest.raises(ValueError, match="self-check"):
        pipeline.protect(source, out, options)

    assert not out.exists()
    assert not list(tmp_path.glob(f"{outputs._TEMP_PREFIX}*"))


def test_a_failed_self_check_does_not_damage_a_previous_product(tmp_path, monkeypatch) -> None:
    """M-A: verification happens before the swap, so the old verified product survives."""
    source = _solid(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    options = pipeline.ProtectOptions(layers=frozenset({"invisible", "visible"}))
    pipeline.protect(source, out, options)
    before = out.read_bytes()

    monkeypatch.setattr(watermark_invisible, "extract", lambda *_a, **_k: "wrong")
    with pytest.raises(ValueError, match="self-check"):
        pipeline.protect(source, out, options)

    assert out.read_bytes() == before


def test_the_self_check_uses_the_byte_exact_extract(monkeypatch, tmp_path) -> None:
    """The raw path must compare through ``extract``, not ``verify``'s garbage filter.

    A legal periodic payload (``abab``) is exactly what ``is_recoverable_text`` rejects, so
    routing the self-check through ``verify`` would fail honest products; this pins the
    byte-exact path by making ``extract_legacy`` explode.
    """
    source = _solid(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"

    def _explode(*_args, **_kwargs):
        raise AssertionError("the self-check must not route through extract_legacy")

    monkeypatch.setattr(watermark_invisible, "extract_legacy", _explode)
    pipeline.protect(
        source, out, pipeline.ProtectOptions(payload="abab", layers=frozenset({"invisible", "visible"}))
    )

    assert out.exists()
