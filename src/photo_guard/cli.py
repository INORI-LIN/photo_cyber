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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "protect":
        opts = pipeline.ProtectOptions(
            payload=args.payload,
            perturber=args.perturber,
            visible_mode=args.visible_mode,
            visible_text=args.visible_text,
            visible_alpha=args.visible_alpha,
            long_edge=args.long_edge,
            quality=args.quality,
        )
        info = pipeline.protect(args.input, args.output, opts)
        print(
            f"protected: {info['output']}  "
            f"size={info['size'][0]}x{info['size'][1]}  "
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
        if not payload or all(c == "\x00" for c in payload):
            print(
                "no payload recovered; image may have been deeply repainted "
                "or never carried a photo-guard watermark",
                file=sys.stderr,
            )
            return 1
        print(payload)
        return 0

    return 2
