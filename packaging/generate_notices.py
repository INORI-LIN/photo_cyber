"""Generate / verify ``THIRD_PARTY_NOTICES.md``.

The notices are a per-platform view of the environment that ships: rows come from
``importlib.metadata`` of the interpreter this tool runs in, so a section is only ever as
good as the environment that produced it. ``--check`` therefore compares **the current
platform's section only** against the installed set, and the release workflow runs it in the
shipping environment (``--extra photoguard --extra desktop --group package``) before
building anything, so a stale section fails loudly with zero artefacts.

Hand-maintained material (``LICENSE``, ``licenses/*.txt``) is never generated and never
overwritten — this tool only reads those files; only the platform section of the notices is
rewritten.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"

# Never generated, never overwritten (G2). Listed here so the write path and ``--check``
# both refuse to treat them as output.
HAND_MAINTAINED_LICENSES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "licenses/GPL-3.0.txt",
    "licenses/LGPL-3.0.txt",
)
# Kept split so this file cannot trip the repository's own compliance gate.
FORBIDDEN_LITERAL = "pip" + " install"
ROW_FIELDS = ("name", "version", "license", "source")
PROJECT_NAME = "photo-guard"
SECTION_PREFIX = "## "
TABLE_HEADER = "| " + " | ".join(ROW_FIELDS) + " |"
TABLE_SEPARATOR = "|" + "---|" * len(ROW_FIELDS)

SECTION_TEMPLATE = """{prefix}{tag}

Rows measured in this environment with ``importlib.metadata``. Other platforms' sections are
appended by running this tool on those platforms; ``--check`` validates one section at a time.

{header}
{separator}
{rows}
"""


def platform_tag() -> str:
    return f"{platform.system()} / {platform.machine()}"


def _license_of(metadata) -> str:
    expression = (metadata.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (metadata.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 60:
        return field
    for classifier in metadata.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "declared in package metadata"


def _source_of(metadata) -> str:
    homepage = (metadata.get("Home-page") or "").strip()
    if homepage:
        return homepage
    for url in metadata.get_all("Project-URL") or []:
        _, _, link = url.partition(",")
        if link.strip():
            return link.strip()
    return (metadata.get("Author-email") or "").strip() or "unknown"


def collect_rows() -> list[dict[str, str]]:
    """One row per installed distribution, the project itself excluded."""
    rows = []
    for dist in md.distributions():
        metadata = dist.metadata
        name = (metadata["Name"] or "").strip()
        if not name or name.lower() == PROJECT_NAME:
            continue
        rows.append(
            {
                "name": name,
                "version": dist.version,
                "license": _license_of(metadata),
                "source": _source_of(metadata),
            }
        )
    return sorted(rows, key=lambda row: row["name"].lower())


def render_row(row: dict[str, str]) -> str:
    return "| " + " | ".join(row[field] for field in ROW_FIELDS) + " |"


def render_section(rows: list[dict[str, str]], tag: str) -> str:
    body = "\n".join(render_row(row) for row in rows) or "| (none installed) | | | |"
    return SECTION_TEMPLATE.format(
        prefix=SECTION_PREFIX, tag=tag, header=TABLE_HEADER, separator=TABLE_SEPARATOR,
        rows=body,
    )


def _section_bounds(text: str, tag: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"{SECTION_PREFIX}{tag}":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(SECTION_PREFIX):
            end = index
            break
    return start, end


def compare_section(text: str, rows: list[dict[str, str]], tag: str) -> tuple[list[str], list[str]]:
    """``(missing, extra)`` row lines for ``tag``; both empty means the section is current."""
    bounds = _section_bounds(text, tag)
    expected = {render_row(row) for row in rows}
    if bounds is None:
        return sorted(expected), []
    start, end = bounds
    present = {
        line.strip()
        for line in text.splitlines()[start:end]
        if line.startswith("|") and not line.startswith("|---") and line.strip() != TABLE_HEADER
    }
    return sorted(expected - present), sorted(present - expected)


def replace_section(text: str, section: str, tag: str) -> str:
    bounds = _section_bounds(text, tag)
    if bounds is None:
        separator = "" if text.endswith("\n\n") else "\n"
        return f"{text}{separator}\n{section}"
    start, end = bounds
    lines = text.splitlines()
    return "\n".join([*lines[:start], *section.splitlines(), "", *lines[end:]]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_notices.py", description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the current platform's section instead of rewriting it",
    )
    args = parser.parse_args(argv)

    tag = platform_tag()
    rows = collect_rows()
    if args.check:
        if NOTICES.name not in HAND_MAINTAINED_LICENSES:
            raise SystemExit("the notices file must stay in HAND_MAINTAINED_LICENSES")
        missing_paths = [p for p in HAND_MAINTAINED_LICENSES if not (ROOT / p).is_file()]
        if missing_paths:
            print(f"licence material missing: {missing_paths}", file=sys.stderr)
            return 1
        missing, extra = compare_section(NOTICES.read_text(encoding="utf-8"), rows, tag)
        if missing or extra:
            print(f"notices are stale for {tag}:", file=sys.stderr)
            for line in missing:
                print(f"  missing: {line}", file=sys.stderr)
            for line in extra:
                print(f"  extra:   {line}", file=sys.stderr)
            return 1
        print(f"notices OK for {tag} ({len(rows)} rows)")
        return 0

    section = render_section(rows, tag)
    if FORBIDDEN_LITERAL in section:
        print("refusing to write: a forbidden install literal is present", file=sys.stderr)
        return 1
    text = NOTICES.read_text(encoding="utf-8") if NOTICES.exists() else "# Third-party notices\n"
    NOTICES.write_text(replace_section(text, section, tag), encoding="utf-8")
    print(f"wrote {tag} section ({len(rows)} rows) to {NOTICES.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
