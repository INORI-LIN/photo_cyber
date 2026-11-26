"""G6 / G2 — the desktop entry's smoke test must verify what actually ships.

``--smoke-test`` used to pass whenever ``PHOTOGUARD_MODEL_ID`` was a non-empty string, so a
machine that had the path configured but no model on disk reported success (G6). Since G2 it
also refuses to pass when the licence material is missing from the bundle, because a build
that forgot to include it must not be signed off. The entry point is loaded from its path
because ``packaging/`` is not an importable package.

P76: every probe now runs and prints its own verdict (``[smoke] <name>: ok|FAILED|skipped``),
and the exit code is the first failure in the fixed order 2/4/3/1/5/6/7/8/9 — one ~3 h
release round must name every broken probe, not just the first. The GUI probe runs in a
``--smoke-gui-probe`` child process (a Qt platform-plugin failure aborts the process), and a
one-step PGD probe (exit 9) covers the autograd path ``latent_norm`` never touched.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from photo_guard import config, device
from tests.support import complete_model, load_script

_ENTRY = Path(__file__).resolve().parents[1] / "packaging" / "desktop_entry.py"


def _load_entry():
    return load_script(_ENTRY, "pg_desktop_entry")


def _bundle_root(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("# Third-party notices\n", encoding="utf-8")
    return root


def _cpu_only(monkeypatch) -> None:
    """Keep device discovery off torch: the extras legs would otherwise import the real torch
    into this process, and the probe under test is elsewhere."""
    monkeypatch.setattr(
        device, "discover_devices", lambda **_kwargs: [device.DeviceInfo("cpu", "Test CPU")]
    )


def test_smoke_test_rejects_a_missing_model_directory(monkeypatch, tmp_path) -> None:
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(tmp_path / "missing-model"))
    assert entry._smoke_test() == 2


def test_smoke_test_rejects_an_empty_model_id(monkeypatch, capsys) -> None:
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", "")
    assert entry._smoke_test() == 2
    # P76: this exit used to be silent. The empty id must fail before the completeness probe:
    # Path("") is the working directory, not a model.
    err = capsys.readouterr().err
    assert "PHOTOGUARD_MODEL_ID is empty: no SD VAE directory is configured" in err
    assert "model directory missing or incomplete" not in err


def test_smoke_test_passes_with_an_existing_model_directory(monkeypatch, tmp_path, capsys) -> None:
    entry = _load_entry()
    model = complete_model(tmp_path / "model")
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    assert entry._smoke_test() == 0
    assert "smoke test passed" in capsys.readouterr().out


def test_smoke_test_rejects_an_incomplete_model_directory(monkeypatch, tmp_path, capsys) -> None:
    """Q2/N5: a directory with config.json but no weights used to report success."""
    entry = _load_entry()
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))

    assert entry._smoke_test() == 2
    err = capsys.readouterr().err
    assert "incomplete" in err and "safetensors" in err
    # P73: the failure must say which roots were probed — that is what turns a 3-hour
    # macOS build round into a one-look diagnosis.
    assert "probed:" in err


@pytest.mark.parametrize("missing", ["LICENSE", "THIRD_PARTY_NOTICES.md"])
def test_smoke_test_rejects_a_bundle_without_licence_material(
    monkeypatch, tmp_path, missing, capsys
) -> None:
    entry = _load_entry()
    root = _bundle_root(tmp_path)
    (root / missing).unlink()
    monkeypatch.setattr(
        config, "PHOTOGUARD_MODEL_ID", str(complete_model(tmp_path / "model"))
    )
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(root))
    assert entry._smoke_test() == 4
    assert missing in capsys.readouterr().err


def test_smoke_test_resolves_the_macos_bundle_layout(monkeypatch, tmp_path, capsys) -> None:
    """P33: Nuitka keeps data-dirs in ``Contents/Resources`` and data-files in
    ``Contents/MacOS``, so a frozen bundle must pass even though the licence material is not
    in the root the model came from."""
    entry = _load_entry()
    contents = tmp_path / "App.app" / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    (macos / "desktop_entry").write_text("", encoding="utf-8")
    (macos / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (macos / "THIRD_PARTY_NOTICES.md").write_text("# notices\n", encoding="utf-8")
    model_dir = complete_model(contents / "Resources" / "models" / "sd-vae-ft-mse")

    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(macos / "desktop_entry"))
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model_dir))

    assert entry._smoke_test() == 0
    assert "smoke test passed" in capsys.readouterr().out


def test_smoke_test_lists_the_roots_it_looked_in(monkeypatch, tmp_path, capsys) -> None:
    """The failure message must name every candidate root: that diagnostic is what turns a
    40-minute build round into a one-look diagnosis (P33)."""
    entry = _load_entry()
    contents = tmp_path / "App.app" / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    (macos / "desktop_entry").write_text("", encoding="utf-8")
    # The model lives outside the bundle here: this test is about the licence-material
    # roots, and N5 would otherwise stop the smoke at the model check first.
    model_dir = complete_model(tmp_path / "model")

    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(macos / "desktop_entry"))
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model_dir))

    assert entry._smoke_test() == 4
    err = capsys.readouterr().err
    assert "LICENSE" in err and "THIRD_PARTY_NOTICES.md" in err
    assert str(contents / "Resources") in err and str(macos) in err


def test_smoke_test_rejects_a_machine_without_a_cpu_device(monkeypatch, tmp_path, capsys) -> None:
    """A discovery result with only unsupported adapters must fail code 3, not pass."""
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(complete_model(tmp_path / "model")))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    calls: list[dict] = []

    def discover(**kwargs):
        calls.append(kwargs)
        return [device.DeviceInfo("unsupported", "GPU", supported=False)]

    monkeypatch.setattr(device, "discover_devices", discover)

    assert entry._smoke_test() == 3
    # P76: exit 3 used to be silent; the log must show what discovery did find.
    err = capsys.readouterr().err
    assert "no CPU backend found (discovered: " in err
    assert "'GPU'" in err and "supported=False" in err
    # The adapter queries (system_profiler / PowerShell, up to 5 s each) stay out of the smoke.
    assert calls == [{"include_unsupported": False}]


# --- R7/DOC6: the bundle must actually contain the PhotoGuard runtime -----------------


def _prepare_smoke(monkeypatch, tmp_path):
    entry = _load_entry()
    model = complete_model(tmp_path / "model")
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    # The real discovery would import torch into this process; a test that needs another
    # discovery result patches it again after this.
    _cpu_only(monkeypatch)
    return entry


def _fake_runtime(cuda):
    import types

    torch = types.ModuleType("torch")
    torch.__version__ = "2.12.1+cpu"
    torch.version = types.SimpleNamespace(cuda=cuda)
    return {"torch": torch, "diffusers": types.ModuleType("diffusers")}


# --- P69: the smoke must also load the VAE and start Qt ------------------------------


def _working_step(image, cfg):
    """A PGD stand-in: +2 levels with the configured step, +1 from the seeded start alone
    (``step_size == 0``), so the step moves pixels and stays inside the budget."""
    return image + (2 if cfg.step_size > 0 else 1)


def _patch_attack(
    monkeypatch, *, norm: float = 1.25, error: Exception | None = None, attack=None
) -> list:
    """Stand-in for the real VAE: ``complete_model`` ships 0-byte weights by design.

    P76: the smoke builds the attack with its own one-step ``PGDConfig`` and, after
    ``latent_norm``, runs ``attack()`` twice (configured step, then ``step_size=0``).
    ``attack`` replaces :func:`_working_step`; the returned list records every built fake.
    """
    from photo_guard import photoguard

    built: list = []

    class _FakeAttack:
        def __init__(self, cfg):
            self.cfg = cfg if cfg is not None else photoguard.PGDConfig()
            self.device_info = device.DeviceInfo("cpu", "Test CPU")
            self.step_sizes: list[float] = []
            built.append(self)

        def latent_norm(self, _image):
            if error is not None:
                raise error
            return norm

        def attack(self, image):
            self.step_sizes.append(self.cfg.step_size)
            return (attack or _working_step)(image, self.cfg)

    monkeypatch.setattr(photoguard, "build_attack", lambda cfg=None: _FakeAttack(cfg))
    return built


def _fake_qt(*, create_error: Exception | None = None):
    import types

    pyside = types.ModuleType("PySide6")
    pyside.__version__ = "6.11.1"
    widgets = types.ModuleType("PySide6.QtWidgets")

    class QApplication:
        def __init__(self, _argv):
            if create_error is not None:
                raise create_error

        @staticmethod
        def instance():
            return None

        def platformName(self):
            return "offscreen"

    widgets.QApplication = QApplication
    pyside.QtWidgets = widgets
    return {"PySide6": pyside, "PySide6.QtWidgets": widgets}


def _child_result(capsys, returncode: int) -> subprocess.CompletedProcess:
    """What the parent receives from the ``--smoke-gui-probe`` child that just ran in-process."""
    captured = capsys.readouterr()
    return subprocess.CompletedProcess(
        ["<in-process child>"], returncode, captured.out, captured.err
    )


def _fake_gui_child(monkeypatch, entry, outcome) -> list:
    """Replace the GUI child process (P76) by ``outcome``: the CompletedProcess to return, or
    the exception ``subprocess.run`` raises. Only the entry module's reference is swapped, so
    the real ``subprocess`` module stays untouched for everything else."""
    import types

    calls: list = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(
        entry,
        "subprocess",
        types.SimpleNamespace(
            run=run, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired
        ),
    )
    return calls


def test_smoke_with_photoguard_rejects_a_missing_runtime(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "torch", None)

    assert entry._smoke_test(with_photoguard=True) == 5

    assert "runtime is missing" in capsys.readouterr().err


def test_smoke_with_photoguard_passes_on_a_cpu_runtime(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device, "discover_devices", lambda **_kwargs: [device.DeviceInfo("cpu", "Test CPU")]
    )
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch)

    assert entry._smoke_test(with_photoguard=True) == 0

    out = capsys.readouterr().out
    assert "cuda=None" in out
    # P69: the old smoke only imported torch/diffusers; a bundle whose safetensors cannot
    # be parsed still reported success.
    assert "PhotoGuard VAE: loaded" in out
    # P76: latent_norm runs under no_grad; the release log must also show one real PGD
    # step (budget = ceil(8/255 * 255) + 1 for the default epsilon).
    assert "PhotoGuard PGD: 1 step ok (device=cpu, max_delta=2, budget=9)" in out
    assert "[smoke] pgd: ok" in out


def test_smoke_with_photoguard_rejects_cuda_on_windows(monkeypatch, tmp_path, capsys) -> None:
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device, "discover_devices", lambda **_kwargs: [device.DeviceInfo("cpu", "Test CPU")]
    )
    for name, module in _fake_runtime("13.0").items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        entry, "sys", types.SimpleNamespace(platform="win32", stderr=sys.stderr)
    )

    assert entry._smoke_test(with_photoguard=True) == 6

    err = capsys.readouterr().err
    assert "CPU-only" in err
    # P76: the remaining probes now run too (the VAE fails on the fake diffusers here); 6
    # must come from the CUDA policy probe being the first failure, not from anything later.
    assert "[smoke] cpu-only-torch: FAILED (exit 6)" in err
    assert "[smoke] vae: FAILED (exit 8)" in err
    assert "[smoke] pgd: skipped (vae failed)" in err
    assert "Photo Guard desktop smoke test FAILED: exit 6 (failed: cpu-only-torch, vae)" in err


def test_smoke_without_the_flag_ignores_a_missing_runtime(monkeypatch, tmp_path) -> None:
    """The check is opt-in: a core/dev tree without torch still reports success."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "torch", None)

    assert entry._smoke_test() == 0


