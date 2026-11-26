"""G7 / G5 / P74 — ``packaging/build_desktop.py`` is loaded by path and its guards are pinned.

``packaging/`` is not an importable package (PyPA ``packaging`` already owns
that name), so the module is loaded from its path.  The success-path tests stub
``subprocess.run`` and point ``MODEL``/``DIST`` at ``tmp_path``; Nuitka itself
never runs.  They also stub the P74 metadata pre-check, because the core legs have no
torch to find; the pre-check's own cases use core dependencies (numpy and
opencv-python-headless) instead.
"""
from __future__ import annotations

import ast
from pathlib import Path
import tomllib

import pytest

from tests.support import complete_model, load_script

ROOT = Path(__file__).resolve().parents[1]
BUILD_DESKTOP = ROOT / "packaging" / "build_desktop.py"

# P74: the measured runtime-metadata closure, pinned here as well as in
# ``build_desktop.RUNTIME_METADATA``: the probe that proves it (test_bundle_metadata.py) skips
# on the core legs, so this is what notices an entry being dropped there.
EXPECTED_RUNTIME_METADATA = {
    "requests": ("requests",),
    "filelock": ("filelock",),
    "numpy": ("numpy",),
    "torch": ("functorch", "torch", "torchgen"),
    "accelerate": ("accelerate",),
    "safetensors": ("safetensors",),
    "opencv-python-headless": ("cv2",),
    "Jinja2": ("jinja2",),
}
# Every module above except numpy. --include-module outranks Nuitka's anti-bloat plugin
# (importing/Recursion.py, _decideRecursion), so --include-module=numpy would override the
# anti-bloat rule that keeps numpy.distutils and its setuptools chain out of the bundle.
EXPECTED_INCLUDE_MODULES = (
    "requests",
    "filelock",
    "functorch",
    "torch",
    "torchgen",
    "accelerate",
    "safetensors",
    "cv2",
    "jinja2",
)


def _load():
    return load_script(BUILD_DESKTOP, "pg_build_desktop_f2")


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_print_version_returns_before_platform_guards(monkeypatch, capsys) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Plan9")
    # P74: the release workflow asks for the version from a core-only job, which has no torch
    # for the metadata pre-check to find; --print-version must answer before it.
    monkeypatch.setattr(
        module,
        "_check_runtime_metadata",
        lambda: pytest.fail("--print-version must answer before the metadata pre-check"),
    )

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


def _prepare_precheck(monkeypatch, tmp_path, runtime_metadata):
    """P74: a buildable platform and a complete model, so only the pre-check can stop main().

    Each case passes a valid core-env entry first and the broken one second: a pre-check that
    stopped after the first entry would then reach Nuitka and fail the case.
    """
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(module, "MODEL", complete_model(tmp_path / "model"))
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")
    monkeypatch.setattr(module, "RUNTIME_METADATA", runtime_metadata)
    # Nuitka reports a missing package only after optimizing every module (before any C code
    # is generated, but well into the build), so the pre-check has to fail before it starts.
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("the pre-check must stop main() before Nuitka"),
    )
    return module


def test_runtime_metadata_precheck_rejects_a_missing_distribution(monkeypatch, tmp_path) -> None:
    module = _prepare_precheck(
        monkeypatch,
        tmp_path,
        {"numpy": ("numpy",), "photo-guard-no-such-distribution": ("numpy",)},
    )

    with pytest.raises(SystemExit, match="'photo-guard-no-such-distribution' is not installed"):
        module.main([])
    assert not module.DIST.exists(), "a refused build must not leave dist/ behind"


def test_runtime_metadata_precheck_requires_the_real_distribution_name(
    monkeypatch, tmp_path
) -> None:
    """importlib still finds ``NumPy`` by normalising it; the key must be the real name."""
    module = _prepare_precheck(
        monkeypatch, tmp_path, {"opencv-python-headless": ("cv2",), "NumPy": ("numpy",)}
    )

    with pytest.raises(SystemExit, match=r"'NumPy'.*real distribution name 'numpy'"):
        module.main([])
    assert not module.DIST.exists(), "a refused build must not leave dist/ behind"


def test_runtime_metadata_precheck_rejects_an_unreachable_module(monkeypatch, tmp_path) -> None:
    module = _prepare_precheck(
        monkeypatch,
        tmp_path,
        {
            "numpy": ("numpy",),
            "opencv-python-headless": ("cv2", "photo_guard_no_such_module"),
        },
    )

    with pytest.raises(
        SystemExit, match="'photo_guard_no_such_module' of 'opencv-python-headless'"
    ):
        module.main([])
    assert not module.DIST.exists(), "a refused build must not leave dist/ behind"


