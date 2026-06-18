"""SD-encoder PGD attack — PhotoGuard's "encoder" variant (AGENTS.md 三②).

Why this is the right algorithm
-------------------------------
PhotoGuard's published recipe attacks the *VAE encoder* of a Stable Diffusion
stack so any subsequent edit (img2img / inpainting / 换脸 / 去水印 — they all
re-encode through the same VAE) lands on a degenerate latent and the decoded
output collapses. Targeting just the VAE keeps memory under 1 GB and avoids
loading the UNet / text encoder.

Implementation notes
--------------------
- Loads `stabilityai/sd-vae-ft-mse` lazily on first `apply()` call.
- PGD with sign-of-gradient steps + L∞ projection (eps in 0..1 image space).
- Loss: ‖encode(x_adv).mean - target_latent‖₂². `target_latent` is a fixed
  zero tensor — the simplest "send everything to a bad latent" objective.
  AGENTS.md 三② only commits to making downstream re-edits "崩坏", not to a
  particular target image, so zero-latent is sufficient.
- Auto device: CUDA if available, else CPU (slow but functional, ~30s for
  10 steps at 512×512 on a modern CPU).
- 8-pixel multiple cropping handled internally so VAE strides line up.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


_DEFAULT_MODEL_ID = "stabilityai/sd-vae-ft-mse"


@dataclass
class PGDConfig:
    epsilon: float = 8.0 / 255.0  # max L∞ pixel perturbation
    step_size: float = 2.0 / 255.0
    steps: int = 10
    model_id: str = _DEFAULT_MODEL_ID


class _SDEncoderAttack:
    """Holds the lazily-loaded VAE; reused across multiple apply() calls."""

    def __init__(self, cfg: PGDConfig) -> None:
        self.cfg = cfg
        self._vae = None
        self._device = None
        self._dtype = None

    def _load(self):
        try:
            import torch
            from diffusers import AutoencoderKL
        except ImportError as exc:  # diffusers not installed
            raise RuntimeError(
                "PhotoGuard SD-encoder perturber needs the optional "
                "`photoguard` extra. Install it with: "
                "`uv sync --extra photoguard`"
            ) from exc

        self._torch = torch
        self._device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        # fp16 only on CUDA; CPU keeps fp32 (numerical stability + speed).
        self._dtype = (
            torch.float16 if self._device.type == "cuda" else torch.float32
        )
        self._vae = AutoencoderKL.from_pretrained(
            self.cfg.model_id, torch_dtype=self._dtype
        ).to(self._device)
        self._vae.eval()
        for p in self._vae.parameters():
            p.requires_grad_(False)

    def _ensure_loaded(self):
        if self._vae is None:
            self._load()

    def attack(self, image_bgr: np.ndarray) -> np.ndarray:
        """Run PGD on one image; returns BGR uint8 same shape (modulo crop)."""
        self._ensure_loaded()
        torch = self._torch

        # BGR uint8 -> RGB float [-1, 1] tensor; crop to 8-multiple
        rgb = image_bgr[:, :, ::-1].astype(np.float32) / 255.0
        h, w = rgb.shape[:2]
        h8, w8 = (h // 8) * 8, (w // 8) * 8
        rgb = rgb[:h8, :w8]
        x_orig = (
            torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(
                self._device, dtype=self._dtype
            )
        )
        x_orig = x_orig * 2.0 - 1.0  # [-1, 1] (SD VAE convention)

        eps = self.cfg.epsilon * 2.0  # in [-1,1] space → 2× pixel ε
        step = self.cfg.step_size * 2.0

        with torch.no_grad():
            target_latent = torch.zeros_like(self._encode_mean(x_orig))

        x_adv = x_orig.clone().detach()
        # Random init inside the L∞ ball helps PGD escape flat regions.
        x_adv = x_adv + torch.empty_like(x_adv).uniform_(-eps, eps)
        x_adv = torch.clamp(x_adv, -1.0, 1.0)

        for _ in range(self.cfg.steps):
            x_adv = x_adv.detach().requires_grad_(True)
            latent = self._encode_mean(x_adv)
            loss = torch.nn.functional.mse_loss(latent, target_latent)
            grad = torch.autograd.grad(loss, x_adv)[0]
            with torch.no_grad():
                x_adv = x_adv - step * grad.sign()  # minimise distance to 0
                # project back into L∞ ball around x_orig
                delta = torch.clamp(x_adv - x_orig, -eps, eps)
                x_adv = torch.clamp(x_orig + delta, -1.0, 1.0)

        out = (x_adv.detach().float() + 1.0) / 2.0
        out = out.clamp(0.0, 1.0).squeeze(0).permute(1, 2, 0).cpu().numpy()
        out_uint8 = (out * 255.0 + 0.5).astype(np.uint8)
        return out_uint8[:, :, ::-1].copy()  # back to BGR

    def _encode_mean(self, x):
        # AutoencoderKL.encode returns AutoencoderKLOutput with .latent_dist
        return self._vae.encode(x).latent_dist.mean


def build_attack(cfg: PGDConfig | None = None) -> _SDEncoderAttack:
    return _SDEncoderAttack(cfg or PGDConfig())
