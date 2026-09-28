"""GPU benchmark for the SD perturber — a committed developer script.

Times the perturb layer on this machine. What it can run depends on the environment:

1-2. invisible-only and noise baselines — the core environment is enough.
3.   device probe (torch).
4-6. SD VAE encoder runs — need ``uv sync --extra photoguard`` plus a local model
     (``uv run photo-guard download-models``); if either is missing those sections are
     skipped with the prerequisite message instead of crashing.

All artifacts go to a fresh temp directory (never the CWD) and are removed on exit,
including when a section raises. Run it with::

    uv run --no-sync python gpu_bench.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from photo_guard import config
from photo_guard.pipeline import ProtectOptions, protect

PERTURB_ONLY = frozenset({"perturb"})


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="pg_gpu_test_"))
    try:
        img_path = tmpdir / "in.jpg"
        out_path = tmpdir / "out.jpg"
        Image.new("RGB", (512, 512), (128, 128, 128)).save(img_path, quality=95)

        print("=" * 50)
        print("photo-guard GPU Benchmark")
        print("=" * 50)

        # 1. Baseline: every fixed stage except the perturber.
        t0 = time.perf_counter()
        protect(img_path, out_path, ProtectOptions(layers=frozenset({"invisible"})))
        print(f"invisible-only (baseline): {time.perf_counter() - t0:.4f}s")

        # 2. Noise perturber.
        t0 = time.perf_counter()
        protect(
            img_path,
            out_path,
            ProtectOptions(
                perturber="noise",
                perturber_kwargs={"epsilon": 2.0 / 255},
                layers=PERTURB_ONLY,
            ),
        )
        print(f"noise (e=2/255):           {time.perf_counter() - t0:.4f}s")

        # 3. Device probe.
        import torch

        dev = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        print(f"Device: {dev}")

        last_case = "noise (e=2/255)"
        try:
            # 4. SD 10 steps at 512px
            t0 = time.perf_counter()
            protect(
                img_path,
                out_path,
                ProtectOptions(
                    perturber="sd",
                    perturber_kwargs={
                        "epsilon": 8.0 / 255,
                        "step_size": 2.0 / 255,
                        "steps": 10,
                    },
                    layers=PERTURB_ONLY,
                ),
            )
            last_case = "sd-512px-10steps"
            print(f"{last_case}:      {time.perf_counter() - t0:.3f}s")

            # 5. SD 20 steps at 512px
            t0 = time.perf_counter()
            protect(
                img_path,
                out_path,
                ProtectOptions(
                    perturber="sd",
                    perturber_kwargs={
                        "epsilon": 8.0 / 255,
                        "step_size": 2.0 / 255,
                        "steps": 20,
                    },
                    layers=PERTURB_ONLY,
                ),
            )
            last_case = "sd-512px-20steps"
            print(f"{last_case}:      {time.perf_counter() - t0:.3f}s")

            # 6. Different resolutions (10 steps)
            for size, name in [(256, "256px"), (512, "512px"), (1024, "1024px")]:
                test_img = Image.new("RGB", (size, size), (128, 128, 128))
                test_img.save(img_path, quality=95)
                t0 = time.perf_counter()
                protect(
                    img_path,
                    out_path,
                    ProtectOptions(
                        perturber="sd",
                        perturber_kwargs={
                            "epsilon": 8.0 / 255,
                            "step_size": 2.0 / 255,
                            "steps": 10,
                        },
                        layers=PERTURB_ONLY,
                        long_edge=max(size * 2, 1080),
                    ),
                )
                last_case = f"sd-{name}-10steps"
                print(f"{last_case}:      {time.perf_counter() - t0:.3f}s")
        except RuntimeError as exc:
            print(f"\nSD sections aborted: {exc}", file=sys.stderr)
            print(
                "prerequisite: uv sync --extra photoguard, then "
                "uv run photo-guard download-models",
                file=sys.stderr,
            )
            print(f"\nperturbation bounds: skipped (SD sections aborted, last case {last_case})")
            return 0

        # 7. Perturbation bounds against a same-quality control: diffing the q95 input
        # against the q85 output would count the JPEG round trip as perturbation.
        control_path = tmpdir / "control.jpg"
        Image.open(img_path).save(control_path, quality=config.DEFAULT_JPEG_QUALITY)
        control = np.asarray(Image.open(control_path), dtype=float)
        protected = np.asarray(Image.open(out_path), dtype=float)
        diff = np.abs(control - protected)
        print(
            f"\n{last_case}: L-inf {diff.max() / 255:.4f} (budget "
            f"{config.PHOTOGUARD_EPSILON:.4f}), mean {diff.mean():.2f}/255 "
            f"— includes the JPEG q{config.DEFAULT_JPEG_QUALITY} residual"
        )
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
