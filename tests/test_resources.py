"""G7 / P33 — resource location across the source tree and the two bundle layouts.

``resources.py`` was the zero-coverage module G7 named, and P33 made it load-bearing: a
macOS bundle does not keep Nuitka's payload in one directory (``--include-data-dir`` lands in
``Contents/Resources``, ``--include-data-files`` next to the executable in
``Contents/MacOS`` — measured on macos-15, ``docs/fix-plan.md`` §9.9), so the module now
probes candidate roots instead of assuming one. These tests build both layouts on disk and
pin which root each lookup resolves to; no macOS runner needed.
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

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


def test_compiled_marker_uses_the_frozen_branch(monkeypatch, tmp_path) -> None:
    """Nuitka sets ``__compiled__`` in the module globals even without ``sys.frozen``."""
    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(resources, "__compiled__", True, raising=False)
    exe = tmp_path / "dist" / "desktop_entry.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))

    assert resources.candidate_roots() == (exe.parent.resolve(),)


def test_windows_flat_layout_resolves_beside_the_executable(monkeypatch, tmp_path) -> None:
    """The Windows standalone build keeps data next to the executable (no app bundle)."""
    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(resources, "__compiled__", raising=False)
    exe = tmp_path / "dist" / "desktop_entry.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    (exe.parent / "models").mkdir()
    (exe.parent / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))

    root = exe.parent.resolve()
    assert resources.candidate_roots() == (root,)
    assert resources.find_resource("models") == root / "models"
    assert resources.find_resource("LICENSE") == root / "LICENSE"


def test_override_expands_user(monkeypatch, tmp_path) -> None:
    """``PHOTO_GUARD_RESOURCE_DIR=~/...`` must expand rather than create a literal ``~``."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PHOTO_GUARD_RESOURCE_DIR", "~/pinned")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    assert resources.candidate_roots() == ((home / "pinned").resolve(),)


# --- P76: one "am I in a bundle" predicate --------------------------------------------


def test_is_bundled_is_true_when_frozen(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(resources, "__compiled__", raising=False)

    assert resources.is_bundled() is True


def test_is_bundled_honours_the_nuitka_marker(monkeypatch) -> None:
    """Nuitka does not set ``sys.frozen``; it puts ``__compiled__`` in the module globals."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(resources, "__compiled__", True, raising=False)

    assert resources.is_bundled() is True


def test_is_bundled_is_false_in_the_source_tree(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(resources, "__compiled__", raising=False)

    assert resources.is_bundled() is False


def test_candidate_roots_ask_is_bundled(monkeypatch, tmp_path) -> None:
    """P76: the resource lookup and ``photoguard``'s runtime error share one predicate, so
    they can never disagree about whether the process runs from a bundle."""
    resources_dir, macos = _frozen_bundle(tmp_path)
    monkeypatch.delenv("PHOTO_GUARD_RESOURCE_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(resources, "__compiled__", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(macos / "desktop_entry"))

    monkeypatch.setattr(resources, "is_bundled", lambda: True)
    assert resources.candidate_roots() == (resources_dir, macos)

    monkeypatch.setattr(resources, "is_bundled", lambda: False)
    assert resources.candidate_roots() == (Path(resources.__file__).resolve().parents[2],)


# --- P76: the program path must not depend on multiprocessing having been imported ----


def test_program_path_prefers_the_nuitka_binary(monkeypatch, tmp_path) -> None:
    """Nuitka standalone: until ``multiprocessing`` is imported, ``sys.executable`` is
    ``<binary dir>/<build interpreter's basename>``, a ``python.exe`` Nuitka does not ship.
    The builtin ``__nuitka_binary_exe`` names the real program from the start (the ``..``
    pins the resolution)."""
    exe = tmp_path / "dist" / "PhotoGuard.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe.parent / "python.exe"))
    monkeypatch.setattr(
        builtins, "__nuitka_binary_exe", str(exe.parent / ".." / "dist" / exe.name), raising=False
    )

    assert resources.program_path() == exe.resolve()


@pytest.mark.parametrize("builtin", [None, ""], ids=["absent", "empty"])
def test_program_path_falls_back_to_sys_executable(monkeypatch, tmp_path, builtin) -> None:
    """Source trees and PyInstaller-style freezers have no Nuitka builtin; there
    ``sys.executable`` is the program."""
    exe = tmp_path / "bin" / "python"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    if builtin is None:
        monkeypatch.delattr(builtins, "__nuitka_binary_exe", raising=False)
    else:
        monkeypatch.setattr(builtins, "__nuitka_binary_exe", builtin, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe.parent / ".." / "bin" / exe.name))

    assert resources.program_path() == exe.resolve()


@pytest.mark.parametrize(
    "interpreter",
    ["MacOS/python", "build/python"],
    ids=["before-multiprocessing", "unrelated-directory"],
)
def test_a_bundle_takes_its_roots_from_the_program_path(
    monkeypatch, tmp_path, interpreter
) -> None:
    """The roots come from :func:`resources.program_path`. ``before-multiprocessing`` is
    Nuitka's real starting state (a missing ``python`` beside the binary); in
    ``unrelated-directory`` only the builtin can yield the bundle's layout."""
    resources_dir, macos = _frozen_bundle(tmp_path)
    _freeze(monkeypatch, macos)
    contents = macos.parent
    monkeypatch.setattr(sys, "executable", str(contents / interpreter))
    monkeypatch.setattr(
        builtins, "__nuitka_binary_exe", str(macos / "desktop_entry"), raising=False
    )

    assert not Path(sys.executable).exists()
    assert resources.candidate_roots() == (resources_dir, macos)


# --- P73: a relocated .cache subtree must not shadow the real model --------------------


def test_model_dir_resolution_prefers_the_complete_root(monkeypatch, tmp_path) -> None:
    """Nuitka moves dotted subtrees (``.cache/huggingface``) to Resources and symlinks them.

    That creates an otherwise empty ``Resources/models``; probing for the directory alone
    picked it and reported the bundle's model as incomplete although ``MacOS/models`` held
    the weights (release run 44445013882).
    """
    from photo_guard import config

    resources_dir, macos = _frozen_bundle(tmp_path)
    (resources_dir / "models" / "sd-vae-ft-mse" / ".cache" / "huggingface").mkdir(
        parents=True
    )
    complete = macos / "models" / "sd-vae-ft-mse"
    complete.mkdir(parents=True)
    (complete / "config.json").write_text("{}", encoding="utf-8")
    (complete / "diffusion_pytorch_model.safetensors").write_bytes(b"")
    _freeze(monkeypatch, macos)

    assert config._resolve_models_dir() == macos / "models"


def test_model_dir_resolution_keeps_the_old_fallback_when_nothing_is_complete(
    monkeypatch, tmp_path
) -> None:
    """A bundle with no usable weights must still resolve to a path the smoke can name."""
    from photo_guard import config

    resources_dir, macos = _frozen_bundle(tmp_path)
    (resources_dir / "models" / "sd-vae-ft-mse").mkdir(parents=True)
    _freeze(monkeypatch, macos)

    assert config._resolve_models_dir() == resources_dir / "models"
