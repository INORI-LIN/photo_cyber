"""AGENTS.md 6.4 compliance: the forbidden install string must not appear
in code or scripts. This file documents the rule and is excluded from its
own grep (it is the watchdog — the rule references the string by name).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).name


def test_no_forbidden_install_in_code_or_scripts() -> None:
    proc = subprocess.run(
        [
            "grep",
            "-RIn",
            "--exclude-dir=.venv",
            "--exclude-dir=.git",
            "--exclude-dir=.github",
            "--exclude=uv.lock",
            "--exclude=AGENTS.md",
            "--exclude=README.md",
            "--exclude=CLAUDE.md",
            f"--exclude={SELF}",
            "pip" + " install",  # split so the literal isn't in this file's body
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    # grep returns 1 when no matches found — that's the success case.
    assert proc.returncode == 1, (
        "forbidden install reference found in code/scripts "
        "(AGENTS.md 6.4 forbids):\n" + proc.stdout
    )


def test_no_requirements_txt() -> None:
    """AGENTS.md 6.4: 仓库不得包含 requirements.txt（避免诱导他人裸装依赖）."""
    assert not (REPO_ROOT / "requirements.txt").exists()


