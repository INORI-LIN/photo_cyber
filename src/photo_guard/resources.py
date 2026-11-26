"""Locate bundled resources in source, Nuitka standalone and macOS app builds."""
from __future__ import annotations

import builtins
import os
from pathlib import Path
import sys


def is_bundled() -> bool:
    """True when running from a desktop bundle rather than a source tree or wheel install.

    Two markers, because freezers disagree: PyInstaller-style tools set ``sys.frozen``, while
    Nuitka — what ``packaging/build_desktop.py`` uses — leaves ``sys.frozen`` unset and puts
    ``__compiled__`` into every compiled module's globals instead, this one included. Both
    :func:`candidate_roots` and ``photoguard``'s runtime-import error ask this one predicate,
    so they cannot disagree about where the process runs (P76).
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def program_path() -> Path:
    """The running program's own file, resolved (P76).

    ``sys.executable`` alone does not name it in every state:

    - Source tree or wheel install: ``sys.executable`` is the interpreter, the program.
    - Nuitka standalone, before ``multiprocessing`` is imported: ``sys.executable`` is
      ``<binary dir>/<basename of the build interpreter>`` (``python.exe`` / ``python``), a
      file Nuitka does not ship. The builtin ``__nuitka_binary_exe`` already names the real
      program (Nuitka 4.1.3, ``CompiledCodeHelpers.c``).
    - Nuitka standalone, after that import: Nuitka's multiprocessing plugin sets
      ``sys.executable`` to ``__nuitka_binary_exe``, so the two agree.

    Reading the builtin first keeps the answer independent of whether something (torch, in
    the desktop smoke) has imported ``multiprocessing`` yet. Without the builtin
    (PyInstaller-style freezers point ``sys.executable`` at the program) the fallback is
    ``sys.executable``. Not for re-running an interpreter from a source tree: resolving a
    venv's ``python`` symlink leaves the venv.
    """
    binary = getattr(builtins, "__nuitka_binary_exe", None)
    if isinstance(binary, str) and binary:
        return Path(binary).resolve()
    return Path(sys.executable).resolve()


def candidate_roots() -> tuple[Path, ...]:
    """Roots to search, most authoritative first.

    A macOS app bundle does not keep Nuitka's payload in one place: ``--include-data-dir``
    lands under ``Contents/Resources/`` while ``--include-data-files`` lands next to the
    executable in ``Contents/MacOS/`` — measured on macos-15 (run 36531496752: `models/` and
    `licenses/` in Resources, `LICENSE`/`THIRD_PARTY_NOTICES.md` in MacOS), see
    ``docs/fix-plan.md`` §9.9 / P33. One root therefore cannot serve both, and callers that
    must *find* something probe this tuple in order via :func:`find_resource`. Inside a
    bundle the executable is :func:`program_path`.
    """
    override = os.environ.get("PHOTO_GUARD_RESOURCE_DIR")
    if override:
        return (Path(override).expanduser().resolve(),)
    if is_bundled():
        executable = program_path()
        if sys.platform == "darwin" and executable.parent.name == "MacOS":
            return (executable.parent.parent / "Resources", executable.parent)
        return (executable.parent,)
    return (Path(__file__).resolve().parents[2],)


def application_root() -> Path:
    """The primary root.

    Kept as a single path for callers that build a path *without* probing; anything that
    must exist in the shipped bundle should use :func:`find_resource` instead, because the
    macOS layout may keep it in either root.
    """
    return candidate_roots()[0]


def find_resource(*parts: str) -> Path | None:
    """First existing ``root/parts`` across :func:`candidate_roots`, else ``None``.

    ``parts`` may name a file (``"LICENSE"``) or a directory (``"models"``).
    """
    for root in candidate_roots():
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None
