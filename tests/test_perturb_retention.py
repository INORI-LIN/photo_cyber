"""P5 — the JPEG q85 delivery path neither loses the perturbation nor the pairing.

Fast tier, core only: no torch/diffusers imports anywhere in this module. Both cases
pair two protects of the same source — control (noise ``epsilon=0.0``, identity) vs
treated (noise at the default ``epsilon``) — and pin (1) byte-level determinism of the
pairing and (2) that the delivered difference survives the delivery path far above the
injected scale.

Measured facts behind the thresholds (P5/M2 Step-0 probes, 2026-10-10; 480x360
textured source, ``ALL_LAYERS``, tile, q85 default): the pre-save difference is clipped
to ±2/255, while the delivered difference reaches max 33, mean 6.05 and 98.2% non-zero
pixels. The save path does not merely preserve the perturbation — q85 quantization
flips remix it into a larger, high-frequency-dominated difference field. A
frequency-selectivity claim ("low frequencies survive better") was probed in six
formulations (band maxima, delta-component correlation, luma-only, quality sweep, FFT
radial energy, structured two-band delta) and does not hold at any viable amplitude,
so it is deliberately not asserted here — see docs/fix-plan.md (P5/M2 landing record).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from photo_guard import config, pipeline

SIZE = (480, 360)


def _textured(size: tuple[int, int] = SIZE, seed: int = 3) -> Image.Image:
    return Image.fromarray(
        np.random.default_rng(seed).integers(40, 210, (size[1], size[0], 3), dtype=np.uint8),
        "RGB",
    )


def _protect(source: Path, out: Path, *, epsilon: float) -> np.ndarray:
    pipeline.protect(
        source,
        out,
        pipeline.ProtectOptions(
            layers=pipeline.ALL_LAYERS,
            perturber="noise",
            perturber_kwargs={"epsilon": epsilon},
            visible_mode="tile",
            long_edge=0,
        ),
    )
    with Image.open(out) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16)


def test_paired_control_is_byte_deterministic(tmp_path) -> None:
    """Both arms run through the factory path, so each protect is byte-reproducible.

    Determinism comes from a fresh seeded perturber per protect (never a shared
    instance — its RNG would advance between calls) plus the fully deterministic
    embed → tile → save chain.
    """
    source = tmp_path / "in.jpg"
    _textured().save(source, quality=92)

    for epsilon in (0.0, config.NOISE_EPSILON):
        first, second = tmp_path / "a.jpg", tmp_path / "b.jpg"
        _protect(source, first, epsilon=epsilon)
        _protect(source, second, epsilon=epsilon)

        assert first.read_bytes() == second.read_bytes()


def test_save_path_transmits_the_perturbation(tmp_path) -> None:
    """The delivered difference survives the q85 path far above the injected bound.

    Thresholds are format- and quality-robust (they hold for a lossless container and
    for q100 as well): what they pin is that the perturbation is *not* erased by the
    delivery chain, not the current magnitude of the quantization coupling.
    """
    source = tmp_path / "in.jpg"
    _textured().save(source, quality=92)
    control = _protect(source, tmp_path / "control.jpg", epsilon=0.0)
    treated = _protect(source, tmp_path / "treated.jpg", epsilon=config.NOISE_EPSILON)

    res = np.abs(treated - control).max(axis=2)
    injected = round(config.NOISE_EPSILON * 255.0)  # 2 gray levels

    assert res.max() >= injected  # 33 measured, >= injected documented
    assert res.mean() >= 1.0  # 6.05 measured
    assert (res > 0).mean() >= 0.5  # 98.2% measured
