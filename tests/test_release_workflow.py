"""G9 — static pins for the release workflow's checksum steps.

Neither leg can be executed from a developer machine (one needs Windows PowerShell, the other
a macOS runner), and both were broken by the same mechanism at different times: the shell
opens the redirection target *before* it runs the command, so enumerating the output
directory re-reads the file being written. The Windows step failed outright on
windows-latest 2026-09-29 (``… being used by another process`` → exit 1 → the upload and
release steps were skipped); the macOS step had the same shape and additionally wrote a name
the other platform also used.

These assertions pin the invariants that let the steps run at all — output excluded from the
enumeration, explicit encoding, distinct per-platform filenames — rather than the exact
wording of either script.
"""
from __future__ import annotations

from pathlib import Path

RELEASE = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "release-desktop.yml"
).read_text(encoding="utf-8")


def _steps(text: str) -> list[str]:
    """Split a job's step list on the 6-space ``- `` that starts each step."""
    parts = text.split("\n      - ")
    return [parts[0], *parts[1:]]


def _step_containing(marker: str) -> str:
    matches = [step for step in _steps(RELEASE) if marker in step]
    assert len(matches) == 1, f"expected one step containing {marker!r}, got {len(matches)}"
    return matches[0]


def _code(step: str) -> str:
    """The step's executable lines (comments may mention the old, broken invocations)."""
    return "\n".join(line for line in step.splitlines() if not line.lstrip().startswith("#"))


def test_windows_checksum_step_excludes_its_own_output() -> None:
    code = _code(_step_containing("SHA256SUMS-Windows-x64.txt"))
    assert "$_.Name -notlike 'SHA256SUMS*'" in code
    # Enumerate first, write second: the old one-liner opened the (globbed) output file
    # before hashing it, which is what produced "being used by another process".
    assert "Get-FileHash release\\*" not in code
    assert code.index("$sums =") < code.index("WriteAllText")


def test_windows_checksum_step_writes_plain_ascii_lf() -> None:
    code = _code(_step_containing("SHA256SUMS-Windows-x64.txt"))
    # `Out-File` defaults to UTF-16 + CRLF + a table layout; nothing else can parse that.
    assert "WriteAllText" in code
    assert "[System.Text.Encoding]::ASCII" in code
    assert "Out-File" not in code
    assert '$sums -join "`n"' in code, "line endings must be explicit LF"


def test_macos_checksum_step_uses_the_same_guards() -> None:
    code = _code(_step_containing("SHA256SUMS-macOS-arm64.txt"))
    assert 'case "$f" in SHA256SUMS*)' in code
    assert "cd release && for f in *" in code
    assert '"$f"' in code, "quote the loop variable: a future artifact name may hold a space"


def test_the_two_platforms_do_not_share_a_checksum_filename() -> None:
    """Both legs upload to one GitHub Release with ``--clobber``; a shared filename means the
    second uploader silently replaces the first platform's sums."""
    windows = _code(_step_containing("SHA256SUMS-Windows-x64.txt"))
    macos = _code(_step_containing("SHA256SUMS-macOS-arm64.txt"))

    assert "SHA256SUMS-Windows-x64.txt" in windows
    assert "SHA256SUMS-macOS-arm64.txt" in macos
    assert "SHA256SUMS.txt" not in windows
    assert "SHA256SUMS.txt" not in macos
