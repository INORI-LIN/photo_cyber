"""Offline PhotoGuard-style PGD attack against a Stable Diffusion VAE encoder.

Scope and known deviations, deliberate and recorded for P5:

- ``zero target``: this implements the *encoder-attack* variant only (push the
  encoder latents toward zero). The diffusion attack variant is not implemented,
  and no measured comparison of the two exists.
- The input is the image *after* the invisible layer, so a delivered product carries
  the composed watermark + perturbation; this module never sees the raw source.
- The delivered perturbation is quantized to ``uint8`` (respecting the L-inf budget,
  ±``epsilon``, 8/255 by default) and then written as ``JPEG`` (q85) by the save
  path: the delivered bytes are never the raw PGD tensor, and this code makes no
  claim about how much of it survives that re-encode.
- The visible watermark is composited after the attack and scales the residual by
  roughly (1 - alpha).
- ``fp16`` on CUDA/MPS is untested: byte-level reproducibility is promised for
  CPU/float32 only (P1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import config, device as device_mod


@dataclass
class PGDConfig:
    epsilon: float = config.PHOTOGUARD_EPSILON
    step_size: float = config.PHOTOGUARD_STEP_SIZE
    steps: int = config.PHOTOGUARD_STEPS
    seed: int = config.PHOTOGUARD_SEED
    model_id: str = config.PHOTOGUARD_MODEL_ID
    device: device_mod.Backend = "auto"
    device_index: int | None = None
    progress_callback: Callable[[int, int], None] | None = None
    cancel_check: Callable[[], bool] | None = None


def pad_to_multiple_of_8(rgb: np.ndarray) -> np.ndarray:
    """Pad an ``HxWx3`` float image up to multiples of 8 by repeating its edge pixels.

    The SD VAE downsamples by 8, so both sides must be multiples of 8; the attack crops
    back with ``[:h, :w]`` afterwards, so the original region must stay byte-identical.
    Module-level and torch-free on purpose: the tests call this instead of restating the
    arithmetic (P17).
    """
    pad_h, pad_w = (-rgb.shape[0]) % 8, (-rgb.shape[1]) % 8
    return np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")


class _SDEncoderAttack:
    def __init__(self, cfg: PGDConfig) -> None:
        self.cfg = cfg
        self._vae = None
        self._device = None
        self._dtype = None
        self.device_info = None

    def _load(self):
        try:
            import torch
            from diffusers import AutoencoderKL
        except ImportError as exc:
            raise RuntimeError(
                "PhotoGuard needs the optional `photoguard` extra. "
                "Run `uv sync --extra photoguard`."
            ) from exc

        model_path = Path(self.cfg.model_id)
        if not model_path.is_dir():
            raise RuntimeError(
                f"local SD VAE directory not found at {model_path}. "
                "Run `uv run photo-guard download-models` once."
            )
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        self._torch = torch
        self._device, self._dtype, self.device_info = device_mod.resolve_device(
            self.cfg.device, self.cfg.device_index
        )
        # P15: `use_safetensors=True` refuses a directory whose weights are pickle (`.bin`)
        # instead of silently falling back to `torch.load` — the spike measured diffusers
        # printing "Defaulting to unsafe serialization" and calling torch.load on such a
        # directory. A local directory is a trust boundary: `--perturber-model` accepts any
        # path, so the loader must not execute whatever it finds there. `revision` is a
        # statement of intent for a local directory (it only bites on the download side).
        self._vae = AutoencoderKL.from_pretrained(
            str(model_path), torch_dtype=self._dtype, local_files_only=True,
            use_safetensors=True, revision=config.PHOTOGUARD_REVISION,
        ).to(self._device)
        self._vae.eval()
        for parameter in self._vae.parameters():
            parameter.requires_grad_(False)

    def _ensure_loaded(self):
        if self._vae is None:
            self._load()

    def _initial_noise_generator(self, x_orig):
        """A fresh, seeded ``torch.Generator`` on ``x_orig``'s device (P1).

        Created per :meth:`attack` call on purpose: a generator stored on the instance would
        advance across calls, so the second attack with the same seed would differ. A device
        whose generator API is unsupported (e.g. MPS) falls back to the global RNG — the
        documented cost is that byte-level reproducibility is then not guaranteed.
        """
        try:
            generator = self._torch.Generator(device=x_orig.device)
            generator.manual_seed(int(self.cfg.seed))
            return generator
        except (RuntimeError, TypeError, ValueError):
            return None

    @staticmethod
    def _validate_bgr(image_bgr: np.ndarray) -> None:
        """Cheap input checks (P1 ran them before the model load; P5 extracted them).

        The two messages and the "validation precedes loading" order are pinned by
        ``tests/test_photoguard_shape.py``.
        """
        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            raise ValueError("PhotoGuard expects a three-channel BGR image")
        if image_bgr.shape[0] == 0 or image_bgr.shape[1] == 0:
            raise ValueError("PhotoGuard cannot process an empty image")

    def _to_tensor(self, image_bgr: np.ndarray):
        """BGR uint8 → padded [-1,1] tensor on this attack's device/dtype (P5).

        Pure conversion — no validation, no lazy load — so :meth:`attack` and
        :meth:`latent_norm` share one preprocessing path and keep their own ordering.
        """
        rgb = image_bgr[:, :, ::-1].astype(np.float32) / 255.0
        rgb = pad_to_multiple_of_8(rgb)
        x = self._torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(
            self._device, dtype=self._dtype
        )
        return x * 2.0 - 1.0

    def attack(self, image_bgr: np.ndarray) -> np.ndarray:
        # P1: input validation runs *before* the model load — a bad call must fail fast and
        # cheaply (and the fast-tier bad-input test must not depend on torch being installed).
        self._validate_bgr(image_bgr)

        self._ensure_loaded()
        torch = self._torch

        h, w = image_bgr.shape[:2]
        x_orig = self._to_tensor(image_bgr)

        # The image spans [0,1] but PGD works on [-1,1], so the budget and the step are
        # doubled exactly once here; `delta` is clamped back in that same doubled space.
        eps, step = self.cfg.epsilon * 2.0, self.cfg.step_size * 2.0
        with torch.no_grad():
            target_latent = torch.zeros_like(self._encode_mean(x_orig))
        x_adv = torch.clamp(
            x_orig.clone().detach()
            + torch.empty_like(x_orig).uniform_(
                -eps, eps, generator=self._initial_noise_generator(x_orig)
            ),
            -1.0,
            1.0,
        )
        for iteration in range(self.cfg.steps):
            if self.cfg.cancel_check and self.cfg.cancel_check():
                raise InterruptedError("PhotoGuard operation cancelled")
            x_adv = x_adv.detach().requires_grad_(True)
            latent = self._encode_mean(x_adv)
            loss = torch.nn.functional.mse_loss(latent, target_latent)
            grad = torch.autograd.grad(loss, x_adv)[0]
            with torch.no_grad():
                x_adv = x_adv - step * grad.sign()
                delta = torch.clamp(x_adv - x_orig, -eps, eps)
                x_adv = torch.clamp(x_orig + delta, -1.0, 1.0)
            if self.cfg.progress_callback:
                self.cfg.progress_callback(iteration + 1, self.cfg.steps)

        out = (x_adv.detach().float() + 1.0) / 2.0
        out = out.clamp(0.0, 1.0).squeeze(0).permute(1, 2, 0).cpu().numpy()
        out = out[:h, :w]
        return ((out * 255.0 + 0.5).astype(np.uint8))[:, :, ::-1].copy()

    def latent_norm(self, image_bgr: np.ndarray) -> float:
        """L2 norm of the encoder's mean latent for ``image_bgr`` (P5).

        The retention measurement applies this to the clean and the perturbed product;
        it shares :meth:`_to_tensor` with :meth:`attack` so both see identical
        preprocessing. Validation runs before the load (P1), and the reduction is
        no-grad and cast to float32 first so fp16 devices cannot overflow it into
        ``inf`` (CPU is a no-op).
        """
        self._validate_bgr(image_bgr)
        self._ensure_loaded()
        with self._torch.no_grad():
            latent = self._encode_mean(self._to_tensor(image_bgr))
            return float(latent.float().norm())

    def _encode_mean(self, x):
        return self._vae.encode(x).latent_dist.mean


def build_attack(cfg: PGDConfig | None = None) -> _SDEncoderAttack:
    return _SDEncoderAttack(cfg or PGDConfig())