def test_smoke_with_photoguard_rejects_a_vae_that_cannot_load(
    monkeypatch, tmp_path, capsys
) -> None:
    """P69: importing torch/diffusers is not proof the bundled weights are usable."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device, "discover_devices", lambda **_kwargs: [device.DeviceInfo("cpu", "Test CPU")]
    )
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch, error=RuntimeError("corrupt safetensors"))

    assert entry._smoke_test(with_photoguard=True) == 8
    assert "VAE" in capsys.readouterr().err


def test_any_exception_from_the_vae_load_is_exit_8(monkeypatch, tmp_path, capsys) -> None:
    """safetensors/diffusers raise unrelated types: a probe that mapped only RuntimeError
    would turn a corrupt model into an exit-1 traceback."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    # Patch discovery explicitly like its siblings: the fake torch below has no CUDA surface,
    # so a real discovery would fail the cpu-backend probe first (exit 1, not 8).
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch, error=KeyError("x1 stub: missing tensor"))

    assert entry._smoke_test(with_photoguard=True) == 8

    err = capsys.readouterr().err
    assert "PhotoGuard VAE is missing or unreadable: 'x1 stub: missing tensor'" in err
    assert "Traceback" not in err
    assert "[smoke] vae: FAILED (exit 8)" in err
    assert "[smoke] pgd: skipped (vae failed)" in err


