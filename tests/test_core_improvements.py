from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from photo_guard import compress, pipeline, watermark_invisible, watermark_visible


def test_long_edge_zero_preserves_size() -> None:
    image = Image.new("RGB", (321, 123))
    assert compress.fit_long_edge(image, 0).size == (321, 123)


def test_long_edge_negative_rejected() -> None:
    with pytest.raises(ValueError, match="long_edge"):
        compress.fit_long_edge(Image.new("RGB", (20, 20)), -1)


@pytest.mark.parametrize("quality", [0, 101])
def test_invalid_quality_rejected(quality: int) -> None:
    with pytest.raises(ValueError, match="quality"):
        pipeline.validate_options(pipeline.ProtectOptions(quality=quality))


@pytest.mark.parametrize("alpha", [-0.1, 1.1])
def test_invalid_alpha_rejected(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        pipeline.validate_options(pipeline.ProtectOptions(visible_alpha=alpha))


def test_noop_perturb_layer_rejected() -> None:
    with pytest.raises(ValueError, match="noop"):
        pipeline.validate_options(
            pipeline.ProtectOptions(layers=frozenset({"perturb"}), perturber="noop")
        )


class _RecordingPerturber:
    """A stand-in for a caller-supplied perturber: records that it ran, changes nothing."""

    name = "recording"

    def __init__(self, *, falsy: bool = False) -> None:
        self.calls = 0
        self._falsy = falsy

    def __bool__(self) -> bool:
        return not self._falsy

    def apply(self, image):
        self.calls += 1
        return image


def test_noop_perturber_with_an_instance_is_accepted_and_used(
    textured_jpg, tmp_path
) -> None:
    """P30: ``validate_options`` used to reject a combination ``protect`` handles fine.

    The rejection must only fire when there is no instance to fall back on; when one is
    supplied, the layer has to run it — not the ``noop`` factory it shadows.
    """
    instance = _RecordingPerturber()
    options = pipeline.ProtectOptions(
        layers=frozenset({"perturb"}), perturber="noop", perturber_instance=instance
    )
    pipeline.validate_options(options)  # pre-fix: ValueError("perturb layer uses noop")

    pipeline.protect(textured_jpg, tmp_path / "out.jpg", options)

    assert instance.calls == 1


def test_a_falsy_instance_is_still_used_not_silently_replaced(
    textured_jpg, tmp_path
) -> None:
    """P30, closing the reverse direction: a falsy instance must not fall into the factory.

    ``protect`` used to pick ``opts.perturber_instance or perturb.get(...)``; an object
    whose truthiness is False would pass the new gate and then be silently swapped for the
    noop factory — reporting success with zero perturbation.
    """
    instance = _RecordingPerturber(falsy=True)
    options = pipeline.ProtectOptions(
        layers=frozenset({"perturb"}), perturber="noop", perturber_instance=instance
    )

    pipeline.protect(textured_jpg, tmp_path / "out.jpg", options)

    assert instance.calls == 1


def test_payload_envelope_crc_round_trip() -> None:
    stored = watermark_invisible.pack_payload("owner:alice")
    payload, verified = watermark_invisible.unpack_payload(stored)
    assert payload == "owner:alice"
    assert verified is True
    damaged = stored[:-1] + ("A" if stored[-1] != "A" else "B")
    with pytest.raises(ValueError):
        watermark_invisible.unpack_payload(damaged)


def test_legacy_payload_is_unverified() -> None:
    assert watermark_invisible.unpack_payload("legacy") == ("legacy", False)


def test_visible_subject_respects_zero_alpha(monkeypatch) -> None:
    source = Image.new("RGB", (300, 200), (40, 50, 60))
    out = watermark_visible.apply(source, "hidden", mode="subject", alpha=0.0)
    assert np.array_equal(np.array(source), np.array(out))


def test_enveloped_pipeline_verify_expected(textured_jpg, tmp_path) -> None:
    output = tmp_path / "enveloped.jpg"
    payload = "owner:crc#001"
    info = pipeline.protect(
        textured_jpg,
        output,
        pipeline.ProtectOptions(
            payload=payload,
            visible_mode="tile",
            visible_text="© crc",
            payload_envelope=True,
        ),
    )
    assert info["payload_envelope"] is True
    assert pipeline.verify_expected(output, payload)["verified"] is True
