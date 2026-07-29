"""Layer ② — adversarial perturbation (AGENTS.md 三②).

Three implementations:

- ``NoopPerturber``: identity. Pipeline-only smoke testing / "off" switch.
- ``GaussianNoisePerturber``: ε-bounded Gaussian noise, deterministic seed.
  Lightweight placeholder; mostly useful for testing the wiring.
- ``SDEncoderPerturber``: real PhotoGuard-style PGD attack against a Stable
  Diffusion VAE encoder. Loaded lazily — importing this module does **not**
  import torch / diffusers; the heavy import only happens when you actually
  call ``apply()`` on an SD perturber instance.

The CLI selects an implementation by name via :func:`get`; per-implementation
kwargs (``epsilon``, ``steps`` …) are forwarded through the same call.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from . import config


class Perturber(ABC):
    name: str = "perturber"

    @abstractmethod
    def apply(self, image_bgr: np.ndarray) -> np.ndarray:
        ...


class NoopPerturber(Perturber):
    name = "noop"

    def apply(self, image_bgr: np.ndarray) -> np.ndarray:
        return image_bgr


class GaussianNoisePerturber(Perturber):
    """ε-bounded Gaussian noise, fixed seed for determinism."""

    name = "noise"

    def __init__(
        self, *, epsilon: float = config.NOISE_EPSILON, seed: int = 0, **_: Any
    ) -> None:
        self.epsilon = epsilon
        self._rng = np.random.default_rng(seed)

    def apply(self, image_bgr: np.ndarray) -> np.ndarray:
        scale = self.epsilon * 255.0
        noise = self._rng.normal(0.0, scale, size=image_bgr.shape)
        out = image_bgr.astype(np.float32) + noise
        return np.clip(out, 0, 255).astype(np.uint8)


class SDEncoderPerturber(Perturber):
    """PhotoGuard encoder-attack: PGD against a SD VAE encoder.

    Lazily imports torch / diffusers / safetensors via :mod:`.photoguard` so
    the rest of the package stays usable without the optional extra.
    """

    name = "sd"

    def __init__(
        self,
        *,
        epsilon: float = config.PHOTOGUARD_EPSILON,
        steps: int = config.PHOTOGUARD_STEPS,
        step_size: float = config.PHOTOGUARD_STEP_SIZE,
        model_id: str = config.PHOTOGUARD_MODEL_ID,
        device: str = "auto",
        device_index: int | None = None,
        progress_callback=None,
        cancel_check=None,
        **_: Any,
    ) -> None:
        self.epsilon = epsilon
        self.steps = steps
        self.step_size = step_size
        self.model_id = model_id
        self.device = device
        self.device_index = device_index
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self._attack = None  # lazy

    def _ensure(self):
        if self._attack is None:
            from . import photoguard  # local import; pulls torch/diffusers

            self._attack = photoguard.build_attack(
                photoguard.PGDConfig(
                    epsilon=self.epsilon,
                    step_size=self.step_size,
                    steps=self.steps,
                    model_id=self.model_id,
                    device=self.device,
                    device_index=self.device_index,
                    progress_callback=self.progress_callback,
                    cancel_check=self.cancel_check,
                )
            )

    def apply(self, image_bgr: np.ndarray) -> np.ndarray:
        self._ensure()
        return self._attack.attack(image_bgr)


_REGISTRY: dict[str, type[Perturber]] = {
    NoopPerturber.name: NoopPerturber,
    GaussianNoisePerturber.name: GaussianNoisePerturber,
    SDEncoderPerturber.name: SDEncoderPerturber,
}


def get(name: str, **kwargs: Any) -> Perturber:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown perturber {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](**kwargs)


def available() -> list[str]:
    return sorted(_REGISTRY)
