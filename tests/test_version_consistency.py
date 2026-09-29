"""G5 — the version lives in ``pyproject.toml`` and nowhere else.

The desktop build, the macOS bundle, the Windows installer and the tag gate all take it from
there; a literal creeping back in is exactly the drift this file exists to catch. ``packaging/``
is not an importable package on purpose, so the module under test is loaded from its path.
"""
from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DESKTOP = REPO_ROOT / "packaging" / "build_desktop.py"
ISS = REPO_ROOT / "packaging" / "windows-installer.iss"
VERSION_LITERAL = re.compile(r"\b\d+\.\d+\.\d+\b")


def _load_build_desktop():
    spec = importlib.util.spec_from_file_location("pg_build_desktop", BUILD_DESKTOP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_packaging_reader_matches_pyproject() -> None:
    assert _load_build_desktop().project_version() == _pyproject_version()


def test_build_desktop_has_no_version_literal() -> None:
    source = BUILD_DESKTOP.read_text(encoding="utf-8")
    assert VERSION_LITERAL.findall(source) == []


def test_iss_has_no_version_literal_and_still_uses_the_define() -> None:
    source = ISS.read_text(encoding="utf-8")
    assert VERSION_LITERAL.findall(source) == []
    assert "AppVersion={#MyAppVersion}" in source
    # The define is required, and a missing one must abort the compile loudly.
    assert "#ifndef MyAppVersion" in source and "#error" in source


def test_version_is_nuitka_compatible() -> None:
    """Nuitka's --file-version accepts at most four dotted components."""
    assert re.fullmatch(r"\d+(\.\d+){1,3}", _pyproject_version())
