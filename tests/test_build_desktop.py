"""G7 / G5 — ``packaging/build_desktop.py`` is loaded by path and its guards are pinned.

``packaging/`` is not an importable package (PyPA ``packaging`` already owns
that name), so the module is loaded from its path.  The success-path tests stub
``subprocess.run`` and point ``MODEL``/``DIST`` at ``tmp_path``; Nuitka itself
never runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_DESKTOP = ROOT / "packaging" / "build_desktop.py"


def _load():
    spec = importlib.util.spec_from_file_location("pg_build_desktop_f2", BUILD_DESKTOP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_print_version_returns_before_platform_guards(monkeypatch, capsys) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Plan9")

    assert module.main(["--print-version"]) == 0
    assert capsys.readouterr().out.strip() == _version()


def test_non_desktop_platform_is_rejected(monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("must not start Nuitka")
    )

    with pytest.raises(SystemExit, match="Windows and macOS"):
        module.main([])


def test_intel_macos_is_rejected(monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")

    with pytest.raises(SystemExit, match="Apple Silicon"):
        module.main([])


def test_missing_model_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(module, "MODEL", tmp_path / "missing-model")

    with pytest.raises(SystemExit, match="bundled model is missing"):
        module.main([])


def test_incomplete_model_is_rejected(monkeypatch, tmp_path) -> None:
    """Q2/N5: a directory with config.json but no safetensors must not be bundled."""
    module = _load()
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(module, "MODEL", model)
    # A red run on the old code must fail here, not start a real Nuitka build.
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("an incomplete model must not reach Nuitka"),
    )

    with pytest.raises(SystemExit, match="incomplete"):
        module.main([])


def _prepare_success(monkeypatch, tmp_path):
    module = _load()
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "diffusion_pytorch_model.safetensors").write_bytes(b"")
    calls: list[dict] = []

    def fake_run(command, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})

    monkeypatch.setattr(module, "MODEL", model)
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return module, model, calls


def test_windows_command_carries_data_and_version_flags(monkeypatch, tmp_path) -> None:
    module, model, calls = _prepare_success(monkeypatch, tmp_path)
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

    assert module.main([]) == 0
    assert len(calls) == 1
    call = calls[0]
    command = call["command"]
    assert call["cwd"] == module.ROOT and call["check"] is True
    assert command[:3] == [module.sys.executable, "-m", "nuitka"]
    assert "--standalone" in command
    assert f"--include-data-dir={model}=models/sd-vae-ft-mse" in command
    assert any(item.endswith("=licenses") for item in command)
    assert any(item.endswith("=LICENSE") for item in command)
    assert any(item.endswith("=THIRD_PARTY_NOTICES.md") for item in command)
    version = _version()
    assert f"--file-version={version}" in command
    assert f"--product-version={version}" in command
    assert "--output-filename=PhotoGuard.exe" in command
    assert command[-1] == str(module.ROOT / "packaging" / "desktop_entry.py")
    assert (tmp_path / "dist").is_dir()


def test_darwin_command_uses_app_bundle_flags(monkeypatch, tmp_path) -> None:
    module, _, calls = _prepare_success(monkeypatch, tmp_path)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")

    assert module.main([]) == 0
    command = calls[0]["command"]
    version = _version()
    assert "--macos-create-app-bundle" in command
    assert "--macos-app-name=Photo Guard" in command
    assert f"--macos-app-version={version}" in command
    assert "--macos-signed-app-name=com.photoguard.desktop" in command
    assert "--output-filename=PhotoGuard.exe" not in command
