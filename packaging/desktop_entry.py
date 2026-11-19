from __future__ import annotations

import math
import os
import sys

# Held for the process lifetime: a QApplication that only lives on the stack is destroyed
# while Qt still expects it, and the resulting crash would look like a bundle defect.
_QT_APP = None


def _smoke_gui() -> None:
    """P69: the bundle must be able to start Qt, not merely carry the wheel.

    Forced rather than defaulted: an inherited platform plugin would decide whether the
    release gate passes. ``offscreen`` needs no display and ships in Nuitka's ``platforms``
    plugin family, so a bundle whose Qt plugins were dropped fails here (7).
    """
    global _QT_APP

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import PySide6
    from PySide6.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    platform = _QT_APP.platformName()
    if platform != "offscreen":
        raise RuntimeError(f"expected the offscreen platform, got {platform!r}")
    import photo_guard.gui  # noqa: F401  (the window module must be in the bundle)
    print(f"GUI runtime: PySide6={PySide6.__version__} platform={platform}")


def _smoke_vae() -> None:
    """P69: importing torch/diffusers is not proof the baked weights can be loaded.

    An 8×8 image keeps this to one encoder pass; the norm must be finite, so a directory
    holding an empty ``*.safetensors`` passes the filename check but fails here (8).
    """
    import numpy as np

    from photo_guard import photoguard

    norm = photoguard.build_attack().latent_norm(np.zeros((8, 8, 3), dtype=np.uint8))
    if not math.isfinite(norm):
        raise RuntimeError(f"latent norm is not finite: {norm}")
    print(f"PhotoGuard VAE: loaded (latent_norm={norm:.3f})")


def _smoke_test(with_photoguard: bool = False, with_gui: bool = False) -> int:
    """Exit codes: 2 = model/bundle material, 3 = no CPU backend, 4 = licences,
    5 = PhotoGuard runtime missing, 6 = CUDA torch in a Windows bundle (DOC6),
    7 = GUI runtime (Qt/plugin) missing, 8 = SD VAE failed to load (P69)."""
    from photo_guard import config, device, pipeline, resources

    if not config.PHOTOGUARD_MODEL_ID:
        return 2
    # G6/Q2-N5: a configured path is not a model, and neither is a directory with only
    # config.json. Without the completeness check a machine that never ran
    # `download-models` (or whose models/ was not shipped fully) still reported success.
    if not config.model_dir_is_complete(config.PHOTOGUARD_MODEL_ID):
        # P73: name every candidate root and whether its model is usable. The macOS bundle
        # can hold a shadow ``Resources/models`` (relocated ``.cache`` symlink) while the
        # weights live in ``MacOS/models``; without this probe the failure path alone said
        # "missing" without saying which root was chosen.
        probes = "; ".join(
            f"{candidate}="
            + ("complete" if config.model_dir_is_complete(candidate) else "missing/incomplete")
            for candidate in (
                root / "models" / config.PHOTOGUARD_MODEL_NAME
                for root in resources.candidate_roots()
            )
        )
        print(
            f"model directory missing or incomplete: {config.PHOTOGUARD_MODEL_ID} "
            f"(needs config.json and *.safetensors; probed: {probes})",
            file=sys.stderr,
        )
        return 2
    # G2/P33: the licence material must ship beside the bundle; a build that forgot to include
    # it (or an install that dropped it) must not report success. The macOS bundle keeps the
    # two layouts apart — Nuitka's data-dirs land in Contents/Resources while data-files land
    # next to the executable in Contents/MacOS — so probe every candidate root and, when
    # something is missing, say which roots were tried (that is what turned a 40-minute build
    # round into a diagnosis last time).
    missing = [
        name
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")
        if resources.find_resource(name) is None
    ]
    if missing:
        tried = ", ".join(str(root) for root in resources.candidate_roots())
        print(
            f"licence material missing from the bundle: {', '.join(missing)} "
            f"(looked in: {tried})",
            file=sys.stderr,
        )
        return 4
    if not any(item.backend == "cpu" for item in device.discover_devices(include_unsupported=False)):
        return 3
    pipeline.validate_options(pipeline.ProtectOptions())
    if with_photoguard:
        # DOC6/R7: the bundles declare PyTorch + diffusers, but the old smoke never imported
        # them — a build that dropped torch still reported success and only failed on the
        # user's first `--perturber sd` run. The flag stays opt-in because a core/dev tree
        # legitimately has no torch.
        try:
            import torch
            import diffusers  # noqa: F401  (both are part of the shipped runtime)
        except (ImportError, OSError) as exc:
            print(f"PhotoGuard runtime is missing from the bundle: {exc}", file=sys.stderr)
            return 5
        cuda = getattr(getattr(torch, "version", None), "cuda", None)
        # The line is the Windows evidence DOC6 asked for: the release log records it.
        print(
            f"PhotoGuard runtime: torch={getattr(torch, '__version__', 'unknown')} cuda={cuda}"
        )
        if sys.platform == "win32" and cuda is not None:
            print(
                f"Windows bundle must ship CPU-only torch, but torch.version.cuda={cuda}",
                file=sys.stderr,
            )
            return 6
    if with_gui:
        # P69: the GUI is a shipped feature; a bundle without Qt (or without its platform
        # plugins) used to pass this smoke and only fail when the user opened the app.
        try:
            _smoke_gui()
        except (ImportError, OSError, RuntimeError) as exc:
            print(f"GUI runtime is missing from the bundle: {exc}", file=sys.stderr)
            return 7
    if with_photoguard:
        # P69: ran after the cheap structural checks above so a broken Qt does not pay for
        # a VAE load, and after the CUDA policy gate so DOC6 keeps its own exit code.
        try:
            _smoke_vae()
        except Exception as exc:  # safetensors/diffusers raise several unrelated types
            print(f"PhotoGuard VAE is missing or unreadable: {exc}", file=sys.stderr)
            return 8
    print("Photo Guard desktop smoke test passed")
    return 0


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        raise SystemExit(
            _smoke_test(
                with_photoguard="--with-photoguard" in sys.argv,
                with_gui="--with-gui" in sys.argv,
            )
        )
    from photo_guard.gui import main
    raise SystemExit(main())
