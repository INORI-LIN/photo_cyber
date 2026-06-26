"""AGENTS.md 6.4 compliance: the forbidden install string must not appear
in code or scripts. This file documents the rule and is excluded from its
own grep (it is the watchdog — the rule references the string by name).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).name

_FORBIDDEN = "pip" + " install"  # split so the literal isn't in this file's body
_EXCLUDE_DIRS = {".venv", ".git", ".github", "__pycache__", ".pytest_cache"}
_EXCLUDE_FILES = {"uv.lock", "AGENTS.md", "README.md", "CLAUDE.md", SELF}


def _scan_repo_for_forbidden() -> list[tuple[Path, int, str]]:
    """Pure-Python equivalent of the grep CI step.

    Cross-platform (the shell-based grep step in ci.yml is Linux-only;
    this test runs on every OS via pytest). Walks the repo, skips binary
    files via UnicodeDecodeError, and reports every line that contains
    the forbidden literal.
    """
    hits: list[tuple[Path, int, str]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.name in _EXCLUDE_FILES:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if _FORBIDDEN in line:
                        hits.append((path, lineno, line.rstrip()))
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable — not a source/script file we care about.
            continue
    return hits


def test_no_forbidden_install_in_code_or_scripts() -> None:
    hits = _scan_repo_for_forbidden()
    assert not hits, (
        "forbidden install reference found in code/scripts "
        "(AGENTS.md 6.4 forbids):\n"
        + "\n".join(f"{p}:{ln}: {text}" for p, ln, text in hits)
    )


def test_no_requirements_txt() -> None:
    """AGENTS.md 6.4: 仓库不得包含 requirements.txt（避免诱导他人裸装依赖）."""
    assert not (REPO_ROOT / "requirements.txt").exists()


