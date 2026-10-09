"""Efficacy matrix benchmark (P6).

The fast tier locks *decisions*; this script measures the two promises that had no numbers:

* the invisible watermark survives the platform-style re-encode chain (``pass`` per cell,
  decided by the CRC envelope — the same authority ``verify`` uses), and
* how much of the PhotoGuard perturbation survives that chain (``rms_ratio`` /
  ``linf_ratio`` — the fraction of the *perturbation* left, never a "protection strength").

Run (core environment; no torch/diffusers needed for ``noise``)::

    uv run python bench/efficacy_matrix.py --out-dir /tmp/pg-bench --perturber noise

Artifacts land in ``--out-dir``: ``cells.csv``, ``retention.csv``, ``summary.md``.
Exit codes: 0 = pinned rows 100% and all self-checks hold; 1 = a pinned row below 100% or
the negative control false-positived; 2 = unusable environment (missing SD model, webp
unavailable, image below the 256x256 floor).

Column names are frozen; ``bench/README.md`` is the contract (P5 consumes both).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from photo_guard import compress, config, perturb, pipeline, watermark_invisible

IMAGES = ("textured_detail", "portrait_like", "smooth_lowtex")
PINNED = frozenset({("textured_detail", "identity"), ("textured_detail", "jpeg_q85")})
DEFAULT_PAYLOAD = "0123456789abcdef"  # 16 bytes -> 37 stored -> 296 bit

CELLS_HEADER = (
    "image", "cell", "ops", "artifact_subsampling", "stored_payload_bytes", "bits",
    "blocks_per_bit", "carrier_channel", "carrier_scale", "fixture_sha256", "fixture_w",
    "fixture_h", "pass", "crc_ok", "payload_match",
)
RETENTION_HEADER = ("image", "cell", "rms_ratio", "linf_ratio")


@dataclass(frozen=True)
class Cell:
    name: str
    ops: tuple[tuple, ...] = ()


# 12 cells; S2 measured webp available so the webp cell stays (fix-plan §10.14).
CELLS: tuple[Cell, ...] = (
    Cell("identity"),
    Cell("jpeg_q90", (("jpeg", 90),)),
    Cell("jpeg_q95", (("jpeg", 95),)),
    Cell("jpeg_q85", (("jpeg", 85),)),
    Cell("jpeg_q75", (("jpeg", 75),)),
    Cell("jpeg_q60", (("jpeg", 60),)),
    Cell("jpeg_q50", (("jpeg", 50),)),
    Cell("q75_x2", (("jpeg", 75), ("jpeg", 75))),
    Cell("webp_q80", (("webp", 80),)),
    Cell("downscale_720", (("scale_long", 720),)),
    Cell("downscale_720_back_1080", (("scale_long", 720), ("scale_to", 1080))),
    Cell("combo_repost", (("scale_long", 720), ("jpeg", 75), ("jpeg", 85))),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic(name: str) -> Image.Image:
    """Deterministic synthetic corpus (no repo images: the bench must not import tests)."""
    rng = np.random.default_rng({"textured_detail": 41, "portrait_like": 42, "smooth_lowtex": 43}[name])
    height, width = 810, 1080
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    if name == "textured_detail":
        arr = rng.integers(40, 210, (height, width, 3), dtype=np.uint8)
    elif name == "portrait_like":
        base = 110 + 60 * np.sin(xx / 90.0) * np.cos(yy / 70.0)
        arr = np.stack([base + 18, base, base - 16], axis=-1).astype(np.uint8)
        blob = ((xx - width * 0.5) ** 2 + (yy - height * 0.42) ** 2) < (120 ** 2)
        arr[blob] = (arr[blob].astype(np.int16) + 25).clip(0, 255).astype(np.uint8)
    else:  # smooth_lowtex
        base = 120 + 35 * np.sin(xx / 260.0) + 25 * np.cos(yy / 210.0)
        arr = np.stack([base, base + 6, base + 12], axis=-1).astype(np.uint8)
    image = Image.fromarray(arr, "RGB")
    return compress.fit_long_edge(image, config.DEFAULT_LONG_EDGE)


def _apply_ops(image: Image.Image, cell: Cell) -> Image.Image:
    for op in cell.ops:
        kind = op[0]
        if kind in {"jpeg", "webp", "png"}:
            buffer = io.BytesIO()
            if kind == "jpeg":
                image.convert("RGB").save(
                    buffer, format="JPEG", quality=op[1], subsampling=2, optimize=True
                )
            elif kind == "webp":
                image.convert("RGB").save(buffer, format="WEBP", quality=op[1], method=4)
            else:
                image.convert("RGB").save(buffer, format="PNG")
            buffer.seek(0)
            with Image.open(buffer) as reloaded:
                image = reloaded.convert("RGB")
        elif kind == "scale_long":
            image = compress.fit_long_edge(image, op[1])
        elif kind == "scale_to":
            width, height = image.size
            scale = op[1] / max(width, height)
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS
            )
        else:  # pragma: no cover - guarded by the frozen CELLS table
            raise ValueError(f"unknown op {kind!r}")
    return image


def _subsampling_of(path: Path) -> str:
    with Image.open(path) as image:
        layer = image.layer
    return str(tuple(layer)) if layer else "n/a"


def _decode_check(path: Path, payload: str) -> tuple[bool, bool]:
    """(crc_ok, payload_match) through the envelope authority ``verify`` uses."""
    image, _ = pipeline._load_oriented_rgb(path)
    bgr = pipeline._pil_rgb_to_bgr(image)
    stored = watermark_invisible.pack_payload(payload)
    try:
        recovered = watermark_invisible.extract_envelope(bgr, len(stored.encode("utf-8")))
    except ValueError:
        return False, False
    return True, recovered == payload


def _options(payload: str, *, layers: frozenset[str], perturber: str) -> pipeline.ProtectOptions:
    return pipeline.ProtectOptions(
        payload=payload, payload_envelope=True, layers=layers,
        perturber=perturber if "perturb" in layers else "noop",
    )


def _expected_long_edge(cell: Cell) -> int:
    """The long edge the cell's ops must land on (P6 step 3: mismatch is exit 2)."""
    edge = config.DEFAULT_LONG_EDGE
    for op in cell.ops:
        if op[0] == "scale_long":
            edge = op[1]
        elif op[0] == "scale_to":
            edge = op[1]
    return edge


