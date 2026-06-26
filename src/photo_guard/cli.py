"""CLI entry point: `photo-guard {protect,verify}`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, perturb, pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-guard",
        description="Three-layer photo anti-theft pipeline (AGENTS.md).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "protect",
        help="Apply invisible watermark → perturbation → visible watermark.",
    )
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--payload", default=config.DEFAULT_PAYLOAD)
    p.add_argument(
        "--layers",
        default=",".join(sorted(pipeline.ALL_LAYERS)),
        help=(
            "Comma-separated subset of {invisible,perturb,visible} to apply. "
            "Order of execution is FIXED (invisible → perturb → visible) per "
            "AGENTS.md §二 — this flag only controls which layers are present, "
            "never the sequence. Default: all three. "
            "Disabling any layer weakens overall protection."
        ),
    )
    p.add_argument(
        "--perturber",
        default=config.DEFAULT_PERTURBER,
        choices=perturb.available(),
    )
    p.add_argument(
        "--visible-mode",
        default=config.DEFAULT_VISIBLE_MODE,
        choices=["subject", "tile", "center"],
    )
    p.add_argument("--visible-text", default=config.DEFAULT_VISIBLE_TEXT)
    p.add_argument(
        "--visible-alpha", type=float, default=config.DEFAULT_VISIBLE_ALPHA
    )
    p.add_argument("--long-edge", type=int, default=config.DEFAULT_LONG_EDGE)
    p.add_argument("--quality", type=int, default=config.DEFAULT_JPEG_QUALITY)

    pg = p.add_argument_group(
        "PhotoGuard SD-encoder attack (--perturber sd; needs `uv sync --extra photoguard`)"
    )
    pg.add_argument(
        "--perturber-eps",
        type=float,
        default=config.PHOTOGUARD_EPSILON,
        help="L∞ perturbation budget in [0,1] image space (default %(default).4f ≈ 8/255)",
    )
    pg.add_argument(
        "--perturber-step-size",
        type=float,
        default=config.PHOTOGUARD_STEP_SIZE,
        help="PGD step size in [0,1] image space (default %(default).4f ≈ 2/255)",
    )
    pg.add_argument(
        "--perturber-steps",
        type=int,
        default=config.PHOTOGUARD_STEPS,
        help="Number of PGD iterations (default %(default)d)",
    )
    pg.add_argument(
        "--perturber-model",
        default=config.PHOTOGUARD_MODEL_ID,
        help="HuggingFace model id for the SD VAE (default %(default)s)",
    )

    v = sub.add_parser(
        "verify",
        help="Extract the embedded invisible-watermark payload from a suspect image.",
    )
    v.add_argument("suspect", type=Path)
    v.add_argument(
        "--payload-bytes",
        type=int,
        required=True,
        help="Byte length of the original payload (must match embed time).",
    )

    d = sub.add_parser(
        "download-models",
        help=(
            "One-off: fetch the SD VAE used by --perturber sd into "
            "models/sd-vae-ft-mse/ for fully offline runs."
        ),
    )
    d.add_argument(
        "--repo",
        default=config.PHOTOGUARD_REMOTE_REPO,
        help="HuggingFace repo id (default %(default)s).",
    )
    d.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=(
            "Destination directory; defaults to "
            f"{config.PHOTOGUARD_MODELS_DIR / config.PHOTOGUARD_MODEL_NAME}"
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "protect":
        try:
            layers = _parse_layers(args.layers)
        except ValueError as exc:
            print(f"protect failed: {exc}", file=sys.stderr)
            return 2

        perturber_kwargs: dict[str, object] = {}
        if args.perturber == "sd":
            perturber_kwargs.update(
                epsilon=args.perturber_eps,
                step_size=args.perturber_step_size,
                steps=args.perturber_steps,
                model_id=args.perturber_model,
            )
        elif args.perturber == "noise":
            perturber_kwargs["epsilon"] = args.perturber_eps

        opts = pipeline.ProtectOptions(
            payload=args.payload,
            perturber=args.perturber,
            perturber_kwargs=perturber_kwargs,
            visible_mode=args.visible_mode,
            visible_text=args.visible_text,
            visible_alpha=args.visible_alpha,
            long_edge=args.long_edge,
            quality=args.quality,
            layers=layers,
        )
        try:
            info = pipeline.protect(args.input, args.output, opts)
        except RuntimeError as exc:  # missing optional extra
            print(f"protect failed: {exc}", file=sys.stderr)
            return 2
        print(
            f"protected: {info['output']}  "
            f"size={info['size'][0]}x{info['size'][1]}  "
            f"layers={'+'.join(info['layers'])}  "
            f"perturber={info['perturber']}  "
            f"payload_bytes={info['payload_bytes']}"
        )
        return 0

    if args.cmd == "verify":
        try:
            payload = pipeline.verify(args.suspect, args.payload_bytes)
        except Exception as exc:  # decoding failures vary by backend
            print(f"verify failed: {exc}", file=sys.stderr)
            return 2
        if _looks_like_no_payload(payload):
            print(
                "no payload recovered; image may have been deeply repainted "
                "or never carried a photo-guard watermark",
                file=sys.stderr,
            )
            return 1
        print(payload)
        return 0

    if args.cmd == "download-models":
        from . import download

        try:
            path = download.download_sd_vae(repo=args.repo, dest=args.dest)
        except RuntimeError as exc:
            print(f"download failed: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # network / hub errors
            print(f"download failed: {exc}", file=sys.stderr)
            return 2
        print(f"downloaded {args.repo} → {path}")
        return 0

    return 2


def _looks_like_no_payload(payload: str) -> bool:
    """A recovered string counts as 'no payload' when it is:
    - empty, or
    - entirely NUL bytes (decoder returned zeros), or
    - dominated by UTF-8 replacement chars / control chars (decoder returned
      garbage that errors='replace' patched up).
    """
    if not payload:
        return True
    bad = sum(
        1
        for ch in payload
        if ch == "\x00" or ch == "�" or (ord(ch) < 0x20 and ch not in "\t\n\r")
    )
    return bad >= max(1, len(payload) // 2)


def _parse_layers(spec: str) -> frozenset[str]:
    """Parse `--layers` into a validated frozenset.

    Accepts comma-separated subset of {invisible, perturb, visible},
    whitespace-tolerant. Raises ValueError on unknown names or empty set
    so the caller can map it to a clean exit code.
    """
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise ValueError(
            f"--layers must name at least one of {sorted(pipeline.ALL_LAYERS)!r}"
        )
    unknown = [p for p in parts if p not in pipeline.ALL_LAYERS]
    if unknown:
        raise ValueError(
            f"--layers got unknown name(s) {unknown!r}; "
            f"expected subset of {sorted(pipeline.ALL_LAYERS)!r}"
        )
    return frozenset(parts)
