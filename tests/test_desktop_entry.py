"""G6 / G2 — the desktop entry's smoke test must verify what actually ships.

``--smoke-test`` used to pass whenever ``PHOTOGUARD_MODEL_ID`` was a non-empty string, so a
machine that had the path configured but no model on disk reported success (G6). Since G2 it
also refuses to pass when the licence material is missing from the bundle, because a build
that forgot to include it must not be signed off. The entry point is loaded from its path
because ``packaging/`` is not an importable package.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from photo_guard import config, device

_ENTRY = Path(__file__).resolve().parents[1] / "packaging" / "desktop_entry.py"


def _load_entry():
    spec = importlib.util.spec_from_file_location("pg_desktop_entry", _ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle_root(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("# Third-party notices\n", encoding="utf-8")
    return root


def _complete_model(path: Path) -> Path:
    """Q2/N5: config.json + one safetensors file is the minimum the smoke accepts."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "diffusion_pytorch_model.safetensors").write_bytes(b"")
    return path


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
    model = _complete_model(tmp_path / "model")
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
        config, "PHOTOGUARD_MODEL_ID", str(_complete_model(tmp_path / "model"))
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
    model_dir = _complete_model(contents / "Resources" / "models" / "sd-vae-ft-mse")

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
    model_dir = _complete_model(tmp_path / "model")

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
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(_complete_model(tmp_path / "model")))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    monkeypatch.setattr(
        device,
        "discover_devices",
        lambda **kwargs: [device.DeviceInfo("unsupported", "GPU", supported=False)],
    )

    assert entry._smoke_test() == 3