def test_smoke_with_gui_rejects_a_missing_qt_runtime(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")  # _smoke_gui forces it; monkeypatch restores
    monkeypatch.setitem(sys.modules, "PySide6", None)

    # P76 child side: what the --smoke-gui-probe process does, run in-process.
    assert entry._gui_probe_main() == 7
    child = _child_result(capsys, 7)
    assert "GUI runtime is missing" in child.stderr

    # Parent side: the child's output, replayed through the subprocess seam.
    _fake_gui_child(monkeypatch, entry, child)
    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing" in captured.err
    assert child.stderr.strip() in captured.err  # the child's own diagnosis is echoed
    assert "smoke test passed" not in captured.out


def test_smoke_with_gui_rejects_a_qt_that_cannot_start(monkeypatch, tmp_path, capsys) -> None:
    """A bundle with the PySide6 module but no usable platform plugin must fail here."""
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    for name, module in _fake_qt(create_error=RuntimeError("no Qt platform plugin")).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "photo_guard.gui", types.ModuleType("photo_guard.gui"))

    assert entry._gui_probe_main() == 7
    child = _child_result(capsys, 7)
    assert "GUI runtime is missing" in child.stderr

    _fake_gui_child(monkeypatch, entry, child)
    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing" in captured.err
    assert "no Qt platform plugin" in captured.err
    assert "smoke test passed" not in captured.out


def test_smoke_with_gui_passes_with_a_working_runtime(monkeypatch, tmp_path, capsys) -> None:
    import os
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_qt().items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "photo_guard.gui", types.ModuleType("photo_guard.gui"))
    # A stray value (not merely an unset one) must be overridden: the old delenv setup only
    # covered the unset case, and left "offscreen" behind for later tests.
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")

    # P76 child side: what the --smoke-gui-probe process does, run in-process.
    assert entry._gui_probe_main() == 0

    child = _child_result(capsys, 0)
    out = child.stdout
    assert "GUI runtime: PySide6=6.11.1 platform=offscreen" in out
    # The platform is forced, not inherited: a stray value in the smoke environment must
    # not decide whether the release gate passes.
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"

    # Parent side: Qt is not importable here and the environment says xcb again; the child
    # must still get offscreen, and its line must reach the release log verbatim.
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", None)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    calls = _fake_gui_child(monkeypatch, entry, child)

    assert entry._smoke_test(with_gui=True) == 0

    out = capsys.readouterr().out
    assert "GUI runtime: PySide6=6.11.1 platform=offscreen" in out
    assert "[smoke] gui: ok" in out and "smoke test passed" in out
    [(command, kwargs)] = calls
    assert command[-1] == "--smoke-gui-probe"
    assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["capture_output"] is True
    assert (kwargs["encoding"], kwargs["errors"], kwargs["timeout"]) == ("utf-8", "replace", 120)
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"  # the parent never starts Qt itself


