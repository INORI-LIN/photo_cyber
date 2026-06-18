"""Perturber registry + lazy-import contract for the SD perturber.

CLAUDE.md flags this as a load-bearing invariant: importing photo_guard.perturb
must NOT pull in torch / diffusers. Only the first apply() on the SD perturber
may. We assert that explicitly here so a careless `import torch` at the top of
perturb.py would fail this test.
"""
from __future__ import annotations

import importlib
import sys

import numpy as np
import pytest

from photo_guard import perturb


def test_available_lists_all_three() -> None:
    assert perturb.available() == ["noise", "noop", "sd"]


def test_noop_is_identity() -> None:
    img = np.full((32, 32, 3), 100, dtype=np.uint8)
    out = perturb.get("noop").apply(img)
    assert out is img or np.array_equal(out, img)


def test_noise_within_epsilon() -> None:
    img = np.full((48, 48, 3), 128, dtype=np.uint8)
    eps = 4.0 / 255.0
    out = perturb.get("noise", epsilon=eps, seed=0).apply(img)
    assert out.shape == img.shape
    assert out.dtype == img.dtype
    # Noise is Gaussian, not bounded — but std≈eps*255 keeps almost all pixels close.
    diff = np.abs(out.astype(int) - img.astype(int))
    # 99th percentile within ~4σ of the noise scale
    assert np.percentile(diff, 99) <= eps * 255 * 4


def test_unknown_perturber_raises() -> None:
    with pytest.raises(ValueError, match="unknown perturber"):
        perturb.get("does-not-exist")


# --- lazy-import contract ----------------------------------------------------


def _scrub_heavy_modules() -> None:
    """Force re-import of perturb without torch/diffusers in sys.modules."""
    for mod in list(sys.modules):
        if mod == "torch" or mod.startswith("torch."):
            del sys.modules[mod]
        if mod == "diffusers" or mod.startswith("diffusers."):
            del sys.modules[mod]
        if mod.endswith(".photoguard"):
            del sys.modules[mod]


def test_importing_perturb_does_not_import_torch() -> None:
    """Re-importing photo_guard.perturb on a clean slate must not import torch."""
    _scrub_heavy_modules()
    importlib.reload(perturb)
    # Construct the SD perturber — still must not pull torch in.
    p = perturb.get("sd", steps=1)
    assert p.name == "sd"
    assert "torch" not in sys.modules, (
        "perturb construction triggered an unexpected `import torch`; "
        "the lazy-import contract is broken."
    )


def test_sd_apply_without_diffusers_gives_clean_error(monkeypatch) -> None:
    """When diffusers can't be imported inside photoguard._load, apply() must
    raise a RuntimeError pointing the user at `uv sync --extra photoguard`.

    We patch `photoguard._SDEncoderAttack._load` itself instead of meddling
    with `builtins.__import__`, because torch's CUDA-preload path also routes
    through `__import__` and a coarse hook breaks unrelated machinery.
    """
    from photo_guard import photoguard as pg_mod

    def fake_load(self):
        raise RuntimeError(
            "PhotoGuard SD-encoder perturber needs the optional "
            "`photoguard` extra. Install it with: "
            "`uv sync --extra photoguard`"
        )

    monkeypatch.setattr(pg_mod._SDEncoderAttack, "_load", fake_load)

    p = perturb.get("sd", steps=1)
    with pytest.raises(RuntimeError, match="uv sync --extra photoguard"):
        p.apply(np.zeros((32, 32, 3), dtype=np.uint8))
