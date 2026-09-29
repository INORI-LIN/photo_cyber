"""Locate bundled resources in source, Nuitka standalone and macOS app builds."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def candidate_roots() -> tuple[Path, ...]:
    """Roots to search, most authoritative first.

    A macOS app bundle does not keep Nuitka's payload in one place: ``--include-data-dir``
    lands under ``Contents/Resources/`` while ``--include-data-files`` lands next to the
    executable in ``Contents/MacOS/`` — measured on macos-15 (run 36531496752: `models/` and
    `licenses/` in Resources, `LICENSE`/`THIRD_PARTY_NOTICES.md` in MacOS), see
    ``docs/fix-plan.md`` §9.9 / P33. One root therefore cannot serve both, and callers that
    must *find* something probe this tuple in order via :func:`find_resource`.
    """
    override = os.environ.get("PHOTO_GUARD_RESOURCE_DIR")
    if override:
        return (Path(override).expanduser().resolve(),)
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        executable = Path(sys.executable).resolve()
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