def _imported_top_level_names(path: Path) -> set[str]:
    """Top-level names this module imports in code the compiler keeps.

    An import inside ``if TYPE_CHECKING:`` or ``if False:`` is dead at runtime and Nuitka
    drops it (``--include-distribution-metadata`` still demands the package, so counting such
    an import would hide a build that aborts after optimizing). Function-level imports count:
    Nuitka follows those.
    """
    dead: set[str] = set()
    live: set[str] = set()

    def is_dead(test: ast.expr | None) -> bool:
        if isinstance(test, ast.Name):
            return test.id == "TYPE_CHECKING"  # bare TYPE_CHECKING, as ruff's rule treats it
        if isinstance(test, ast.Attribute):
            return test.attr == "TYPE_CHECKING"  # typing.TYPE_CHECKING
        if isinstance(test, ast.Constant):
            return not test.value
        return False

    def visit(node: ast.AST, *, dropped: bool) -> None:
        if isinstance(node, ast.If) and is_dead(node.test):
            for child in (*node.body, *node.orelse):
                visit(child, dropped=True)
            return
        if isinstance(node, ast.If):
            for child in (*node.body, *node.orelse):
                visit(child, dropped=dropped)
            return
        target = dead if dropped else live
        if isinstance(node, ast.Import):
            target.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            target.add(node.module.partition(".")[0])
        for child in ast.iter_child_nodes(node):
            visit(child, dropped=dropped)

    visit(ast.parse(path.read_text(encoding="utf-8")), dropped=False)
    return live - dead


def test_modules_left_out_of_include_module_are_imported_by_photo_guard() -> None:
    """P74: Nuitka aborts when an embedded distribution's package is not in the build.

    A module the command does not pass to --include-module therefore has to arrive through
    normal import following: --include-package=photo_guard compiles every photo_guard module
    and follows its imports, so each such module must be listed and imported there.
    """
    module = _load()
    listed = {name for modules in module.RUNTIME_METADATA.values() for name in modules}
    imported: set[str] = set()
    for path in (ROOT / "src" / "photo_guard").rglob("*.py"):
        imported |= _imported_top_level_names(path)

    assert module.NO_FORCE_INCLUDE_MODULES <= listed
    assert module.NO_FORCE_INCLUDE_MODULES <= imported


def test_the_import_guard_ignores_code_the_compiler_drops(tmp_path) -> None:
    """A TYPE_CHECKING or ``if False`` import never reaches the bundle: Nuitka drops it and
    still aborts on the embedded metadata, so the guard above must not count it."""
    dead = tmp_path / "dead.py"
    dead.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import numpy\n"
        "if False:\n"
        "    import numpy as numpy_again\n",
        encoding="utf-8",
    )
    assert "numpy" not in _imported_top_level_names(dead)

    live = tmp_path / "live.py"
    live.write_text("def load():\n    import numpy\n", encoding="utf-8")
    assert "numpy" in _imported_top_level_names(live)


def _assert_runtime_metadata_flags(command: list[str]) -> None:
    """P74: each distribution's metadata, plus the top-level modules Nuitka ties it to."""
    embedded = [item for item in command if item.startswith("--include-distribution-metadata=")]
    assert sorted(embedded) == sorted(
        f"--include-distribution-metadata={name}" for name in EXPECTED_RUNTIME_METADATA
    )
    included = [item for item in command if item.startswith("--include-module=")]
    assert sorted(included) == sorted(
        f"--include-module={name}" for name in EXPECTED_INCLUDE_MODULES
    )
    # The anti-bloat rule (numpy: no-auto-follow numpy.distutils) only holds without it.
    assert "--include-module=numpy" not in command


def _prepare_success(monkeypatch, tmp_path):
    module = _load()
    model = complete_model(tmp_path / "model")
    calls: list[dict] = []

    def fake_run(command, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})

    monkeypatch.setattr(module, "MODEL", model)
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    # P74: the core legs have no torch for the real pre-check to find; its own cases are above.
    monkeypatch.setattr(module, "_check_runtime_metadata", lambda: None)
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
    _assert_runtime_metadata_flags(command)
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
    _assert_runtime_metadata_flags(command)
    assert command[-1] == str(module.ROOT / "packaging" / "desktop_entry.py")
