"""F′1 / G11 — static locks for workflow and container hardening.

These are text-level checks on purpose: PyYAML is not part of the core dev
environment (CI runs ``uv sync --frozen --group dev`` without the photoguard
extra), and the invariants here are about YAML structure that a full parser
would not express any better.  The release-workflow tests use the same style.

Nothing here asserts the *number* of tests or the exact major version of every
action — that would turn each dependency bump into test churn.  The locks are
the decisions that must not silently regress: read-only tokens, concurrency,
no floating ``@main`` refs, the pinned third-party action, ignore/EOL rules,
and the non-root image contract.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _workflow_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in WORKFLOWS}


def _header(text: str) -> str:
    """Everything before the first top-level ``jobs:`` block."""
    marker = "\njobs:\n"
    assert marker in text, "workflow has no top-level jobs block"
    return text.split(marker, 1)[0]


def _executable_lines(text: str) -> str:
    """Drop comment-only lines so a historical note cannot satisfy a lock."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_workflows_declare_read_only_permissions_and_concurrency() -> None:
    texts = _workflow_texts()
    assert len(texts) >= 4
    for name, text in texts.items():
        header = _header(text)
        assert "permissions:" in header, name
        assert "contents: read" in header, name
        assert "contents: write" not in header, name
        assert "concurrency:" in header, name
        assert "group: ${{ github.workflow }}-${{ github.ref }}" in header, name

    # A release must queue rather than cancel a half-published run.
    assert "cancel-in-progress: false" in _header(texts["release-desktop.yml"])
    for name in ("ci.yml", "docker.yml", "efficacy.yml"):
        assert "cancel-in-progress: true" in _header(texts[name]), name

    # The only write grant is the tag-gated publish job.
    release = texts["release-desktop.yml"]
    assert release.count("contents: write") == 1
    assert "  publish:" in release and release.index("  publish:") < release.index("contents: write")


def test_workflow_actions_are_not_pinned_to_floating_branches() -> None:
    for name, text in _workflow_texts().items():
        refs = re.findall(r"uses:\s*([^\s#]+)", _executable_lines(text))
        assert refs, name
        for ref in refs:
            assert ref.startswith("./") or "@" in ref, f"{name}: unpinned action {ref}"
            assert not ref.endswith(("@main", "@master")), f"{name}: floating branch {ref}"


def test_docker_workflow_checks_the_visible_watermark_font() -> None:
    """Q2/N3: the image ships no font package; the sized Pillow fallback is the contract.

    A regression to unsized ``load_default()`` renders the visible layer at ~10 px while
    still exiting 0. The probe must stay executable (comments do not satisfy this lock).
    """
    code = _executable_lines(_workflow_texts()["docker.yml"])
    assert "_load_font(36)" in code
    assert "font probe OK" in code


def test_docker_workflow_pins_free_disk_space_and_uses_new_input_name() -> None:
    text = _workflow_texts()["docker.yml"]
    code = _executable_lines(text)
    assert (
        "jlumbroso/free-disk-space@ceedf095f4ec1a097402bc6bd80831f2e1a6fde6"
        in code
    )
    assert "preinstalled-runtimes: true" in code
    assert "tool-cache:" not in code


def test_dockerignore_gitattributes_and_project_urls_are_hardened() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in ("release/", "docs/"):
        assert entry in dockerignore, entry

    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for entry in ("*.sh text eol=lf", "Dockerfile text eol=lf"):
        assert entry in attrs, entry

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["urls"]["Repository"] == (
        "https://github.com/INORI-LIN/photo_cyber"
    )


def test_dockerfile_runs_as_non_root_and_pins_base_and_uv() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim-trixie@sha256:" in text
    assert "ghcr.io/astral-sh/uv:0.13.7" in text
    assert "USER app" in text
    assert "HEALTHCHECK" in text and "photo-guard" in text
    # The release stage is the last one and inherits runtime's non-root user.
    assert text.rstrip().splitlines()[-1].strip() == "FROM runtime AS release"


def test_dockerfile_test_stage_switches_to_root_before_sync() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM runtime AS test" in text
    test_stage = text.split("FROM runtime AS test", 1)[1].split("FROM runtime AS release", 1)[0]
    assert "USER root" in test_stage
    assert test_stage.index("USER root") < test_stage.index("RUN uv sync")