def test_smoke_without_the_gui_flag_ignores_a_missing_qt(monkeypatch, tmp_path) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "PySide6", None)

    assert entry._smoke_test() == 0


# --- P76: every probe runs; the first failure in the fixed order is the exit code ------


def test_every_probe_runs_and_the_first_failure_decides_the_exit_code(
    monkeypatch, tmp_path, capsys
) -> None:
    """User decision 2026-11-25: one ~3 h release round must report every broken probe,
    while the exit code keeps the old priority."""
    entry = _load_entry()
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")  # incomplete: 2
    root = _bundle_root(tmp_path)
    (root / "LICENSE").unlink()  # 4
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(root))
    monkeypatch.setattr(device, "discover_devices", lambda **_kwargs: [])  # 3
    monkeypatch.setitem(sys.modules, "torch", None)  # 5
    built = _patch_attack(monkeypatch)

    assert entry._smoke_test(with_photoguard=True) == 2

    captured = capsys.readouterr()
    err = captured.err
    failures = [
        "[smoke] model: FAILED (exit 2)",
        "[smoke] licences: FAILED (exit 4)",
        "[smoke] cpu-backend: FAILED (exit 3)",
        "[smoke] photoguard-runtime: FAILED (exit 5)",
    ]
    positions = [err.index(line) for line in failures]
    assert positions == sorted(positions), err
    # Each probe still prints its own diagnosis.
    assert "probed:" in err and "licence material missing" in err
    assert "no CPU backend found (discovered: nothing)" in err
    assert "runtime is missing" in err
    assert "[smoke] options: ok" in captured.out
    assert "[smoke] vae: skipped (model, photoguard-runtime failed)" in err
    assert "[smoke] pgd: skipped (vae skipped)" in err
    assert built == []
    assert err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 2 "
        "(failed: model, licences, cpu-backend, photoguard-runtime)"
    )
    assert "smoke test passed" not in captured.out


def test_a_licence_failure_outranks_a_missing_cpu_backend(monkeypatch, tmp_path, capsys) -> None:
    entry = _load_entry()
    root = _bundle_root(tmp_path)
    (root / "THIRD_PARTY_NOTICES.md").unlink()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(complete_model(tmp_path / "model")))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(root))
    monkeypatch.setattr(
        device,
        "discover_devices",
        lambda **_kwargs: [device.DeviceInfo("unsupported", "GPU", supported=False)],
    )

    assert entry._smoke_test() == 4

    err = capsys.readouterr().err
    assert "[smoke] licences: FAILED (exit 4)" in err
    assert "[smoke] cpu-backend: FAILED (exit 3)" in err
    assert err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 4 (failed: licences, cpu-backend)"
    )


def test_an_unexpected_probe_error_is_exit_1_and_later_probes_still_run(
    monkeypatch, tmp_path, capsys
) -> None:
    """1 is what the old smoke exited with for an uncaught exception; now it is recorded
    for that probe, with its traceback, and the rest still runs."""
    from photo_guard import pipeline

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch)

    def broken_validate(_options):
        raise KeyError("x1-options-probe")

    monkeypatch.setattr(pipeline, "validate_options", broken_validate)

    assert entry._smoke_test(with_photoguard=True) == 1

    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err
    assert "KeyError: 'x1-options-probe'" in captured.err
    assert "[smoke] options: FAILED (exit 1)" in captured.err
    assert "[smoke] photoguard-runtime: ok" in captured.out
    assert "PhotoGuard VAE: loaded" in captured.out
    assert "PhotoGuard PGD: 1 step ok" in captured.out
    assert captured.err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 1 (failed: options)"
    )


def test_stdout_is_line_buffered_before_the_first_probe(monkeypatch, tmp_path) -> None:
    """A native crash in a later probe (torch, Qt) would otherwise discard the block-buffered
    stdout of a redirected run, and the log would not say which probes had passed."""
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    calls: list[dict] = []

    class _Stdout:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        entry,
        "sys",
        types.SimpleNamespace(platform=sys.platform, stderr=sys.stderr, stdout=_Stdout()),
    )

    assert entry._smoke_test() == 0
    assert calls == [{"line_buffering": True}]


def test_the_probe_order_is_the_exit_code_priority(monkeypatch, tmp_path, capsys) -> None:
    """With everything green, the verdicts appear in the priority order; a reordered probe
    would change which failure decides the exit code without any other symptom."""
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch)
    _fake_gui_child(
        monkeypatch, entry, subprocess.CompletedProcess(["child"], 0, "GUI runtime: x1\n", "")
    )
    monkeypatch.setattr(
        entry,
        "sys",
        types.SimpleNamespace(
            platform="win32", stderr=sys.stderr, executable=sys.executable
        ),
    )

    assert entry._smoke_test(with_photoguard=True, with_gui=True) == 0

    out = capsys.readouterr().out
    verdicts = re.findall(r"^\[smoke\] (\S+): ok$", out, re.MULTILINE)
    assert verdicts == [
        "model", "licences", "cpu-backend", "options", "photoguard-runtime",
        "cpu-only-torch", "gui", "vae", "pgd",
    ]
    assert out.splitlines()[-1] == "Photo Guard desktop smoke test passed"