def _rms(arr: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(arr.astype(np.float64)))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="efficacy_matrix.py", description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--perturber", choices=["noise", "sd"], default="noise")
    parser.add_argument("--payload", default=DEFAULT_PAYLOAD)
    parser.add_argument("--images-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    from PIL import features

    if not features.check("webp"):
        print("webp support is missing from this Pillow build", file=sys.stderr)
        return 2

    if args.images_dir is not None:
        sources = {}
        for path in sorted(args.images_dir.iterdir()):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
                sources[path.stem] = path
        if not sources:
            print(f"no images found in {args.images_dir}", file=sys.stderr)
            return 2
    else:
        sources = {}
        work = args.out_dir / "fixtures"
        work.mkdir(parents=True, exist_ok=True)
        for name in IMAGES:
            path = work / f"{name}.jpg"
            _synthetic(name).save(path, quality=92)
            sources[name] = path

    for name, path in sources.items():
        with Image.open(path) as image:
            if image.size[0] * image.size[1] < 256 * 256:
                print(f"{name} is below the 256x256 floor", file=sys.stderr)
                return 2

    if args.perturber == "sd":
        model_dir = Path(config.PHOTOGUARD_MODELS_DIR)
        if not model_dir.is_dir():
            print(f"SD perturber requested but no model at {model_dir}", file=sys.stderr)
            return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stored_bytes = len(watermark_invisible.pack_payload(args.payload).encode("utf-8"))
    bits = stored_bytes * 8
    artifacts = args.out_dir / "artifacts"
    artifacts.mkdir(exist_ok=True)

    all_layers = frozenset({pipeline.LAYER_INVISIBLE, pipeline.LAYER_PERTURB, pipeline.LAYER_VISIBLE})
    plain_layers = frozenset({pipeline.LAYER_INVISIBLE, pipeline.LAYER_VISIBLE})
    visible_only = frozenset({pipeline.LAYER_VISIBLE})

    cells_rows: list[dict[str, object]] = []
    retention_rows: list[dict[str, object]] = []
    failures: list[str] = []

    # Negative control (P6 step 5): visible-only has no envelope — verify must refuse it.
    control_src = sources[IMAGES[0]]
    control_out = artifacts / "negative_control.jpg"
    pipeline.protect(
        control_src, control_out,
        pipeline.ProtectOptions(payload=args.payload, layers=visible_only, visible_text="© control"),
    )
    control_crc, control_match = _decode_check(control_out, args.payload)
    if control_crc or control_match:
        print("negative control false-positive: visible-only product verified", file=sys.stderr)
        return 1

    for name, source in sources.items():
        base_sha = _sha256(source)
        with Image.open(source) as image:
            base_w, base_h = image.size
        deltas: dict[str, tuple[float, float]] = {}
        for cell in CELLS:
            out = artifacts / f"{name}-{cell.name}.jpg"
            pipeline.protect(
                source, out,
                _options(args.payload, layers=plain_layers, perturber=args.perturber),
            )
            clean = _apply_ops(Image.open(out).convert("RGB"), cell)
            pert_out = artifacts / f"{name}-{cell.name}-pert.jpg"
            pipeline.protect(
                source, pert_out,
                pipeline.ProtectOptions(
                    payload=args.payload, payload_envelope=True, layers=all_layers,
                    perturber=args.perturber,
                ),
            )
            perturbed = _apply_ops(Image.open(pert_out).convert("RGB"), cell)
            clean_arr = np.asarray(clean, dtype=np.int16)
            pert_arr = np.asarray(perturbed, dtype=np.int16)

            expected_edge = _expected_long_edge(cell)
            if max(clean.size) != expected_edge:
                print(
                    f"{name}/{cell.name}: post-ops long edge {max(clean.size)} != {expected_edge}",
                    file=sys.stderr,
                )
                return 2
            with Image.open(out) as artifact:
                if artifact.format != "JPEG":
                    print(f"{name}/{cell.name}: artifact format {artifact.format}", file=sys.stderr)
                    return 2

            crc_ok, payload_match = _decode_check(out, args.payload)
            with Image.open(out) as artifact:
                artifact_w, artifact_h = artifact.size
            # The frozen formula from fix-plan §6 P6: blocks (MCU-aligned) per stored bit.
            blocks = ((artifact_h // 4 * 4) // 8) * ((artifact_w // 4 * 4) // 8)
            bpb = blocks / bits
            cells_rows.append(
                {
                    "image": name,
                    "cell": cell.name,
                    "ops": repr(cell.ops),
                    "artifact_subsampling": _subsampling_of(out),
                    "stored_payload_bytes": stored_bytes,
                    "bits": bits,
                    "blocks_per_bit": f"{bpb:.4f}",
                    "carrier_channel": config.CARRIER_CHANNEL,
                    "carrier_scale": config.CARRIER_SCALE,
                    "fixture_sha256": base_sha,
                    "fixture_w": base_w,
                    "fixture_h": base_h,
                    "pass": crc_ok and payload_match,
                    "crc_ok": crc_ok,
                    "payload_match": payload_match,
                }
            )
            if clean_arr.shape != pert_arr.shape:
                print(f"{name}/{cell.name}: clean/pert shapes differ", file=sys.stderr)
                return 2
            delta = (pert_arr - clean_arr).astype(np.float64)
            deltas[cell.name] = (_rms(delta), float(np.abs(delta).max()))

            if (name, cell.name) in PINNED and not (crc_ok and payload_match):
                failures.append(f"pinned row {name}/{cell.name} did not pass")

        rms0, linf0 = deltas["identity"]
        for cell in CELLS:
            rms_q, linf_q = deltas[cell.name]
            retention_rows.append(
                {
                    "image": name,
                    "cell": cell.name,
                    "rms_ratio": f"{rms_q / rms0:.6f}",
                    "linf_ratio": f"{linf_q / linf0:.6f}",
                }
            )

    cells_path = args.out_dir / "cells.csv"
    retention_path = args.out_dir / "retention.csv"
    with cells_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CELLS_HEADER)
        writer.writeheader()
        writer.writerows(cells_rows)
    with retention_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RETENTION_HEADER)
        writer.writeheader()
        writer.writerows(retention_rows)

    # Frozen headers: the P5 contract reads these names; drift must be loud.
    with cells_path.open(newline="", encoding="utf-8") as handle:
        if tuple(next(csv.reader(handle))) != CELLS_HEADER:
            print("cells.csv header drifted", file=sys.stderr)
            return 2
    with retention_path.open(newline="", encoding="utf-8") as handle:
        if tuple(next(csv.reader(handle))) != RETENTION_HEADER:
            print("retention.csv header drifted", file=sys.stderr)
            return 2

    expected_rows = len(sources) * len(CELLS)
    if len(cells_rows) != expected_rows or len(retention_rows) != expected_rows:
        print(f"row count {len(cells_rows)} != {expected_rows}", file=sys.stderr)
        return 2

    first_image = next(iter(sources))
    identity_ratio = next(
        row["rms_ratio"] for row in retention_rows if row["image"] == first_image and row["cell"] == "identity"
    )
    if float(identity_ratio) != 1.0:
        print(f"identity rms_ratio must be exactly 1.0, got {identity_ratio}", file=sys.stderr)
        return 1

    import importlib.metadata as metadata

    try:
        version = metadata.version("photo-guard")
    except metadata.PackageNotFoundError:  # pragma: no cover - source tree without install
        version = "uninstalled"

    passed = sum(1 for row in cells_rows if row["pass"])
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    summary = args.out_dir / "summary.md"
    summary.write_text(
        "\n".join(
            [
                "# efficacy matrix summary",
                "",
                f"- run: {len(sources)} images x {len(CELLS)} cells; pass {passed}/{expected_rows}",
                f"- perturber: {args.perturber}; payload {args.payload!r} "
                f"({bits} bit, {stored_bytes} stored bytes)",
                f"- negative control (visible-only): crc_ok={control_crc} match={control_match} "
                f"(both must be False)",
                f"- versions: python {sys.version.split()[0]}, Pillow {Image.__version__}, "
                f"numpy {np.__version__}, photo-guard {version}, sha {sha}",
                f"- artifact_subsampling: {sorted({row['artifact_subsampling'] for row in cells_rows})}",
                "",
                "Pinned rows (must be 100%): " + ", ".join(sorted(f"{i}/{c}" for i, c in PINNED)),
                "",
                "| image | cell | pass | crc_ok | payload_match | blocks_per_bit |",
                "|---|---|---|---|---|---|",
                *(
                    f"| {row['image']} | {row['cell']} | {row['pass']} | {row['crc_ok']} | "
                    f"{row['payload_match']} | {row['blocks_per_bit']} |"
                    for row in cells_rows
                ),
                "",
                "rms_ratio/linf_ratio = fraction of the *perturbation* surviving the cell's ops;",
                "identity is exactly 1.0 by construction. Never read these as protection strength.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if failures:
        print("; ".join(failures), file=sys.stderr)
        return 1
    print(f"efficacy matrix OK: {passed}/{expected_rows} pass; artifacts in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
