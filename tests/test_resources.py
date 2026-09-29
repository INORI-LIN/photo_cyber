"""G7 / P33 — resource location across the source tree and the two bundle layouts.

``resources.py`` was the zero-coverage module G7 named, and P33 made it load-bearing: a
macOS bundle does not keep Nuitka's payload in one directory (``--include-data-dir`` lands in
``Contents/Resources``, ``--include-data-files`` next to the executable in
``Contents/MacOS`` — measured on macos-15, ``docs/fix-plan.md`` §9.9), so the module now
probes candidate roots instead of assuming one. These tests build both layouts on disk and
pin which root each lookup resolves to; no macOS runner needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from photo_guard import resources


def _frozen_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(resources_dir, macos_dir)`` — a bundle with an executable but no payload."""
    contents = tmp_path / "App.app" / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    (macos / "desktop_entry").write_text("", encoding="utf-8")
    resources_dir = contents / "Resources"
    resources_dir.mkdir()
    return resources_dir, macos


def _freeze(monkeypatch, macos: Path, executable_name: str = "desktop_entry") -> None:
    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(macos / executable_name))


def test_candidate_roots_cover_both_bundle_directories(monkeypatch, tmp_path) -> None:
    """P33: Resources first, then the executable's directory."""
    resources_dir, macos = _frozen_bundle(tmp_path)
    _freeze(monkeypatch, macos)

    assert resources.candidate_roots() == (resources_dir, macos)


def test_the_mixed_layout_that_shipped_is_resolved_per_item(monkeypatch, tmp_path) -> None:
    """The measured layout: models/ in Resources, licence material in MacOS.

    A single root cannot serve both — that is the whole of P33 — so each lookup picks the
    root that actually holds its item.
    """
    resources_dir, macos = _frozen_bundle(tmp_path)
    (resources_dir / "models" / "sd-vae-ft-mse").mkdir(parents=True)
    (macos / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (macos / "THIRD_PARTY_NOTICES.md").write_text("# notices\n", encoding="utf-8")
    _freeze(monkeypatch, macos)

    assert resources.find_resource("models") == resources_dir / "models"
    assert resources.find_resource("models", "sd-vae-ft-mse") == (
        resources_dir / "models" / "sd-vae-ft-mse"
    )
    assert resources.find_resource("LICENSE") == macos / "LICENSE"
    assert resources.find_resource("THIRD_PARTY_NOTICES.md") == macos / "THIRD_PARTY_NOTICES.md"
    assert resources.find_resource("config.json") is None


def test_everything_in_resources_is_resolved(monkeypatch, tmp_path) -> None:
    resources_dir, macos = _frozen_bundle(tmp_path)
    (resources_dir / "models").mkdir()
    (resources_dir / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    _freeze(monkeypatch, macos)

    assert resources.find_resource("models") == resources_dir / "models"
    assert resources.find_resource("LICENSE") == resources_dir / "LICENSE"


def test_everything_next_to_the_executable_is_resolved(monkeypatch, tmp_path) -> None:
    """The flat layout Windows produces (and the macOS bundle would if Nuitka moved data)."""
    _, macos = _frozen_bundle(tmp_path)
    (macos / "models").mkdir()
    (macos / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    _freeze(monkeypatch, macos)

    assert resources.find_resource("models") == macos / "models"
    assert resources.find_resource("LICENSE") == macos / "LICENSE"


def test_a_missing_item_is_reported_as_none(monkeypatch, tmp_path) -> None:
    _, macos = _frozen_bundle(tmp_path)
    _freeze(monkeypatch, macos)

    assert resources.find_resource("LICENSE") is None
    assert resources.application_root() == resources.candidate_roots()[0]


def test_the_override_is_the_only_candidate(monkeypatch, tmp_path) -> None:
    """``PHOTO_GUARD_RESOURCE_DIR`` (desktop smoke tests, packaging tests) stays a single
    root, so the probe never escapes the directory a caller pinned."""
    override = tmp_path / "pinned"
    override.mkdir()
    (override / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", str(override))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "App.app" / "Contents" / "MacOS" / "x"))

    assert resources.candidate_roots() == (override,)
    assert resources.find_resource("LICENSE") == override / "LICENSE"


def test_the_source_tree_layout_is_unchanged(monkeypatch) -> None:
    """Non-frozen runs still resolve to the repository root, and the probe agrees with it."""
    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)

    roots = resources.candidate_roots()
    assert len(roots) == 1
    assert resources.find_resource("pyproject.toml") == roots[0] / "pyproject.toml"