def test_probes_that_do_not_apply_print_nothing(monkeypatch, tmp_path, capsys) -> None:
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)

    assert entry._smoke_test() == 0
    captured = capsys.readouterr()
    for name in ("model", "licences", "cpu-backend", "options"):
        assert f"[smoke] {name}: ok" in captured.out
    assert captured.out.count("[smoke] ") == 4
    assert "[smoke]" not in captured.err

    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch)
    real_stderr = sys.stderr
    monkeypatch.setattr(entry, "sys", types.SimpleNamespace(platform="linux", stderr=real_stderr))
    assert entry._smoke_test(with_photoguard=True) == 0
    captured = capsys.readouterr()
    assert "cpu-only-torch" not in captured.out + captured.err  # not Windows
    assert "[smoke] gui" not in captured.out + captured.err  # no --with-gui

    monkeypatch.setattr(entry, "sys", types.SimpleNamespace(platform="win32", stderr=real_stderr))
    assert entry._smoke_test(with_photoguard=True) == 0
    assert "[smoke] cpu-only-torch: ok" in capsys.readouterr().out


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_a_missing_runtime_skips_the_vae_and_pgd_probes(
    monkeypatch, tmp_path, capsys, platform
) -> None:
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    monkeypatch.setitem(sys.modules, "torch", None)
    built = _patch_attack(monkeypatch)
    monkeypatch.setattr(entry, "sys", types.SimpleNamespace(platform=platform, stderr=sys.stderr))

    assert entry._smoke_test(with_photoguard=True) == 5

    err = capsys.readouterr().err
    assert "[smoke] photoguard-runtime: FAILED (exit 5)" in err
    assert "[smoke] vae: skipped (photoguard-runtime failed)" in err
    assert "[smoke] pgd: skipped (vae skipped)" in err
    assert built == []
    # The CUDA policy needs torch.version: on Windows it is skipped, elsewhere it never applies.
    skipped_policy = "[smoke] cpu-only-torch: skipped (photoguard-runtime failed)"
    assert (skipped_policy in err) is (platform == "win32")
    assert err.count("cpu-only-torch") == (1 if platform == "win32" else 0)


def test_an_oserror_from_the_runtime_import_is_exit_5(monkeypatch, tmp_path, capsys) -> None:
    """A broken native library surfaces as OSError ("DLL load failed"), not ImportError."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)

    class _BrokenTorch:
        @staticmethod
        def find_spec(name, path=None, target=None):
            if name == "torch":
                raise OSError("x1 stub: native library failed to load")
            return None

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BrokenTorch, *sys.meta_path])

    assert entry._smoke_test(with_photoguard=True) == 5
    assert "PhotoGuard runtime is missing from the bundle: x1 stub: native library" in (
        capsys.readouterr().err
    )


def test_a_model_failure_alone_skips_the_vae_probe(monkeypatch, tmp_path, capsys) -> None:
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", "")
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    built = _patch_attack(monkeypatch)

    assert entry._smoke_test(with_photoguard=True) == 2

    err = capsys.readouterr().err
    assert "[smoke] vae: skipped (model failed)" in err
    assert "[smoke] pgd: skipped (vae skipped)" in err
    assert built == []
    assert err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 2 (failed: model)"
    )


def test_a_licence_failure_does_not_block_the_vae_and_pgd_probes(
    monkeypatch, tmp_path, capsys
) -> None:
    """Only the model and the runtime gate the expensive probes: the point of running on is
    that one broken check must not hide the others."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    (Path(tmp_path) / "bundle" / "LICENSE").unlink()
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch)

    assert entry._smoke_test(with_photoguard=True) == 4

    captured = capsys.readouterr()
    assert "PhotoGuard VAE: loaded" in captured.out
    assert "PhotoGuard PGD: 1 step ok" in captured.out
    assert captured.err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 4 (failed: licences)"
    )


