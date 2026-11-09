"""Locate Inno Setup's ``ISCC.exe`` for the Windows release build (P23).

The release workflow used to hard-code one install path.  This resolver tries,
in order:

1. ``ISCC_PATH`` — an explicit override.  If it is set but does not name a
   file, the resolver exits 2 instead of silently falling back to another
   install: a broken explicit configuration must be visible.
2. ``PATH`` (``shutil.which``).
3. The Inno Setup 6 registry entries (``InstallLocation`` and the
   ``App Paths\\ISCC.exe`` default value).
4. The two standard ``Program Files`` locations.

Only the resolved path is written to stdout; every diagnostic goes to stderr,
so the PowerShell caller can use the stdout value directly.  Exit codes:
0 = found, 1 = not found, 2 = ``ISCC_PATH`` is set but invalid.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DEFAULT_INSTALL_DIRS = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)

_UNINSTALL_SUBKEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
)
_APP_PATH_SUBKEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
)


def _clean(value: object) -> str:
    """Strip whitespace and the quotes Windows installers like to add."""
    return str(value or "").strip().strip('"').strip("'")


def _registry_candidates() -> list[Path]:
    """Inno Setup 6 locations recorded by Windows, in probe order."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    key_read = getattr(winreg, "KEY_READ", 0)
    # Accessing the 32-bit view on a 64-bit interpreter needs an explicit flag;
    # WOW6432Node is also listed literally so the result does not depend on it.
    access_modes = (0, getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0))
    hives = (
        getattr(winreg, "HKEY_LOCAL_MACHINE", None),
        getattr(winreg, "HKEY_CURRENT_USER", None),
    )

    candidates: list[Path] = []
    for hive in hives:
        if hive is None:
            continue
        for subkey in _UNINSTALL_SUBKEYS:
            for extra in access_modes:
                try:
                    with winreg.OpenKey(hive, subkey, 0, key_read | extra) as key:
                        location, _ = winreg.QueryValueEx(key, "InstallLocation")
                except OSError:
                    continue
                location = _clean(location)
                if location:
                    candidates.append(Path(location) / "ISCC.exe")

        for subkey in _APP_PATH_SUBKEYS:
            for extra in access_modes:
                try:
                    with winreg.OpenKey(hive, subkey, 0, key_read | extra) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                except OSError:
                    continue
                value = _clean(value)
                if value:
                    candidates.append(Path(value))
    return candidates


def discovery_candidates() -> list[Path]:
    """Every candidate to try when ``ISCC_PATH`` is not set, in order."""
    candidates: list[Path] = []
    which = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if which:
        candidates.append(Path(which))
    candidates.extend(_registry_candidates())
    candidates.extend(DEFAULT_INSTALL_DIRS)

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _print_tried(candidates: list[Path]) -> None:
    print("tried:", file=sys.stderr)
    if not candidates:
        print("  (no candidates)", file=sys.stderr)
        return
    for candidate in candidates:
        print(f"  {candidate}", file=sys.stderr)


def main() -> int:
    raw = os.environ.get("ISCC_PATH")
    if raw:
        configured = Path(_clean(raw)).expanduser()
        if configured.is_file():
            print(configured.resolve())
            return 0
        print(
            f"ISCC_PATH points to a non-existent file: {configured} "
            "(not falling back to PATH/registry)",
            file=sys.stderr,
        )
        _print_tried([configured])
        return 2

    candidates = discovery_candidates()
    for candidate in candidates:
        if candidate.is_file():
            print(candidate.resolve())
            return 0

    print("Inno Setup compiler (ISCC.exe) not found", file=sys.stderr)
    _print_tried(candidates)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
