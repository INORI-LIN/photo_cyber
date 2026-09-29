"""G6 / G2 — the desktop entry's smoke test must verify what actually ships.

``--smoke-test`` used to pass whenever ``PHOTOGUARD_MODEL_ID`` was a non-empty string, so a
machine that had the path configured but no model on disk reported success (G6). Since G2 it
also refuses to pass when the licence material is missing from the bundle, because a build
that forgot to include it must not be signed off. The entry point is loaded from its path
because ``packaging/`` is not an importable package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from photo_guard import config

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
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(tmp_path))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(_bundle_root(tmp_path)))
    assert entry._smoke_test() == 0
    assert "smoke test passed" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["LICENSE", "THIRD_PARTY_NOTICES.md"])
def test_smoke_test_rejects_a_bundle_without_licence_material(
    monkeypatch, tmp_path, missing, capsys
) -> None:
    entry = _load_entry()
    root = _bundle_root(tmp_path)
    (root / missing).unlink()
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_ID", str(tmp_path))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(root))
    assert entry._smoke_test() == 4
    assert missing in capsys.readouterr().err