def test_a_vae_failure_skips_the_pgd_probe(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    built = _patch_attack(monkeypatch, error=RuntimeError("corrupt safetensors"))

    assert entry._smoke_test(with_photoguard=True) == 8

    err = capsys.readouterr().err
    assert "PhotoGuard VAE is missing or unreadable: corrupt safetensors" in err
    assert "[smoke] vae: FAILED (exit 8)" in err
    assert "[smoke] pgd: skipped (vae failed)" in err
    assert [fake.step_sizes for fake in built] == [[]]


def test_a_non_finite_latent_norm_is_a_vae_failure(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch, norm=float("nan"))

    assert entry._smoke_test(with_photoguard=True) == 8
    assert "latent norm is not finite: nan" in capsys.readouterr().err


def test_vae_and_pgd_share_one_single_step_attack(monkeypatch, tmp_path, capsys) -> None:
    """One VAE load serves both probes; the config mirrors P69 (device stays auto)."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    built = _patch_attack(monkeypatch)

    assert entry._smoke_test(with_photoguard=True) == 0

    [fake] = built
    assert fake.cfg.steps == 1
    assert fake.cfg.model_id == config.PHOTOGUARD_MODEL_ID
    assert fake.cfg.device == "auto"
    # The configured step first, then the same seed without a step as the reference point.
    assert fake.step_sizes == [config.PHOTOGUARD_STEP_SIZE, 0.0]


def _pgd_raises(image, cfg):
    raise RuntimeError("x1 stub: autograd unavailable")


def _pgd_raises_type_error(image, cfg):
    """Not a RuntimeError: autograd, device and dtype failures raise unrelated types."""
    raise TypeError("x1 stub: not a RuntimeError")


def _pgd_over_budget(image, cfg):
    return np.clip(image.astype(np.int16) + 40, 0, 255).astype(np.uint8)


def _pgd_stuck(image, cfg):
    return image + 1  # identical with and without the step: the gradient moved nothing


def _pgd_untouched(image, cfg):
    return image.copy()


def _pgd_float(image, cfg):
    return image.astype(np.float32) + (2 if cfg.step_size > 0 else 1)


def _pgd_cropped(image, cfg):
    return _working_step(image, cfg)[:4]


def _pgd_float_start(image, cfg):
    """Only the reference point is wrong: a uint8 step next to a float starting point."""
    return _working_step(image, cfg) if cfg.step_size > 0 else image.astype(np.float32)


@pytest.mark.parametrize(
    ("step", "detail"),
    [
        (_pgd_raises, "autograd unavailable"),
        (_pgd_over_budget, "budget"),
        (_pgd_stuck, "starting point"),
        (_pgd_untouched, "budget"),
        (_pgd_float, "the stepped output is float32"),
        (_pgd_cropped, "(4, 8, 3)"),
        (_pgd_float_start, "the starting point is float32"),
        (_pgd_raises_type_error, "x1 stub: not a RuntimeError"),
    ],
    ids=[
        "raises", "over-budget", "does-not-move", "no-delta", "wrong-dtype", "wrong-shape",
        "wrong-start-dtype", "raises-type-error",
    ],
)
def test_a_broken_pgd_step_fails_with_exit_9(
    monkeypatch, tmp_path, capsys, step, detail
) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(monkeypatch, attack=step)

    assert entry._smoke_test(with_photoguard=True) == 9

    captured = capsys.readouterr()
    assert "PhotoGuard VAE: loaded" in captured.out
    assert "PhotoGuard PGD: 1 step ok" not in captured.out
    failure = next(
        line for line in captured.err.splitlines()
        if line.startswith("PhotoGuard PGD step failed: ")
    )
    assert detail in failure
    assert "[smoke] pgd: FAILED (exit 9)" in captured.err
    assert captured.err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 9 (failed: pgd)"
    )
    assert "smoke test passed" not in captured.out


@pytest.mark.parametrize(("delta", "expected"), [(9, 0), (10, 9)], ids=["at-budget", "one-over"])
def test_the_pgd_budget_is_inclusive(monkeypatch, tmp_path, capsys, delta, expected) -> None:
    """``ceil(8/255 * 255) + 1`` = 9 levels: the +1 is the uint8 rounding allowance."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    for name, module in _fake_runtime(None).items():
        monkeypatch.setitem(sys.modules, name, module)
    _patch_attack(
        monkeypatch, attack=lambda image, cfg: image + (delta if cfg.step_size > 0 else 1)
    )

    assert entry._smoke_test(with_photoguard=True) == expected

    out = capsys.readouterr().out
    assert ("PhotoGuard PGD: 1 step ok" in out) is (expected == 0)


# --- P76: the GUI probe's child process ------------------------------------------------


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (-6, ""),
        (3, ""),
        (-11, "GUI runtime: PySide6=6.11.1 platform=offscreen\n"),
        (0xC0000005, ""),
    ],
    ids=["abort", "windows-abort", "after-the-success-line", "windows-access-violation"],
)
def test_a_crashing_gui_child_is_exit_7(
    monkeypatch, tmp_path, capsys, returncode, stdout
) -> None:
    """qFatal (e.g. no usable platform plugin) aborts: SIGABRT on POSIX, 3 on Windows. In
    process, that killed the whole smoke before it printed a verdict. A crash after the
    success line (Qt teardown) still fails: the line alone only proves that Qt started. A
    Windows access violation arrives as a large positive code; of the non-zero codes only 1,
    Python's own uncaught-exception status, is not a crash (see the exit-1 test below)."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    _fake_gui_child(
        monkeypatch,
        entry,
        subprocess.CompletedProcess(["child"], returncode, stdout, "x1 stub: qFatal\n"),
    )

    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "x1 stub: qFatal" in captured.err
    assert "GUI runtime is missing from the bundle: " in captured.err
    assert f"returncode {returncode}" in captured.err
    assert "[smoke] gui: FAILED (exit 7)" in captured.err
    assert "smoke test passed" not in captured.out


@pytest.mark.parametrize(
    "error", [ImportError("x1"), OSError("x1"), RuntimeError("x1")], ids=lambda e: type(e).__name__
)
def test_the_gui_child_maps_the_old_exceptions_to_7(monkeypatch, capsys, error) -> None:
    """The child keeps the mapping the in-process probe had (missing module, broken native
    library, Qt that will not start)."""
    entry = _load_entry()

    def broken() -> None:
        raise error

    monkeypatch.setattr(entry, "_smoke_gui", broken)

    assert entry._gui_probe_main() == 7
    assert "GUI runtime is missing from the bundle: x1" in capsys.readouterr().err


def test_the_gui_child_does_not_swallow_a_programming_error(monkeypatch) -> None:
    """Anything else keeps its traceback and Python's exit 1, which the parent reports as 1:
    the old in-process probe's uncaught exception was exit 1 too (strict parity for Python
    failures; 7 is for Qt/native failures)."""
    entry = _load_entry()

    def broken() -> None:
        raise ValueError("x1 stub: not a Qt problem")

    monkeypatch.setattr(entry, "_smoke_gui", broken)

    with pytest.raises(ValueError, match="not a Qt problem"):
        entry._gui_probe_main()


_CHILD_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "desktop_entry.py", line 1, in <module>\n'
    "AttributeError: x1 stub: not a Qt problem\n"
)


def test_a_gui_child_that_raises_is_exit_1(monkeypatch, tmp_path, capsys) -> None:
    """Strict parity (lead decision): returncode 1 is what the old in-process probe exited
    with for a Python-level failure; signals, Windows' abort code 3, other codes, hangs and
    launch errors stay 7. The message names both causes of an exit 1, since SystemExit(1)
    and an interpreter start-up failure print no traceback."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _fake_gui_child(
        monkeypatch, entry, subprocess.CompletedProcess(["child"], 1, "", _CHILD_TRACEBACK)
    )

    assert entry._smoke_test(with_gui=True) == 1

    captured = capsys.readouterr()
    message = (
        "GUI runtime is missing from the bundle: the GUI probe exited 1 "
        "(an uncaught exception or SystemExit; its output is above)"
    )
    assert _CHILD_TRACEBACK in captured.err
    assert message in captured.err.splitlines()
    assert captured.err.index(_CHILD_TRACEBACK) < captured.err.index(message)
    assert "[smoke] gui: FAILED (exit 1)" in captured.err
    assert captured.err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 1 (failed: gui)"
    )
    assert "smoke test passed" not in captured.out


