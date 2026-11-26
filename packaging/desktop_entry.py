from __future__ import annotations

import dataclasses
import math
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable

# Held for the process lifetime: a QApplication that only lives on the stack is destroyed
# while Qt still expects it, and the resulting crash would look like a bundle defect.
_QT_APP = None

# P76: the GUI probe runs in a child process started with this hidden flag. Qt reports a
# missing platform plugin through qFatal, which aborts the process: in-process, that killed
# the smoke before it printed a verdict, let alone ran the remaining probes.
_GUI_PROBE_FLAG = "--smoke-gui-probe"
# A Qt start-up that hangs must fail this probe, not hold the release step until the job
# timeout.
_GUI_PROBE_TIMEOUT = 120


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


def _gui_probe_main() -> int:
    """The ``--smoke-gui-probe`` child (P76): 0, or 7 with the in-process probe's message.

    Any other exception propagates: Python prints its traceback and exits 1, which
    :func:`_probe_gui` reports as 1, the old in-process result.
    """
    try:
        _smoke_gui()
    except (ImportError, OSError, RuntimeError) as exc:
        print(f"GUI runtime is missing from the bundle: {exc}", file=sys.stderr)
        return 7
    return 0


def _gui_probe_command() -> list[str]:
    """How to start this program again as the GUI child (P76), decided at call time.

    - Source tree: ``sys.executable`` is the interpreter and this file is a real script, so
      the interpreter re-runs it. ``sys.executable`` stays unresolved: resolving a venv's
      ``python`` symlink would leave the venv.
    - Nuitka standalone: ``__file__`` names no real script, so the flag goes straight to the
      program, :func:`photo_guard.resources.program_path`. Before ``multiprocessing`` is
      imported ``sys.executable`` names a ``python``/``python.exe`` beside the binary that
      Nuitka does not ship; after that import Nuitka rewrites it to the program. In the
      release smoke it would name the program only because torch, imported by the
      cpu-backend probe, imports ``multiprocessing``. ``program_path`` reads Nuitka's
      ``__nuitka_binary_exe`` builtin first, so the child does not depend on that.
    """
    from photo_guard import resources

    if resources.is_bundled():
        return [str(resources.program_path()), _GUI_PROBE_FLAG]
    return [sys.executable, str(Path(__file__).resolve()), _GUI_PROBE_FLAG]


def _ascii(text: str) -> str:
    """Keep forwarded text ASCII: a Windows console redirected to a file encodes with cp1252
    and raises on anything else (P76). Escapes keep the information."""
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


