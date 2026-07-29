"""Canonical pipeline: resize → invisible → perturb → visible → JPEG."""
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
ALL_LAYERS = frozenset({LAYER_INVISIBLE, LAYER_PERTURB, LAYER_VISIBLE})
DEFAULT_LAYERS = frozenset({LAYER_INVISIBLE, LAYER_VISIBLE})


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
    layers: frozenset[str] = DEFAULT_LAYERS
    payload_envelope: bool = False
    perturber_instance: Any | None = None


def _pil_rgb_to_bgr(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))[:, :, ::-1].copy()


def _bgr_to_pil_rgb(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr[:, :, ::-1].copy(), mode="RGB")


def validate_options(opts: ProtectOptions) -> None:
    unknown = set(opts.layers) - ALL_LAYERS
    if unknown:
        raise ValueError(f"unknown layer(s) {sorted(unknown)!r}")
    if not opts.layers:
        raise ValueError("at least one layer must be enabled")
    if opts.long_edge < 0:
        raise ValueError("long_edge must be zero or positive")
    if not 1 <= opts.quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    if not 0.0 <= opts.visible_alpha <= 1.0:
        raise ValueError("visible watermark alpha must be between 0 and 1")
    if LAYER_INVISIBLE in opts.layers and not opts.payload:
        raise ValueError("invisible watermark payload must not be empty")
    if LAYER_VISIBLE in opts.layers and not opts.visible_text:
        raise ValueError("visible watermark text must not be empty")
    if LAYER_PERTURB in opts.layers and opts.perturber == "noop":
        raise ValueError("perturb layer uses noop; choose noise or sd, or disable the layer")


def protect(input_path: Path, output_path: Path, opts: ProtectOptions) -> dict:
    validate_options(opts)
    with Image.open(input_path) as opened:
        opened.load()
        src = opened.convert("RGB")
    src = compress.fit_long_edge(src, opts.long_edge)
    bgr = _pil_rgb_to_bgr(src)

    stored_payload = opts.payload
    if LAYER_INVISIBLE in opts.layers:
        if opts.payload_envelope:
            stored_payload = watermark_invisible.pack_payload(opts.payload)
        bgr = watermark_invisible.embed(bgr, stored_payload)

    perturber_name = None
    if LAYER_PERTURB in opts.layers:
        selected = opts.perturber_instance or perturb.get(
            opts.perturber, **opts.perturber_kwargs
        )
        bgr = selected.apply(bgr)
        perturber_name = selected.name

    rgb = _bgr_to_pil_rgb(bgr)
    final = (
        watermark_visible.apply(
            rgb, opts.visible_text, mode=opts.visible_mode, alpha=opts.visible_alpha
        )
        if LAYER_VISIBLE in opts.layers
        else rgb
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, format="JPEG", quality=opts.quality, optimize=True)
    return {
        "output": str(output_path),
        "size": final.size,
        "perturber": perturber_name,
        "payload_bytes": len(stored_payload.encode("utf-8")) if LAYER_INVISIBLE in opts.layers else 0,
        "payload_envelope": bool(opts.payload_envelope and LAYER_INVISIBLE in opts.layers),
        "layers": sorted(opts.layers),
    }


def verify(suspect_path: Path, payload_bytes: int) -> str:
    with Image.open(suspect_path) as image:
        image.load()
        bgr = _pil_rgb_to_bgr(image)
    return watermark_invisible.extract(bgr, payload_bytes)


def verify_expected(suspect_path: Path, expected_payload: str) -> dict:
    size = watermark_invisible.packed_size(expected_payload)
    stored = verify(suspect_path, size)
    payload, verified = watermark_invisible.unpack_payload(stored)
    if not verified or payload != expected_payload:
        raise ValueError("watermark payload does not match or failed integrity check")
    return {"payload": payload, "verified": True, "payload_bytes": size}