def test_a_gui_child_without_its_success_line_is_exit_7(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    _fake_gui_child(monkeypatch, entry, subprocess.CompletedProcess(["child"], 0, "", ""))

    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing from the bundle: " in captured.err
    assert "returncode 0" in captured.err
    assert "'GUI runtime:'" in captured.err  # names the line it did not see
    assert "[smoke] gui: FAILED (exit 7)" in captured.err
    assert "smoke test passed" not in captured.out


@pytest.mark.parametrize(
    ("partial", "partial_err"),
    [
        (b"GUI runtime: PySide6=6.11.1 platform=offscreen\n", None),
        (None, None),
        (b"out\n", b"x1 stub: gui-boom\n"),
    ],
    ids=["bytes", "none", "stderr"],
)
def test_a_hanging_gui_child_is_exit_7(
    monkeypatch, tmp_path, capsys, partial, partial_err
) -> None:
    """``TimeoutExpired`` carries raw bytes on POSIX (or nothing); a hang after the success
    line is still a failure, and what the child wrote to stderr before it hung is the
    diagnosis."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    _fake_gui_child(
        monkeypatch,
        entry,
        subprocess.TimeoutExpired(["child"], 120, output=partial, stderr=partial_err),
    )

    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing from the bundle: " in captured.err
    assert "120 s" in captured.err
    if partial is not None:
        assert partial.decode("ascii") in captured.out
    if partial_err is not None:
        echoed = partial_err.decode("ascii")
        assert echoed in captured.err
        assert captured.err.index(echoed) < captured.err.index("GUI runtime is missing")
    assert "[smoke] gui: ok" not in captured.out
    assert "[smoke] gui: FAILED (exit 7)" in captured.err
    assert "smoke test passed" not in captured.out


def test_a_gui_child_that_cannot_be_started_is_exit_7(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    _fake_gui_child(monkeypatch, entry, FileNotFoundError(2, "x1 stub: no such program"))

    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing from the bundle: " in captured.err
    assert "x1 stub: no such program" in captured.err
    assert "[smoke] gui: FAILED (exit 7)" in captured.err
    assert "smoke test passed" not in captured.out


def test_the_gui_child_output_reaches_the_log_as_ascii(monkeypatch, tmp_path, capsys) -> None:
    """A Windows console redirected to a file encodes with cp1252 and raises on anything
    else; a Qt/Chinese message from the child must not turn a pass into a crash."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    out_text = "GUI runtime: PySide6=6.11.1 platform=offscreen\n\u7a97\u53e3\n"
    _fake_gui_child(
        monkeypatch,
        entry,
        subprocess.CompletedProcess(["child"], 0, out_text, "\u8b66\u544a\n"),
    )

    assert entry._smoke_test(with_gui=True) == 0

    captured = capsys.readouterr()
    assert captured.out.isascii() and captured.err.isascii()
    assert "GUI runtime: PySide6=6.11.1 platform=offscreen\n" in captured.out
    assert "\\u7a97\\u53e3" in captured.out and "\\u8b66\\u544a" in captured.err
    assert "[smoke] gui: ok" in captured.out


def test_the_gui_probe_command_in_a_source_tree(monkeypatch) -> None:
    entry = _load_entry()
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert entry._gui_probe_command() == [sys.executable, str(_ENTRY), "--smoke-gui-probe"]


def test_the_gui_probe_command_inside_a_bundle(monkeypatch, tmp_path) -> None:
    """With no Nuitka builtin (PyInstaller-style freezers set ``sys.frozen``), and in Nuitka
    once ``multiprocessing`` is imported, ``sys.executable`` is the bundle's own program;
    ``__file__`` names no script there, so the flag goes straight to the executable."""
    entry = _load_entry()
    exe = tmp_path / "dist" / "PhotoGuard.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    assert entry._gui_probe_command() == [str(exe.resolve()), "--smoke-gui-probe"]


def test_the_gui_probe_command_before_multiprocessing_is_imported(monkeypatch, tmp_path) -> None:
    """Nuitka standalone: ``sys.executable`` starts as ``<binary dir>/python.exe`` (the build
    interpreter's basename, not shipped) and names the program only once ``multiprocessing``
    is imported, which the release smoke got from torch in the cpu-backend probe. The
    command must come from the builtin ``__nuitka_binary_exe``, not from that side effect."""
    import builtins

    from photo_guard import resources

    entry = _load_entry()
    exe = tmp_path / "dist" / "PhotoGuard.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.delattr(sys, "frozen", raising=False)  # Nuitka sets no sys.frozen ...
    monkeypatch.setattr(resources, "__compiled__", True, raising=False)  # ... but this
    monkeypatch.setattr(sys, "executable", str(exe.parent / "python.exe"))
    monkeypatch.setattr(builtins, "__nuitka_binary_exe", str(exe), raising=False)

    assert not Path(sys.executable).exists()
    assert entry._gui_probe_command() == [str(exe.resolve()), "--smoke-gui-probe"]


def _shadow_pyside6(monkeypatch, tmp_path, body: str) -> None:
    """Give every child process a ``PySide6`` package whose ``__init__`` is ``body``.

    The stub directory is prepended to ``PYTHONPATH`` rather than replacing it: a run from a
    copy of the repository (red or mutation overlays) puts that copy's ``src`` there, and
    the child must keep importing it instead of the editable install's ``photo_guard``.
    """
    import os

    stub = tmp_path / "stub" / "PySide6"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text(body, encoding="utf-8")
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(filter(None, [str(stub.parent), os.environ.get("PYTHONPATH")])),
    )


