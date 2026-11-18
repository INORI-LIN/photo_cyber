"""G6 / G2 — the desktop entry's smoke test must verify what actually ships.

``--smoke-test`` used to pass whenever ``PHOTOGUARD_MODEL_ID`` was a non-empty string, so a
machine that had the path configured but no model on disk reported success (G6). Since G2 it
also refuses to pass when the licence material is missing from the bundle, because a build
that forgot to include it must not be signed off. The entry point is loaded from its path
because ``packaging/`` is not an importable package.
"""
from __future__ import annotations

import sys
from pathlib import Path

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


def test_smoke_test_rejects_a_missing_model_directory(monkeypatch, tmp_path) -> None:
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(tmp_path / "missing-model"))
    assert entry._smoke_test() == 2


def test_smoke_test_rejects_an_empty_model_id(monkeypatch) -> None:
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", "")
    assert entry._smoke_test() == 2


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


def test_smoke_test_rejects_a_machine_without_a_cpu_device(monkeypatch, tmp_path) -> None:
    """A discovery result with only unsupported adapters must fail code 3, not pass."""
    entry = _load_entry()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(complete_model(tmp_path / "model")))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    monkeypatch.setattr(
        device,
        "discover_devices",
        lambda **kwargs: [device.DeviceInfo("unsupported", "GPU", supported=False)],
    )

    assert entry._smoke_test() == 3


# --- R7/DOC6: the bundle must actually contain the PhotoGuard runtime -----------------


def _prepare_smoke(monkeypatch, tmp_path):
    entry = _load_entry()
    model = complete_model(tmp_path / "model")
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(model))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    return entry


def _fake_runtime(cuda):
    import types

    torch = types.ModuleType("torch")
    torch.__version__ = "2.12.1+cpu"
    torch.version = types.SimpleNamespace(cuda=cuda)
    return {"torch": torch, "diffusers": types.ModuleType("diffusers")}


# --- P69: the smoke must also load the VAE and start Qt ------------------------------


def _patch_attack(monkeypatch, *, norm: float = 1.25, error: Exception | None = None) -> None:
    """Stand-in for the real VAE: ``complete_model`` ships 0-byte weights by design."""
    from photo_guard import photoguard

    class _FakeAttack:
        def latent_norm(self, _image):
            if error is not None:
                raise error
            return norm

    monkeypatch.setattr(photoguard, "build_attack", lambda: _FakeAttack())


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

    assert "CPU-only" in capsys.readouterr().err


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


def test_smoke_with_gui_rejects_a_missing_qt_runtime(monkeypatch, tmp_path, capsys) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "PySide6", None)

    assert entry._smoke_test(with_gui=True) == 7

    assert "GUI runtime is missing" in capsys.readouterr().err


def test_smoke_with_gui_rejects_a_qt_that_cannot_start(monkeypatch, tmp_path, capsys) -> None:
    """A bundle with the PySide6 module but no usable platform plugin must fail here."""
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    for name, module in _fake_qt(create_error=RuntimeError("no Qt platform plugin")).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "photo_guard.gui", types.ModuleType("photo_guard.gui"))

    assert entry._smoke_test(with_gui=True) == 7
    assert "GUI runtime is missing" in capsys.readouterr().err


def test_smoke_with_gui_passes_with_a_working_runtime(monkeypatch, tmp_path, capsys) -> None:
    import os
    import types

    entry = _prepare_smoke(monkeypatch, tmp_path)
    for name, module in _fake_qt().items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "photo_guard.gui", types.ModuleType("photo_guard.gui"))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    assert entry._smoke_test(with_gui=True) == 0

    out = capsys.readouterr().out
    assert "GUI runtime: PySide6=6.11.1 platform=offscreen" in out
    # The platform is forced, not inherited: a stray value in the smoke environment must
    # not decide whether the release gate passes.
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"


def test_smoke_without_the_gui_flag_ignores_a_missing_qt(monkeypatch, tmp_path) -> None:
    entry = _prepare_smoke(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "PySide6", None)

    assert entry._smoke_test() == 0
