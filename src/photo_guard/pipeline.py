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

Layer selection
---------------
``ProtectOptions.layers`` lets the caller pick any non-empty subset of
``{"invisible", "perturb", "visible"}``. The order in which selected
layers run is **always** the canonical one above; the set only decides
which layers are present, never the sequence. This matches AGENTS.md
§二: 处理顺序固定，但用户可以主动放弃某一层（代价是降低整体防护）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import compress, config, perturb, watermark_invisible, watermark_visible


LAYER_INVISIBLE = "invisible"
LAYER_PERTURB = "perturb"
LAYER_VISIBLE = "visible"
ALL_LAYERS: frozenset[str] = frozenset(
    {LAYER_INVISIBLE, LAYER_PERTURB, LAYER_VISIBLE}
)


@dataclass
class ProtectOptions:
    payload: str = config.DEFAULT_PAYLOAD
    perturber: str = config.DEFAULT_PERTURBER
    perturber_kwargs: dict[str, Any] = field(default_factory=dict)
    visible_mode: str = config.DEFAULT_VISIBLE_MODE
    visible_text: str = config.DEFAULT_VISIBLE_TEXT
    visible_alpha: float = config.DEFAULT_VISIBLE_ALPHA
    long_edge: int = config.DEFAULT_LONG_EDGE
    quality: int = config.DEFAULT_JPEG_QUALITY
    # Which layers to apply. Order of execution is fixed (see module
    # docstring); membership only controls presence. Default = all three,
    # i.e. AGENTS.md baseline behaviour.
    layers: frozenset[str] = ALL_LAYERS


def _pil_rgb_to_bgr(image: Image.Image) -> np.ndarray:
    arr = np.array(image.convert("RGB"))
    return arr[:, :, ::-1].copy()  # RGB -> BGR for invisible-watermark / OpenCV


def _bgr_to_pil_rgb(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr[:, :, ::-1].copy(), mode="RGB")


def protect(input_path: Path, output_path: Path, opts: ProtectOptions) -> dict:
    """Run the selected layers in the mandated order and write `output_path`."""
    unknown = set(opts.layers) - ALL_LAYERS
    if unknown:
        raise ValueError(
            f"unknown layer(s) {sorted(unknown)!r}; "
            f"expected subset of {sorted(ALL_LAYERS)!r}"
        )
    if not opts.layers:
        raise ValueError(
            "at least one layer must be enabled "
            f"(any non-empty subset of {sorted(ALL_LAYERS)!r})"
        )

    src = Image.open(input_path)
    src.load()
    src = src.convert("RGB")

    # 0. Resize to the platform spec FIRST (AGENTS.md 五 step 1) — DWT-DCT
    #    is sensitive to resampling, so this must happen before embedding.
    src = compress.fit_long_edge(src, opts.long_edge)

    bgr = _pil_rgb_to_bgr(src)

    # ① invisible watermark — embed into the cleanest available pixels.
    if LAYER_INVISIBLE in opts.layers:
        bgr = watermark_invisible.embed(bgr, opts.payload)

    # ② adversarial perturbation — PhotoGuard SD-encoder attack when
    #    perturber=='sd', else noop / noise placeholders.
    perturber_name: str | None = None
    if LAYER_PERTURB in opts.layers:
        perturber = perturb.get(opts.perturber, **opts.perturber_kwargs)
        bgr = perturber.apply(bgr)
        perturber_name = perturber.name

    rgb = _bgr_to_pil_rgb(bgr)

    # ③ visible watermark — last, on top of the protected pixels.
    if LAYER_VISIBLE in opts.layers:
        final = watermark_visible.apply(
            rgb,
            opts.visible_text,
            mode=opts.visible_mode,
            alpha=opts.visible_alpha,
        )
    else:
        final = rgb

    # Save as JPEG at the chosen quality — this is the post-platform shape.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, format="JPEG", quality=opts.quality, optimize=True)

    return {
        "output": str(output_path),
        "size": final.size,
        "perturber": perturber_name,
        "payload_bytes": (
            len(opts.payload.encode("utf-8"))
            if LAYER_INVISIBLE in opts.layers
            else 0
        ),
        "layers": sorted(opts.layers),
    }


def verify(suspect_path: Path, payload_bytes: int) -> str:
    """Extract the embedded payload from a suspect image."""
    img = Image.open(suspect_path)
    img.load()
    bgr = _pil_rgb_to_bgr(img)
    return watermark_invisible.extract(bgr, payload_bytes)
