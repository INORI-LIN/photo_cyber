"""Locate bundled resources in source, Nuitka standalone and macOS app builds."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def application_root() -> Path:
    override = os.environ.get("PHOTO_GUARD_RESOURCE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        executable = Path(sys.executable).resolve()
        if sys.platform == "darwin" and executable.parent.name == "MacOS":
            return executable.parent.parent / "Resources"
        return executable.parent
    return Path(__file__).resolve().parents[2]


def model_dir(name: str) -> Path:
    return application_root() / "models" / name
