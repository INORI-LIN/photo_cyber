"""G6 — the desktop entry's smoke test must verify the model actually exists.

``--smoke-test`` used to pass whenever ``PHOTOGUARD_MODEL_ID`` was a non-empty string, so a
machine that had the path configured but no model on disk reported success. The entry point
is loaded from its path because ``packaging/`` is not an importable package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from photo_guard import config

_ENTRY = Path(__file__).resolve().parents[1] / "packaging" / "desktop_entry.py"


def _load_entry():
    spec = importlib.util.spec_from_file_location("pg_desktop_entry", _ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert entry._smoke_test() == 0
    assert "smoke test passed" in capsys.readouterr().out
