"""P1 — the real SD path is exercised end to end, on CPU, deterministically.

The fast tier only locks decisions; this file is the one place that runs the real
diffusers/torch stack (marker ``slow``; excluded from CI's fast legs and from the release
``verify`` chain). Skips carry an actionable reason when the extra or the local model is
missing. Top-level imports deliberately avoid torch/diffusers (AGENTS §8.4 laziness).

Contract frozen here for P5/M2: ``config.PHOTOGUARD_SEED`` / ``PGDConfig.seed`` /
``SDEncoderPerturber(seed=...)`` / ``device="cpu"`` for byte-level reproducibility, and this
file's path.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from photo_guard import config, perturb, photoguard, pipeline

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        importlib.util.find_spec("torch") is None
        or importlib.util.find_spec("diffusers") is None,
        reason="needs the photoguard extra: uv sync --frozen --extra photoguard",
    ),
    pytest.mark.skipif(
        not Path(config.PHOTOGUARD_MODELS_DIR).is_dir(),
        reason="needs the local SD VAE: uv run photo-guard download-models",
    ),
]

STEPS = 3  # enough to exercise the loop; keeps the slow tier cheap on CPU


def _image(seed: int = 5, size: tuple[int, int] = (64, 64)) -> np.ndarray:
    return np.random.default_rng(seed).integers(40, 210, (size[1], size[0], 3), dtype=np.uint8)


def _objective(attack, image_bgr: np.ndarray) -> float:
    """``MSE(latent(x), 0)`` — the attack's own objective, recomputed for the assertion."""
    import torch

    rgb = image_bgr[:, :, ::-1].astype(np.float32) / 255.0
    padded = photoguard.pad_to_multiple_of_8(rgb)
    x = torch.from_numpy(padded).permute(2, 0, 1).unsqueeze(0).to(
        attack._device, dtype=attack._dtype
    )
    x = x * 2.0 - 1.0
    with torch.no_grad():
        latent = attack._encode_mean(x)
        return float(torch.nn.functional.mse_loss(latent, torch.zeros_like(latent)))


@pytest.fixture(scope="module")
def attack():
    """One model load for the whole module (loading is the expensive part)."""
    return photoguard.build_attack(photoguard.PGDConfig(device="cpu", steps=STEPS, seed=0))


def test_default_seed_reaches_pgd_config() -> None:
    assert config.PHOTOGUARD_SEED == 0
    assert photoguard.PGDConfig().seed == config.PHOTOGUARD_SEED


def test_seed_reaches_pgd_config_via_the_perturber() -> None:
    sd = perturb.get("sd", seed=7)
    sd._ensure()  # builds the PGDConfig without loading the model
    assert sd._attack.cfg.seed == 7


def test_attack_same_seed_same_output() -> None:
    image = _image()
    first = photoguard.build_attack(photoguard.PGDConfig(device="cpu", steps=STEPS, seed=0)).attack(image)
    second = photoguard.build_attack(photoguard.PGDConfig(device="cpu", steps=STEPS, seed=0)).attack(image)

    assert np.array_equal(first, second)


def test_attack_different_seed_different_output() -> None:
    image = _image()
    first = photoguard.build_attack(photoguard.PGDConfig(device="cpu", steps=STEPS, seed=0)).attack(image)
    other = photoguard.build_attack(photoguard.PGDConfig(device="cpu", steps=STEPS, seed=1)).attack(image)

    assert not np.array_equal(first, other)


@pytest.mark.parametrize("size", [(8, 8), (16, 24), (64, 64), (1, 1)])
def test_attack_preserves_shape_and_dtype(attack, size: tuple[int, int]) -> None:
    image = _image(size=size)
    out = attack.attack(image)

    assert out.shape == image.shape
    assert out.dtype == image.dtype


def test_attack_respects_l_inf_budget(attack) -> None:
    image = _image()
    out = attack.attack(image)

    budget = round(config.PHOTOGUARD_EPSILON * 255.0)
    delta = np.abs(out.astype(np.int16) - image.astype(np.int16))
    assert delta.max() <= budget
    assert delta.max() >= 1  # the attack is not a no-op


def test_attack_reduces_objective(attack) -> None:
    image = _image()
    before = _objective(attack, image)
    out = attack.attack(image)
    after = _objective(attack, out)

    assert after / before < 1.0


def test_protect_sd_is_byte_reproducible(tmp_path) -> None:
    source = tmp_path / "in.jpg"
    from PIL import Image

    Image.fromarray(_image(), "RGB").save(source, quality=92)
    options = pipeline.ProtectOptions(
        layers=frozenset({pipeline.LAYER_PERTURB}),
        perturber="sd",
        perturber_kwargs={"device": "cpu", "steps": 2},
    )
    first, second = tmp_path / "a.jpg", tmp_path / "b.jpg"

    pipeline.protect(source, first, options)
    pipeline.protect(source, second, options)

    assert first.read_bytes() == second.read_bytes()


def test_latent_delivery_ratio_is_measurable(attack) -> None:
    """P5: `latent_norm` measures the encoder response on a real image (CPU).

    `latent_norm` is the accessor the P5 retention statement is measured with; the
    pair (clean, delivered) must yield finite positive norms, and the encoder attack
    must move the delivered norm below the clean one (its objective is MSE toward a
    zero latent, and MSE(latent, 0) is proportional to the squared norm). The size is
    a non-multiple of 8 on purpose, so the pad path inside `_to_tensor` is exercised
    for real.
    """
    import math

    image = _image(size=(65, 47))
    clean = attack.latent_norm(image)
    delivered = attack.latent_norm(attack.attack(image))

    assert math.isfinite(clean) and clean > 0
    assert math.isfinite(delivered) and delivered > 0
    assert 0.0 < delivered / clean < 1.0
