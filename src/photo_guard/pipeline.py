"""Canonical pipeline: load (decode + orientation + strip EXIF + keep ICC) → resize →
invisible → perturb → visible → JPEG."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

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


_HEIC_SUFFIXES = (".heic", ".heif", ".avif")


def _validate_input(image: Image.Image, path: Path) -> None:
    """Refuse contract-breaking inputs — every check runs before ``.load()`` (G4).

    Order inside the loader: format → pixel ceiling → frame count. The ceiling uses the
    pre-draft ``image.size``, so a JPEG cannot be silently downsampled past the check.
    """
    if image.format not in config.SUPPORTED_INPUT_FORMATS:
        raise ValueError(
            f"unsupported input format {image.format!r} "
            f"(supported: {', '.join(config.SUPPORTED_INPUT_FORMATS)}): {path}"
        )
    width, height = image.size
    if width * height > config.MAX_INPUT_PIXELS:
        raise ValueError(
            f"input has {width * height} pixels, above the {config.MAX_INPUT_PIXELS}-pixel "
            f"limit: {path}"
        )
    frames = getattr(image, "n_frames", 1)
    if frames > 1:
        raise ValueError(
            f"input has {frames} frames; only single-frame images are supported: {path}"
        )


def _rgb_on_matte(image: Image.Image) -> Image.Image:
    """Flatten transparency onto the configured matte, then convert to RGB (G4).

    ``convert("RGB")`` alone would keep the RGB values hidden under alpha=0 — or under a
    P-mode transparency index — and copy them straight into the protected output.
    """
    if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (*config.ALPHA_MATTE, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _load_oriented_rgb(
    path: Path, *, draft_long_edge: int | None = None
) -> tuple[Image.Image, bytes | None]:
    """The single image loader: decode, contract guards, orientation, EXIF strip, ICC.

    Body order is load-bearing (P8/G4 binding, do not reorder):
    ``Image.open`` → :func:`_validate_input` → fresh EXIF re-parse → JPEG ``draft`` →
    ``.load()`` → ICC → orient+matte. The guards must run before ``.load()`` so the full
    pixel budget is never spent on a refused input; ``draft`` must sit after the guards
    (its size comes from the pre-draft dimensions) and before ``.load()``.

    The EXIF re-parse is deliberate: while opening a JPEG, Pillow swallows a corrupt
    EXIF ``SyntaxError`` and caches an empty Exif, so ``image.getexif()`` can no longer
    fail — only a fresh ``Image.Exif().load()`` sees corruption. Missing EXIF (``None``)
    is not corrupt and passes through untouched.
    """
    try:
        opened = Image.open(path)
    except Image.DecompressionBombError as exc:
        raise ValueError(
            f"input is too large to decode (limit: {config.MAX_INPUT_PIXELS} pixels): {path}"
        ) from exc
    except (OSError, SyntaxError) as exc:
        hint = ""
        if path.suffix.lower() in _HEIC_SUFFIXES or any(
            token in str(exc).upper() for token in ("HEIC", "HEIF", "AVIF")
        ):
            hint = " (HEIC/HEIF is not supported; convert the photo to JPEG or PNG first)"
        raise ValueError(f"cannot read {path}: {exc}{hint}") from exc
    with opened:
        _validate_input(opened, path)
        raw_exif = opened.info.get("exif")
        if raw_exif:
            try:
                Image.Exif().load(raw_exif)
            except (SyntaxError, OSError, ValueError) as exc:
                raise ValueError(f"input EXIF metadata is unreadable ({exc}): {path}") from exc
        if draft_long_edge:
            # 0 keeps the original size (README §参数表); draft((0, 0)) would divide by zero.
            opened.draft("RGB", (draft_long_edge, draft_long_edge))
        opened.load()
        icc = opened.info.get("icc_profile")
        rgb = _rgb_on_matte(ImageOps.exif_transpose(opened))
    # convert()/transpose() copy ``info``; strip the metadata the product must not carry
    # (GPS/XMP) instead of relying on the later numpy round trip to drop it by accident.
    for key in ("exif", "xmp"):
        rgb.info.pop(key, None)
    return rgb, icc


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


def validate_capacity(stored_bytes: int, height: int, width: int) -> None:
    """P4 write-side gate: the pixel floor first, then the structural ceiling.

    The ceiling is :func:`watermark_invisible.max_stored_bytes` — a "cannot possibly fit"
    bound, **not** a reliability threshold. The 448-cell measurement (docs/fix-plan.md §6 P4
    / §10.14) showed no ``blocks/bit`` threshold is monotone and every one of them rejects
    legal products, so reliability belongs to the post-write self-check in :func:`protect`.
    Runs on the **post-resize** dimensions — that is why it lives here rather than in
    ``validate_options`` (which never sees the resized size).
    """
    if height * width < config.WATERMARK_MIN_IMAGE_PIXELS:
        raise ValueError(
            f"image too small for the invisible layer: {height * width} pixels < "
            f"{config.WATERMARK_MIN_IMAGE_PIXELS} (256x256 = 65536); use a larger image "
            f"or drop the invisible layer"
        )
    limit = watermark_invisible.max_stored_bytes(height, width)
    if stored_bytes > limit:
        raise ValueError(
            f"payload cannot be carried: this image can carry at most {limit} stored bytes "
            f"({height}x{width}); shorten --payload or raise --long-edge"
        )


def _verify_output(
    temp_path: Path, expected_payload: str, *, envelope: bool, destination: Path
) -> None:
    """Re-read the freshly written product and require exact recovery (P4).

    Runs on the temp file before ``os.replace`` (M-A), so a failure leaves no product and
    cannot damage a previous one. Raw payloads go through
    :func:`watermark_invisible.extract` **byte-exact** — deliberately not through
    ``verify``, whose ``is_recoverable_text`` filter rejects legal periodic payloads such as
    ``abab`` and would turn honest products into exit 2. ``destination`` only names the
    wanted output in the failure message (the temp name alone would be unhelpful).
    """
    image, _ = _load_oriented_rgb(temp_path)
    bgr = _pil_rgb_to_bgr(image)
    try:
        if envelope:
            stored = watermark_invisible.pack_payload(expected_payload)
            recovered = watermark_invisible.extract_envelope(bgr, len(stored.encode("utf-8")))
        else:
            recovered = watermark_invisible.extract(bgr, len(expected_payload.encode("utf-8")))
    except ValueError as exc:
        # A reader that cannot see the carrier raises here; keep the self-check wording so
        # the failure is attributable to the product, with the underlying reason attached.
        raise ValueError(
            f"self-check failed: the written product cannot be read back ({exc}): {destination}"
        ) from exc
    if recovered != expected_payload:
        raise ValueError(
            f"self-check failed: the written product does not return the payload "
            f"({destination}); the image content may be too flat or too small for the "
            f"invisible layer"
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
    # P29: the second gate for programmatic callers — the GUI widget path cannot smuggle an
    # unknown mode through (non-editable combo), but ``ProtectOptions`` can. Conditional on
    # the layer for the same reason as the text check above: an unused mode is not an error.
    if LAYER_VISIBLE in opts.layers and opts.visible_mode not in config.VISIBLE_MODES:
        raise ValueError(
            f"unknown visible mode {opts.visible_mode!r}; "
            f"expected one of {', '.join(config.VISIBLE_MODES)}"
        )
    # P30: only reject `noop` when there is no instance to fall back on — `protect` uses a
    # caller-supplied instance in preference to the factory, so the old unconditional check
    # rejected combinations it actually handles.
    if (
        LAYER_PERTURB in opts.layers
        and opts.perturber_instance is None
        and opts.perturber == "noop"
    ):
        raise ValueError("perturb layer uses noop; choose noise or sd, or disable the layer")


def protect(input_path: Path, output_path: Path, opts: ProtectOptions) -> dict:
    validate_options(opts)
    # AGENTS.md §五 wants the original kept for archival; writing the product over it is
    # the one mistake here that cannot be undone, so it is refused rather than warned about.
    if _same_file(input_path, output_path):
        raise ValueError(
            "refusing to overwrite the input file; choose a different output path"
        )
    # P28: `os.replace` onto a directory would only fail at the very end of the pipeline
    # (after resize/embed and, for the SD perturber, a full PGD run). Refuse it up front —
    # this is the shared contract point for the CLI, the GUI and programmatic callers.
    if output_path.is_dir():
        raise ValueError(f"output path is a directory: {output_path}")
    src, icc = _load_oriented_rgb(input_path, draft_long_edge=opts.long_edge)
    src = compress.fit_long_edge(src, opts.long_edge)
    bgr = _pil_rgb_to_bgr(src)

    stored_payload = opts.payload
    if LAYER_INVISIBLE in opts.layers:
        if opts.payload_envelope:
            stored_payload = watermark_invisible.pack_payload(opts.payload)
        validate_capacity(len(stored_payload.encode("utf-8")), bgr.shape[0], bgr.shape[1])
        bgr = watermark_invisible.embed(bgr, stored_payload)

    perturber_name = None
    if LAYER_PERTURB in opts.layers:
        # P30: `is not None`, not truthiness — a falsy instance must be used as given, not
        # silently replaced by the factory (which would report success with zero perturbation).
        selected = (
            opts.perturber_instance
            if opts.perturber_instance is not None
            else perturb.get(opts.perturber, **opts.perturber_kwargs)
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
    verify = None
    if LAYER_INVISIBLE in opts.layers:
        # P4/M-A: verify the temp bytes before the swap, so a failed check leaves neither a
        # product nor damage to a previous one.
        verify = lambda path: _verify_output(  # noqa: E731 - one-line closure over opts
            path, opts.payload, envelope=opts.payload_envelope, destination=output_path
        )
    outputs.save_image_atomic(
        final, output_path, quality=opts.quality, icc_profile=icc, verify=verify
    )
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

    Reads through the shared :func:`_load_oriented_rgb` loader (P8), so the input contract
    and the display-orientation interpretation are the same as ``protect``.
    """
    bgr = _pil_rgb_to_bgr(_load_oriented_rgb(suspect_path)[0])
    return watermark_invisible.extract_legacy(bgr, payload_bytes)


def verify(suspect_path: Path, payload_bytes: int) -> str:
    """Text view of :func:`verify_legacy`; raises ``NoPayloadError`` on garbage.

    Test-only thin wrapper (P32): no production caller — the CLI uses ``verify_legacy`` for
    the clue path and ``discover_payload``/``verify_expected`` for evidence. Kept because
    the round-trip tests read the recovered text through it.
    """
    return verify_legacy(suspect_path, payload_bytes).text


def discover_payload(suspect_path: Path, max_bytes: int | None = None) -> str:
    """Blind search for a CRC-protected envelope: no prior knowledge required."""
    bgr = _pil_rgb_to_bgr(_load_oriented_rgb(suspect_path)[0])
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
    bgr = _pil_rgb_to_bgr(_load_oriented_rgb(suspect_path)[0])
    payload = watermark_invisible.extract_envelope(bgr, size)
    if payload != expected_payload:
        raise ValueError("watermark payload does not match the expected payload")
    return {"payload": payload, "verified": True, "payload_bytes": size}
