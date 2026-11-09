"""P23 — the release workflow must resolve ISCC instead of hard-coding one path.

The resolver is deliberately stdlib-only so it can be loaded by path here and
run on the Windows runner without installing anything.  The registry branch is
Windows-only; the fake ``winreg`` module below exercises the two value shapes
without needing a Windows host.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIND_ISCC = ROOT / "packaging" / "find_iscc.py"


def _load():
    spec = importlib.util.spec_from_file_location("pg_find_iscc_f2", FIND_ISCC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_override_wins_and_prints_only_the_path(monkeypatch, tmp_path, capsys) -> None:
    module = _load()
    exe = tmp_path / "ISCC.exe"
    exe.write_text("", encoding="utf-8")
    # Quotes are what Windows installers put in registry values; the resolver accepts them.
    monkeypatch.setenv("ISCC_PATH", f'"{exe}"')
    monkeypatch.setattr(
        module, "discovery_candidates", lambda: pytest.fail("must not fall back")
    )

    assert module.main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(exe.resolve())
    assert captured.err == ""


def test_env_override_missing_exits_two(monkeypatch, tmp_path, capsys) -> None:
    module = _load()
    missing = tmp_path / "missing-ISCC.exe"
    monkeypatch.setenv("ISCC_PATH", str(missing))
    monkeypatch.setattr(
        module, "discovery_candidates", lambda: pytest.fail("must not fall back")
    )

    assert module.main() == 2
    err = capsys.readouterr().err
    assert "ISCC_PATH" in err
    assert str(missing) in err


def test_discovery_order_is_which_registry_defaults(monkeypatch, tmp_path) -> None:
    module = _load()
    which_path = tmp_path / "which" / "ISCC.exe"
    registry_path = tmp_path / "registry" / "ISCC.exe"
    default_path = tmp_path / "default" / "ISCC.exe"

    monkeypatch.setattr(module.shutil, "which", lambda name: str(which_path))
    monkeypatch.setattr(module, "_registry_candidates", lambda: [registry_path])
    monkeypatch.setattr(module, "DEFAULT_INSTALL_DIRS", (default_path,))

    assert module.discovery_candidates() == [which_path, registry_path, default_path]


class _Key:
    def __init__(self, value: str) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def test_registry_reads_install_location_and_app_paths(monkeypatch, tmp_path) -> None:
    module = _load()
    install = tmp_path / "Inno Setup 6"
    install.mkdir()
    app_path_exe = tmp_path / "elsewhere" / "ISCC.exe"

    fake = types.ModuleType("winreg")
    fake.HKEY_LOCAL_MACHINE = 1
    fake.HKEY_CURRENT_USER = 2
    fake.KEY_READ = 0x20019
    fake.KEY_WOW64_32KEY = 0x0200
    fake.KEY_WOW64_64KEY = 0x0100

    def open_key(hive, subkey, reserved, access):
        if hive != fake.HKEY_LOCAL_MACHINE:
            raise OSError("not this hive")
        if "Uninstall" in subkey:
            return _Key(str(install))
        if "App Paths" in subkey:
            return _Key(str(app_path_exe))
        raise OSError("unexpected key")

    def query_value(key, name):
        if name == "InstallLocation":
            return key.value, 1
        if name == "":
            return key.value, 1
        raise OSError("unexpected value")

    fake.OpenKey = open_key
    fake.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(module.sys, "platform", "win32")

    candidates = module._registry_candidates()
    assert install / "ISCC.exe" in candidates
    assert app_path_exe in candidates


def test_registry_is_empty_off_windows(monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    assert module._registry_candidates() == []


def test_not_found_exits_one_and_lists_candidates(monkeypatch, tmp_path, capsys) -> None:
    module = _load()
    monkeypatch.delenv("ISCC_PATH", raising=False)
    candidates = [tmp_path / "a" / "ISCC.exe", tmp_path / "b" / "ISCC.exe"]
    monkeypatch.setattr(module, "discovery_candidates", lambda: candidates)

    assert module.main() == 1
    err = capsys.readouterr().err
    assert "not found" in err
    for candidate in candidates:
        assert str(candidate) in err


def test_default_dirs_are_the_two_program_files_locations() -> None:
    module = _load()
    assert [str(path) for path in module.DEFAULT_INSTALL_DIRS] == [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