def test_a_real_gui_child_without_qt_is_exit_7(monkeypatch, tmp_path, capsys) -> None:
    """End to end through a real child process, no Qt needed: a PySide6 package that refuses
    to import shadows any installed copy through PYTHONPATH, so this also runs on the core
    legs (and the ``--smoke-gui-probe`` dispatch is what prints the echoed line)."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    _shadow_pyside6(
        monkeypatch, tmp_path, 'raise ImportError("x1 stub: PySide6 refuses to import")\n'
    )

    assert entry._smoke_test(with_gui=True) == 7

    captured = capsys.readouterr()
    assert "GUI runtime is missing from the bundle: x1 stub: PySide6 refuses to import" in (
        captured.err
    )
    assert "[smoke] gui: FAILED (exit 7)" in captured.err
    assert "smoke test passed" not in captured.out


def test_a_real_gui_child_that_raises_is_exit_1(monkeypatch, tmp_path, capsys) -> None:
    """The parity code is what a real child returns: an exception the child does not map
    (here an AttributeError while importing PySide6) is Python's uncaught exit 1."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _shadow_pyside6(
        monkeypatch, tmp_path, 'raise AttributeError("x1 stub: not a Qt problem")\n'
    )

    assert entry._smoke_test(with_gui=True) == 1

    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err
    assert "AttributeError: x1 stub: not a Qt problem" in captured.err
    assert "the GUI probe exited 1 (an uncaught exception or SystemExit; its output is above)" in (
        captured.err
    )
    assert "[smoke] gui: FAILED (exit 1)" in captured.err
    assert captured.err.splitlines()[-1] == (
        "Photo Guard desktop smoke test FAILED: exit 1 (failed: gui)"
    )
    assert "smoke test passed" not in captured.out


@pytest.mark.gui
@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed (desktop extra: uv sync --extra desktop); the no-Qt "
    "child path is covered by test_a_real_gui_child_without_qt_is_exit_7",
)
def test_a_real_gui_child_starts_qt_offscreen(monkeypatch, tmp_path, capsys) -> None:
    """The real thing: a child process starts Qt and imports the window module. The parent's
    stray platform must not leak into the child (xcb would abort on a headless runner)."""
    entry = _prepare_smoke(monkeypatch, tmp_path)
    _cpu_only(monkeypatch)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")

    assert entry._smoke_test(with_gui=True) == 0

    out = capsys.readouterr().out
    assert re.search(r"^GUI runtime: PySide6=\S+ platform=offscreen$", out, re.MULTILINE), out
    assert "[smoke] gui: ok" in out
    assert "smoke test passed" in out
