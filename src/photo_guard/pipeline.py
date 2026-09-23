"""Canonical pipeline: resize → invisible → perturb → visible → JPEG."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import compress, config, outputs, perturb, watermark_invisible, watermark_visible

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


def _same_file(first: Path, second: Path) -> bool:
    """True when the two paths denote the same file on disk.

    ``samefile`` needs both names to exist, so a not-yet-created output falls back to a
    normalised realpath comparison. Windows path casing is folded by ``normcase``.
    """
    if first.exists() and second.exists():
        try:
            return first.samefile(second)
        except OSError:
            pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(
        os.path.realpath(second)
    )


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
    # AGENTS.md §五 wants the original kept for archival; writing the product over it is
    # the one mistake here that cannot be undone, so it is refused rather than warned about.
    if _same_file(input_path, output_path):
        raise ValueError(
            "refusing to overwrite the input file; choose a different output path"
        )
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
    outputs.save_image_atomic(final, output_path, quality=opts.quality)
    return {
        "output": str(output_path),
        "size": final.size,
        "perturber": perturber_name,
        "payload_bytes": len(stored_payload.encode("utf-8")) if LAYER_INVISIBLE in opts.layers else 0,
        "payload_envelope": bool(opts.payload_envelope and LAYER_INVISIBLE in opts.layers),
        "layers": sorted(opts.layers),
    }


def verify_legacy(suspect_path: Path, payload_bytes: int) -> watermark_invisible.LegacyExtraction:
    """Decode a checksum-less payload as a clue, with its advisory metrics.

    The read is inline rather than a shared loader on purpose: P8 lands the single
    ``_load_oriented_rgb`` helper in the next batch and will consolidate these call sites.
    """
    with Image.open(suspect_path) as image:
        image.load()
        bgr = _pil_rgb_to_bgr(image)
    return watermark_invisible.extract_legacy(bgr, payload_bytes)


def verify(suspect_path: Path, payload_bytes: int) -> str:
    """Text view of :func:`verify_legacy`; raises ``NoPayloadError`` on garbage."""
    return verify_legacy(suspect_path, payload_bytes).text


def discover_payload(suspect_path: Path, max_bytes: int | None = None) -> str:
    """Blind search for a CRC-protected envelope: no prior knowledge required."""
    with Image.open(suspect_path) as image:
        image.load()
        bgr = _pil_rgb_to_bgr(image)
    found = watermark_invisible.find_envelope(bgr, max_bytes)
    if found is None:
        raise watermark_invisible.NoPayloadError("no photo-guard envelope found")
    return found[0]


def verify_expected(suspect_path: Path, expected_payload: str) -> dict:
    """Verify a CRC-protected payload.

    ``extract_envelope`` raises ``IntegrityUncertainError`` when an envelope-shaped decode
    fails its CRC32 — reported as uncertain rather than mismatched, because chroma clipping
    can flip bits at the correct length (spike P3-B).
    """
    size = watermark_invisible.packed_size(expected_payload)
    with Image.open(suspect_path) as image:
        image.load()
        bgr = _pil_rgb_to_bgr(image)
    payload = watermark_invisible.extract_envelope(bgr, size)
    if payload != expected_payload:
        raise ValueError("watermark payload does not match the expected payload")
    return {"payload": payload, "verified": True, "payload_bytes": size}
