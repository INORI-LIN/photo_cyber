"""P17 — pin the *real* padding contract instead of restating its arithmetic.

The previous version recomputed ``height + (-height) % 8`` inside the test and never called
the attack code, so it could not fail when the implementation changed. It now calls the
shipped helper. ``photoguard`` keeps torch/diffusers lazy, so this file stays in the fast
tier and needs no importorskip.
"""
from __future__ import annotations

import numpy as np
import pytest

from photo_guard import photoguard


@pytest.mark.parametrize(
    ("height", "width"), [(8, 8), (9, 7), (240, 320), (1, 1), (13, 130)]
)
def test_padding_rounds_up_to_a_multiple_of_eight(height: int, width: int) -> None:
    rgb = np.random.default_rng(11).random((height, width, 3), dtype=np.float32)

    padded = photoguard.pad_to_multiple_of_8(rgb)

    assert padded.shape[:2] == (((height + 7) // 8) * 8, ((width + 7) // 8) * 8)
    assert padded.shape[0] % 8 == 0 and padded.shape[1] % 8 == 0
    # The attack crops back with [:h, :w] after the VAE round trip, so the padding must
    # leave the original region untouched.
    assert np.array_equal(padded[:height, :width], rgb)


@pytest.mark.parametrize(
    ("epsilon", "step_size"),
    [
        (float("nan"), 2 / 255),
        (float("inf"), 2 / 255),
        (float("-inf"), 2 / 255),
        (-1 / 255, 2 / 255),
        (8 / 255, float("nan")),
        (8 / 255, float("inf")),
        (8 / 255, -1 / 255),
    ],
    ids=["eps-nan", "eps-inf", "eps--inf", "eps-negative", "step-nan", "step-inf", "step-negative"],
)
def test_pgd_config_rejects_non_finite_or_negative_budgets(
    epsilon: float, step_size: float
) -> None:
    """Q2/N4: PGDConfig is the last gate before the model loads; NaN must die here."""
    with pytest.raises(ValueError, match="finite and non-negative"):
        photoguard.PGDConfig(epsilon=epsilon, step_size=step_size)


def test_pgd_config_allows_zero_budgets_for_control_groups() -> None:
    config = photoguard.PGDConfig(epsilon=0.0, step_size=0.0)
    assert config.epsilon == 0.0 and config.step_size == 0.0


def test_padding_repeats_the_edge_pixel() -> None:
    rgb = np.zeros((9, 9, 3), dtype=np.float32)
    rgb[8, :, :] = 1.0
    rgb[:, 8, :] = 2.0  # (8, 8) ends up 2.0: the column wins

    padded = photoguard.pad_to_multiple_of_8(rgb)

    assert np.all(padded[9:, :8] == 1.0)  # added rows copy the last row
    assert np.all(padded[:, 9:] == 2.0)  # added columns copy the last column


def test_attack_rejects_bad_input(monkeypatch) -> None:
    """P1: input validation runs *before* the model load, so a bad call fails fast.

    The monkeypatch is what makes the ordering observable (and this test red on the pre-P1
    code even on a machine with the extra installed): if ``attack()`` ever loads before
    validating, the load path explodes instead of raising the expected ``ValueError``.
    """
    attack = photoguard.build_attack()

    def _explode():
        raise AssertionError("the model must not be loaded before input validation")

    monkeypatch.setattr(attack, "_ensure_loaded", _explode)

    with pytest.raises(ValueError, match="three-channel"):
        attack.attack(np.zeros((16, 16), dtype=np.uint8))
    with pytest.raises(ValueError, match="empty"):
        attack.attack(np.zeros((0, 0, 3), dtype=np.uint8))


def test_attack_cancels_before_model_load(monkeypatch) -> None:
    """P7: a cancelled batch must not load the VAE just to bail on the first PGD step."""
    attack = photoguard.build_attack(photoguard.PGDConfig(cancel_check=lambda: True))

    def _explode():
        raise AssertionError("the model must not be loaded after cancellation")

    monkeypatch.setattr(attack, "_ensure_loaded", _explode)

    with pytest.raises(InterruptedError, match="cancelled"):
        attack.attack(np.zeros((16, 16, 3), dtype=np.uint8))


def test_attack_validates_before_cancel_check() -> None:
    """P1 priority: a bad image still fails validation, even when cancellation is pending."""
    calls: list[int] = []

    def cancel_check() -> bool:
        calls.append(1)
        return True

    attack = photoguard.build_attack(photoguard.PGDConfig(cancel_check=cancel_check))

    with pytest.raises(ValueError, match="three-channel"):
        attack.attack(np.zeros((16, 16), dtype=np.uint8))
    assert calls == []