def _echo(data: str | bytes | None, *, stderr: bool = False) -> None:
    """Forward the GUI child's output. ``TimeoutExpired`` carries bytes (POSIX) or ``None``."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if data:
        print(
            _ascii(data),
            end="" if data.endswith("\n") else "\n",
            file=sys.stderr if stderr else None,
        )


def _probe_gui() -> int:
    """P69: the GUI is a shipped feature; a bundle without Qt (or without its platform
    plugins) used to pass the smoke and only fail when the user opened the app.

    P76: checked in a child process, so a qFatal abort becomes an exit code instead of
    ending the smoke. The child must exit 0 *and* print its ``GUI runtime:`` line. Exit
    codes keep the in-process meaning (lead decision, strict parity for Python failures):
    the child maps ImportError/OSError/RuntimeError to 7 itself, and any other exception is
    Python's uncaught exit 1, which stays 1 here as it was in process. Native failures (a
    signal such as qFatal's SIGABRT, Windows' abort code 3, any other code), a hang, a
    launch error or a missing ``GUI runtime:`` line are 7.
    """
    command = _gui_probe_command()
    # Forced, not inherited (as in _smoke_gui); UTF-8 so the child never dies in print().
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GUI_PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        _echo(exc.stdout)
        _echo(exc.stderr, stderr=True)
        reason = f"the GUI probe did not finish within {_GUI_PROBE_TIMEOUT} s"
    except OSError as exc:
        reason = f"the GUI probe could not be started: {exc}"
    else:
        _echo(result.stdout)
        _echo(result.stderr, stderr=True)
        if result.returncode == 0 and "GUI runtime:" in (result.stdout or ""):
            return 0
        if result.returncode == 1:
            # Not necessarily an exception: SystemExit(1) and an interpreter start-up failure
            # also exit 1. The child's own output above says which.
            print(
                "GUI runtime is missing from the bundle: the GUI probe exited 1 "
                "(an uncaught exception or SystemExit; its output is above)",
                file=sys.stderr,
            )
            return 1
        if result.returncode:
            reason = f"the GUI probe exited with returncode {result.returncode}"
        else:
            reason = "the GUI probe exited with returncode 0 but printed no 'GUI runtime:' line"
    print(f"GUI runtime is missing from the bundle: {_ascii(reason)}", file=sys.stderr)
    return 7


def _smoke_vae():
    """P69: importing torch/diffusers is not proof the baked weights can be loaded.

    An 8×8 image keeps this to one encoder pass; the norm must be finite, so a directory
    holding an empty ``*.safetensors`` passes the filename check but fails here (8). P76: the
    attack is configured for one PGD step and returned, so the PGD probe reuses this load.
    """
    import numpy as np

    from photo_guard import config, photoguard

    attack = photoguard.build_attack(
        photoguard.PGDConfig(steps=1, model_id=config.PHOTOGUARD_MODEL_ID)
    )
    norm = attack.latent_norm(np.zeros((8, 8, 3), dtype=np.uint8))
    if not math.isfinite(norm):
        raise RuntimeError(f"latent norm is not finite: {norm}")
    print(f"PhotoGuard VAE: loaded (latent_norm={norm:.3f})")
    return attack


def _smoke_pgd(attack) -> None:
    """P76: one real PGD step. ``latent_norm`` runs under no_grad, so the smoke never
    exercised autograd — the path every ``--perturber sd`` run takes.

    An 8×8 mid-gray image goes through the configured step, then through the same seed with
    ``step_size=0`` (the bare starting point). The step must keep the shape and uint8, move
    at least one level yet stay inside the L-inf budget (+1 for uint8 rounding), and differ
    from its starting point: that is what proves the gradient moved pixels. The last check
    is exact on CPU, and on MPS as measured with torch 2.12.1 (a seeded MPS generator
    repeats its draw). It is weaker only on a device whose generator cannot be seeded (P1's
    fallback to the global RNG): there the two starts differ anyway.
    """
    import numpy as np

    image = np.full((8, 8, 3), 128, dtype=np.uint8)
    stepped = attack.attack(image)
    attack.cfg = dataclasses.replace(attack.cfg, step_size=0.0)
    start = attack.attack(image)
    for label, out in (("the stepped output", stepped), ("the starting point", start)):
        if out.dtype != np.uint8 or out.shape != image.shape:
            raise RuntimeError(
                f"{label} is {out.dtype} {out.shape}, expected uint8 {image.shape}"
            )
    max_delta = int(np.abs(stepped.astype(np.int16) - image.astype(np.int16)).max())
    budget = math.ceil(attack.cfg.epsilon * 255) + 1
    if not 0 < max_delta <= budget:
        raise RuntimeError(f"max_delta={max_delta} is outside the budget (0, {budget}]")
    if np.array_equal(stepped, start):
        raise RuntimeError("the step left every pixel at its same-seed starting point")
    backend = getattr(attack.device_info, "backend", "unknown")
    print(f"PhotoGuard PGD: 1 step ok (device={backend}, max_delta={max_delta}, budget={budget})")


def _probe_model(config, resources) -> int:
    if not config.PHOTOGUARD_MODEL_ID:
        # P76: this exit used to be silent. An empty id is no path at all — Path("") is the
        # working directory — so the completeness check below must not run on it.
        print("PHOTOGUARD_MODEL_ID is empty: no SD VAE directory is configured", file=sys.stderr)
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
    return 0


def _probe_licences(resources) -> int:
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
    return 0


def _probe_cpu_backend(device) -> int:
    discovered = device.discover_devices(include_unsupported=False)
    if any(item.backend == "cpu" for item in discovered):
        return 0
    # P76: this exit used to be silent; name what discovery did find.
    found = "; ".join(
        f"{item.key} {ascii(item.name)} supported={item.supported} available={item.available}"
        for item in discovered
    )
    print(f"no CPU backend found (discovered: {found or 'nothing'})", file=sys.stderr)
    return 3


def _probe_options(pipeline) -> int:
    pipeline.validate_options(pipeline.ProtectOptions())
    return 0


def _probe_runtime(state: dict) -> int:
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
    print(f"PhotoGuard runtime: torch={getattr(torch, '__version__', 'unknown')} cuda={cuda}")
    state["cuda"] = cuda
    return 0


def _probe_cpu_only_torch(cuda) -> int:
    if cuda is not None:
        print(
            f"Windows bundle must ship CPU-only torch, but torch.version.cuda={cuda}",
            file=sys.stderr,
        )
        return 6
    return 0


def _probe_vae(state: dict) -> int:
    try:
        state["attack"] = _smoke_vae()
    except Exception as exc:  # safetensors/diffusers raise several unrelated types
        print(f"PhotoGuard VAE is missing or unreadable: {exc}", file=sys.stderr)
        return 8
    return 0


def _probe_pgd(attack) -> int:
    try:
        _smoke_pgd(attack)
    except Exception as exc:  # autograd, device and dtype failures raise unrelated types
        print(f"PhotoGuard PGD step failed: {_ascii(str(exc))}", file=sys.stderr)
        return 9
    return 0


def _run_probe(name: str, probe: Callable[[], int]) -> int:
    """Run one probe and print its verdict (P76).

    A probe maps only the exception types it always mapped; anything else is exit 1 with a
    traceback — what the old smoke's uncaught exception produced — and the run goes on.
    """
    try:
        code = probe()
    except Exception:
        traceback.print_exc()
        code = 1
    if code:
        print(f"[smoke] {name}: FAILED (exit {code})", file=sys.stderr)
    else:
        print(f"[smoke] {name}: ok")
    return code


def _smoke_test(with_photoguard: bool = False, with_gui: bool = False) -> int:
    """Run every probe; return the first failure in this fixed order, which is the priority.

    2 = model/bundle material, 4 = licences, 3 = no CPU backend, 1 = options (or any
    unexpected error inside a probe, the GUI child's included), 5 = PhotoGuard runtime
    missing, 6 = CUDA torch in a Windows bundle (DOC6), 7 = GUI runtime (Qt/plugin) missing,
    or the GUI child crashed, hung or could not start, 8 = SD VAE failed to load (P69),
    9 = one PGD step failed (P76). 5/6/8/9 need ``with_photoguard`` (6 only on
    Windows), 7 needs ``with_gui``; a probe that does not apply prints nothing. P76 (user
    decision 2026-11-25): a failure no longer stops the run — one ~3 h release round must
    name every broken probe. The VAE probe is skipped when the model or the runtime failed,
    the PGD probe when the VAE probe failed or was skipped.
    """
    # Importing the package is not a probe: nothing below can run without it, so a failure
    # here stays the uncaught exit 1 it always was.
    from photo_guard import config, device, pipeline, resources

    # P76: flush stdout per line. When it is redirected (both release legs), a block-buffered
    # stdout would be lost if a native crash (torch, Qt) ends the process mid-probe, and the
    # log would no longer say which probes had already passed.
    reconfigure = getattr(getattr(sys, "stdout", None), "reconfigure", None)
    if reconfigure is not None:
        reconfigure(line_buffering=True)

    failed: list[tuple[str, int]] = []

    def run(name: str, probe: Callable[[], int]) -> bool:
        code = _run_probe(name, probe)
        if code:
            failed.append((name, code))
        return not code

    def skip(name: str, reason: str) -> None:
        print(f"[smoke] {name}: skipped ({reason})", file=sys.stderr)

    model_ok = run("model", lambda: _probe_model(config, resources))
    run("licences", lambda: _probe_licences(resources))
    run("cpu-backend", lambda: _probe_cpu_backend(device))
    run("options", lambda: _probe_options(pipeline))
    state: dict = {}
    runtime_ok = False
    if with_photoguard:
        runtime_ok = run("photoguard-runtime", lambda: _probe_runtime(state))
        if sys.platform == "win32":
            if runtime_ok:
                run("cpu-only-torch", lambda: _probe_cpu_only_torch(state["cuda"]))
            else:
                skip("cpu-only-torch", "photoguard-runtime failed")
    if with_gui:
        run("gui", _probe_gui)
    if with_photoguard:
        # P69: after the cheap structural checks and the CUDA policy gate, so their exit
        # codes keep priority over a VAE failure.
        blockers = [
            name for name, ok in (("model", model_ok), ("photoguard-runtime", runtime_ok))
            if not ok
        ]
        if blockers:
            skip("vae", f"{', '.join(blockers)} failed")
            skip("pgd", "vae skipped")
        elif run("vae", lambda: _probe_vae(state)):
            run("pgd", lambda: _probe_pgd(state["attack"]))
        else:
            skip("pgd", "vae failed")
    if failed:
        code = failed[0][1]
        names = ", ".join(name for name, _ in failed)
        print(
            f"Photo Guard desktop smoke test FAILED: exit {code} (failed: {names})",
            file=sys.stderr,
        )
        return code
    print("Photo Guard desktop smoke test passed")
    return 0


if __name__ == "__main__":
    # P76: the GUI child is this same program; its flag is checked first so the child never
    # falls through to the smoke or the window.
    if _GUI_PROBE_FLAG in sys.argv:
        raise SystemExit(_gui_probe_main())
    if "--smoke-test" in sys.argv:
        raise SystemExit(
            _smoke_test(
                with_photoguard="--with-photoguard" in sys.argv,
                with_gui="--with-gui" in sys.argv,
            )
        )
    from photo_guard.gui import main
    raise SystemExit(main())
