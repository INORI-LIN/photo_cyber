"""Layer ② — adversarial perturbation (AGENTS.md 三②, 预留接入位).

Defines the `Perturber` interface so a future PhotoGuard / SD-encoder attack
can drop in without touching the pipeline. Two stub implementations are
provided today:

- NoopPerturber: identity, default — keeps the slot reserved as the doc says.
- GaussianNoisePerturber: ε-bounded noise, lightweight placeholder showing
  the layer is wired up end-to-end.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

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

    def __init__(self, epsilon: float = config.NOISE_EPSILON, seed: int = 0) -> None:
        self.epsilon = epsilon
        self._rng = np.random.default_rng(seed)

    def apply(self, image_bgr: np.ndarray) -> np.ndarray:
        scale = self.epsilon * 255.0
        noise = self._rng.normal(0.0, scale, size=image_bgr.shape)
        out = image_bgr.astype(np.float32) + noise
        return np.clip(out, 0, 255).astype(np.uint8)


_REGISTRY: dict[str, type[Perturber]] = {
    NoopPerturber.name: NoopPerturber,
    GaussianNoisePerturber.name: GaussianNoisePerturber,
}


def get(name: str) -> Perturber:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown perturber {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def available() -> list[str]:
    return sorted(_REGISTRY)
