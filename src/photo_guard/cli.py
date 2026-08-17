"""Command-line interface for protection, verification, devices and model setup."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, device, perturb, pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photo-guard", description="Three-layer photo protection")
    sub = parser.add_subparsers(dest="cmd", required=True)

    protect = sub.add_parser("protect", help="Protect one image")
    protect.add_argument("input", type=Path)
    protect.add_argument("-o", "--output", type=Path, required=True)
    protect.add_argument("--payload", default=config.DEFAULT_PAYLOAD)
    protect.add_argument(
        "--layers", default=",".join(sorted(pipeline.DEFAULT_LAYERS)),
        help=("Comma-separated subset of invisible,perturb,visible; order stays fixed. "
              "Choosing noise or sd automatically enables perturb"),
    )
    protect.add_argument("--perturber", default=config.DEFAULT_PERTURBER, choices=perturb.available())
    protect.add_argument("--visible-mode", default=config.DEFAULT_VISIBLE_MODE, choices=["subject", "tile", "center"])
    protect.add_argument("--visible-text", default=config.DEFAULT_VISIBLE_TEXT)
    protect.add_argument("--visible-alpha", type=float, default=config.DEFAULT_VISIBLE_ALPHA)
    protect.add_argument("--long-edge", type=int, default=config.DEFAULT_LONG_EDGE, help="0 keeps original size")
    protect.add_argument("--quality", type=int, default=config.DEFAULT_JPEG_QUALITY)
    protect.add_argument("--payload-envelope", action="store_true", help="Embed a versioned payload with CRC integrity checking")

    group = protect.add_argument_group("PhotoGuard SD attack")
    group.add_argument("--device", choices=["auto", "cpu", "cuda", "mps"], default="auto")
    group.add_argument("--device-index", type=int, default=None)
    group.add_argument("--perturber-eps", type=float, default=config.PHOTOGUARD_EPSILON)
    group.add_argument("--perturber-step-size", type=float, default=config.PHOTOGUARD_STEP_SIZE)
    group.add_argument("--perturber-steps", type=int, default=config.PHOTOGUARD_STEPS)
    group.add_argument("--perturber-model", default=config.PHOTOGUARD_MODEL_ID, help="Local SD VAE directory")

    verify = sub.add_parser("verify", help="Verify an invisible watermark")
    verify.add_argument("suspect", type=Path)
    mode = verify.add_mutually_exclusive_group(required=True)
    mode.add_argument("--expected-payload", help="Verify a new CRC-protected payload")
    mode.add_argument("--payload-bytes", type=int, help="Legacy/raw stored payload byte length")

    sub.add_parser("devices", help="List detected compute devices")

    download = sub.add_parser("download-models", help="Download the offline SD VAE")
    download.add_argument("--repo", default=config.PHOTOGUARD_REMOTE_REPO)
    download.add_argument("--dest", type=Path, default=None)
    return parser


def _parse_layers(spec: str) -> frozenset[str]:
    parts = [part.strip() for part in spec.split(",") if part.strip()]
    if not parts:
        raise ValueError("--layers must name at least one protection layer")
    unknown = [part for part in parts if part not in pipeline.ALL_LAYERS]
    if unknown:
        raise ValueError(f"--layers got unknown name(s) {unknown!r}")
    return frozenset(parts)


def _looks_like_no_payload(payload: str) -> bool:
    if not payload:
        return True
    bad = sum(1 for ch in payload if ch in {"\x00", "�"} or (ord(ch) < 0x20 and ch not in "\t\n\r"))
    return bad >= max(1, len(payload) // 2)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "protect":
            layers = _parse_layers(args.layers)
            if args.perturber != "noop":
                layers = frozenset({*layers, pipeline.LAYER_PERTURB})
            if args.perturber_steps <= 0:
                raise ValueError("perturber steps must be positive")
            if args.perturber_eps < 0 or args.perturber_step_size <= 0:
                raise ValueError("perturber epsilon/step size are invalid")
            kwargs: dict[str, object] = {}
            if args.perturber == "sd":
                kwargs.update(
                    epsilon=args.perturber_eps, step_size=args.perturber_step_size,
                    steps=args.perturber_steps, model_id=args.perturber_model,
                    device=args.device, device_index=args.device_index,
                )
            elif args.perturber == "noise":
                kwargs["epsilon"] = args.perturber_eps
            info = pipeline.protect(
                args.input, args.output,
                pipeline.ProtectOptions(
                    payload=args.payload, perturber=args.perturber,
                    perturber_kwargs=kwargs, visible_mode=args.visible_mode,
                    visible_text=args.visible_text, visible_alpha=args.visible_alpha,
                    long_edge=args.long_edge, quality=args.quality, layers=layers,
                    payload_envelope=args.payload_envelope,
                ),
            )
            print(
                f"protected: {info['output']} size={info['size'][0]}x{info['size'][1]} "
                f"layers={'+'.join(info['layers'])} perturber={info['perturber']} "
                f"payload_bytes={info['payload_bytes']}"
            )
            return 0

        if args.cmd == "verify":
            if args.expected_payload is not None:
                result = pipeline.verify_expected(args.suspect, args.expected_payload)
                print(result["payload"])
                return 0
            payload = pipeline.verify(args.suspect, args.payload_bytes)
            if _looks_like_no_payload(payload):
                print("no payload recovered", file=sys.stderr)
                return 1
            print(payload)
            return 0

        if args.cmd == "devices":
            for item in device.discover_devices():
                status = "supported" if item.supported else "unsupported (CPU fallback)"
                memory = f" {item.memory_bytes / 2**30:.1f} GiB" if item.memory_bytes else ""
                print(f"{item.key}: {item.name}{memory} [{status}]")
            return 0

        if args.cmd == "download-models":
            from . import download
            path = download.download_sd_vae(repo=args.repo, dest=args.dest)
            print(f"downloaded {args.repo} → {path}")
            return 0
    except (OSError, ValueError, RuntimeError, InterruptedError) as exc:
        print(f"{args.cmd} failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{args.cmd} failed: {exc}", file=sys.stderr)
        return 2
    return 2
