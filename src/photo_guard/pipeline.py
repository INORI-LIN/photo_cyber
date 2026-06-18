"""Pipeline: enforces AGENTS.md ordering.

二 节 — among the three protection layers, order is fixed: ① invisible →
② perturb → ③ visible.

五 节 checklist — resize to platform spec is step 1, BEFORE embedding the
invisible watermark, because DWT-DCT survives JPEG re-compression but is
sensitive to geometric resampling (the DCT block grid moves). Final JPEG
encoding happens at save time so the artifact is already in its post-platform
shape (四 节: 「自己先按平台规格压一遍再处理」).

So the concrete order is:
    load → fit_long_edge → ① embed → ② perturb → ③ visible → save JPEG
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import compress, config, perturb, watermark_invisible, watermark_visible


@dataclass
class ProtectOptions:
    payload: str = config.DEFAULT_PAYLOAD
    perturber: str = config.DEFAULT_PERTURBER
    visible_mode: str = config.DEFAULT_VISIBLE_MODE
    visible_text: str = config.DEFAULT_VISIBLE_TEXT
    visible_alpha: float = config.DEFAULT_VISIBLE_ALPHA
    long_edge: int = config.DEFAULT_LONG_EDGE
    quality: int = config.DEFAULT_JPEG_QUALITY


def _pil_rgb_to_bgr(image: Image.Image) -> np.ndarray:
    arr = np.array(image.convert("RGB"))
    return arr[:, :, ::-1].copy()  # RGB -> BGR for invisible-watermark / OpenCV


def _bgr_to_pil_rgb(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr[:, :, ::-1].copy(), mode="RGB")


def protect(input_path: Path, output_path: Path, opts: ProtectOptions) -> dict:
    """Run all three layers in the mandated order and write `output_path`."""
    src = Image.open(input_path)
    src.load()
    src = src.convert("RGB")

    # 0. Resize to the platform spec FIRST (AGENTS.md 五 step 1) — DWT-DCT
    #    is sensitive to resampling, so this must happen before embedding.
    src = compress.fit_long_edge(src, opts.long_edge)

    # ① invisible watermark — embed into the cleanest available pixels.
    bgr = _pil_rgb_to_bgr(src)
    bgr = watermark_invisible.embed(bgr, opts.payload)

    # ② adversarial perturbation — placeholder slot per AGENTS.md 三②.
    perturber = perturb.get(opts.perturber)
    bgr = perturber.apply(bgr)

    rgb = _bgr_to_pil_rgb(bgr)

    # ③ visible watermark — last, on top of the protected pixels.
    final = watermark_visible.apply(
        rgb,
        opts.visible_text,
        mode=opts.visible_mode,
        alpha=opts.visible_alpha,
    )

    # Save as JPEG at the chosen quality — this is the post-platform shape.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, format="JPEG", quality=opts.quality, optimize=True)

    return {
        "output": str(output_path),
        "size": final.size,
        "perturber": perturber.name,
        "payload_bytes": len(opts.payload.encode("utf-8")),
    }


def verify(suspect_path: Path, payload_bytes: int) -> str:
    """Extract the embedded payload from a suspect image."""
    img = Image.open(suspect_path)
    img.load()
    bgr = _pil_rgb_to_bgr(img)
    return watermark_invisible.extract(bgr, payload_bytes)
