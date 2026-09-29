"""AGENTS.md 6.4 compliance: the forbidden install string must not appear
in code or scripts. This file documents the rule and is excluded from its
own grep (it is the watchdog — the rule references the string by name).

G2 turned this file into the licence/notices gate as well: the MIT text, the canonical
copyleft texts, the PEP 639 fields of the built metadata and the packaging wiring are all
pinned here, so a missing or drifted licence artefact fails the fast tier.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).name

_FORBIDDEN = "pip" + " install"  # split so the literal isn't in this file's body
# .github/ is deliberately NOT excluded (G5): excluding it left a blind spot in the gate,
# and AGENTS.md §11 now records the whitelist as AGENTS.md + README.md only.
_EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache"}
_EXCLUDE_FILES = {"uv.lock", "AGENTS.md", "README.md", SELF}


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


# --- licence material and third-party notices (G2) ----------------------------------
LICENSE_FILE = REPO_ROOT / "LICENSE"
NOTICES_FILE = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
# Canonical texts fetched from gnu.org; the hashes make accidental edits loud.
COPYLEFT_TEXTS = {
    "licenses/GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "licenses/LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
}


def test_license_file_is_complete_mit_text() -> None:
    text = LICENSE_FILE.read_text(encoding="utf-8")
    assert text.splitlines()[0].strip() == "MIT License"
    assert "Copyright (c) 2026 INORI-LIN" in text
    for phrase in (
        "Permission is hereby granted, free of charge",
        "copies or substantial portions of the Software",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert phrase in text, phrase


def test_copyleft_texts_are_canonical_and_hashes_match() -> None:
    for relative, digest in COPYLEFT_TEXTS.items():
        raw = (REPO_ROOT / relative).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != digest:
            # Turn the most likely cause (a checkout that rewrote LF to CRLF) into an
            # actionable message instead of a bare hash mismatch.
            hint = ""
            if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == digest:
                hint = (
                    " — the file was checked out with CRLF line endings; check that "
                    ".gitattributes still marks it `text eol=lf`"
                )
            raise AssertionError(f"{relative}: sha256 {actual} != {digest}{hint}")
        lines = [line.strip() for line in raw.decode("utf-8").splitlines() if line.strip()]
        assert lines[0] in {
            "GNU GENERAL PUBLIC LICENSE",
            "GNU LESSER GENERAL PUBLIC LICENSE",
        }, lines[0]
        assert lines[1] == "Version 3, 29 June 2007", lines[1]


def test_pyproject_declares_license_and_files() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == [
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "licenses/*.txt",
    ]
    assert "classifiers" not in project


def test_installed_distribution_carries_license_metadata() -> None:
    """PEP 639 fields must survive into the built metadata (G2's S1 spike, pinned)."""
    metadata = importlib.metadata.metadata("photo-guard")
    assert (metadata.get("License-Expression") or "").strip() == "MIT"
    files = set(metadata.get_all("License-File") or [])
    assert set(COPYLEFT_TEXTS) | {"LICENSE", "THIRD_PARTY_NOTICES.md"} <= files, files


def test_third_party_notices_cover_core_dependencies() -> None:
    """Every core dependency must appear with the version uv.lock actually resolves."""
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = {
        package["name"].lower(): package["version"]
        for package in tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    }
    notices = NOTICES_FILE.read_text(encoding="utf-8").lower()
    missing = []
    for specifier in project["project"]["dependencies"]:
        name = re.split(r"[<>=!~;\[\s]", specifier.strip(), maxsplit=1)[0].lower()
        row = f"| {name} | {lock[name]} |"
        if row not in notices:
            missing.append(row)
    assert not missing, missing


def test_sd_vae_notice_is_mit_and_pinned_to_the_configured_repo() -> None:
    from photo_guard import config

    notices = NOTICES_FILE.read_text(encoding="utf-8")
    rows = [line for line in notices.splitlines() if config.PHOTOGUARD_REMOTE_REPO in line]
    assert rows, "no notice row mentions the configured model repo"
    assert any("| MIT |" in row for row in rows), rows
    # P15: the row must carry the revision both sides pin to, so the notice cannot drift.
    assert any(config.PHOTOGUARD_REVISION in row for row in rows), rows


def test_packaging_wires_license_material() -> None:
    build = (REPO_ROOT / "packaging" / "build_desktop.py").read_text(encoding="utf-8")
    for fragment in (
        "--include-data-dir={ROOT / 'licenses'}=licenses",
        "--include-data-files={ROOT / 'LICENSE'}=LICENSE",
        "--include-data-files={ROOT / 'THIRD_PARTY_NOTICES.md'}=THIRD_PARTY_NOTICES.md",
    ):
        assert fragment in build, fragment
    iss = (REPO_ROOT / "packaging" / "windows-installer.iss").read_text(encoding="utf-8")
    assert "LicenseFile=..\\LICENSE" in iss
    dmg = (REPO_ROOT / "packaging" / "create_dmg.sh").read_text(encoding="utf-8")
    assert "THIRD_PARTY_NOTICES.md" in dmg and "licenses" in dmg


