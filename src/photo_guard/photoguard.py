"""Offline PhotoGuard-style PGD attack against a Stable Diffusion VAE encoder."""
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
    model_id: str = config.PHOTOGUARD_MODEL_ID
    device: device_mod.Backend = "auto"
    device_index: int | None = None
    progress_callback: Callable[[int, int], None] | None = None
    cancel_check: Callable[[], bool] | None = None


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
        self._vae = AutoencoderKL.from_pretrained(
            str(model_path), torch_dtype=self._dtype, local_files_only=True
        ).to(self._device)
        self._vae.eval()
        for parameter in self._vae.parameters():
            parameter.requires_grad_(False)

    def _ensure_loaded(self):
        if self._vae is None:
            self._load()

    def attack(self, image_bgr: np.ndarray) -> np.ndarray:
        self._ensure_loaded()
        torch = self._torch
        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            raise ValueError("PhotoGuard expects a three-channel BGR image")

        rgb = image_bgr[:, :, ::-1].astype(np.float32) / 255.0
        h, w = rgb.shape[:2]
        if h == 0 or w == 0:
            raise ValueError("PhotoGuard cannot process an empty image")
        pad_h, pad_w = (-h) % 8, (-w) % 8
        rgb = np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        x_orig = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(
            self._device, dtype=self._dtype
        )
        x_orig = x_orig * 2.0 - 1.0

        eps, step = self.cfg.epsilon * 2.0, self.cfg.step_size * 2.0
        with torch.no_grad():
            target_latent = torch.zeros_like(self._encode_mean(x_orig))
        x_adv = torch.clamp(
            x_orig.clone().detach() + torch.empty_like(x_orig).uniform_(-eps, eps),
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

    def _encode_mean(self, x):
        return self._vae.encode(x).latent_dist.mean


def build_attack(cfg: PGDConfig | None = None) -> _SDEncoderAttack:
    return _SDEncoderAttack(cfg or PGDConfig())
