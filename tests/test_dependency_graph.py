"""G1 — the core install must stay free of torch, duplicate cv2 and GPU wheels.

The contract is read from two places on purpose: ``uv.lock`` is what CI actually installs
(``uv sync --frozen``), and ``pyproject.toml`` is what a reviewer reads. A transitive
dependency that sneaks the heavy closure back in turns this file red.

Deliberately stdlib-only: the core environment must not need anything beyond the packages
under test in order to run its own regression suite.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Must never be reachable from the core install. ``opencv-python`` is listed separately
# below because the core leg deliberately keeps the headless build.
FORBIDDEN = {
    "torch",
    "triton",
    "diffusers",
    "transformers",
    "accelerate",
    "safetensors",
    "huggingface-hub",
    "imwatermark",
    "invisible-watermark",
    "opencv-python",
}
FORBIDDEN_PREFIXES = ("nvidia-", "cuda-")

EXPECTED_CORE_CLOSURE = {
    "photo-guard",
    "numpy",
    "opencv-python-headless",
    "pillow",
    "pywavelets",
}


def _normalise(name: str) -> str:
    """PEP 503 normalisation: ``Foo.Bar_baz`` and ``foo-bar-baz`` are the same project."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _dependency_name(specifier: str) -> str:
    return _normalise(re.split(r"[<>=!~;\[\s]", specifier.strip(), maxsplit=1)[0])


def _lock() -> dict:
    return tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _core_closure(lock: dict) -> set[str]:
    """Every package reachable from ``photo-guard`` through ``[[package]] .dependencies``.

    Markers and extras are ignored: an entry that only applies on another platform is still
    a dependency someone will install, so it must not be able to hide here.
    """
    edges: dict[str, set[str]] = {}
    for package in lock["package"]:
        edges[_normalise(package["name"])] = {
            _normalise(dep["name"]) for dep in package.get("dependencies", [])
        }
    seen: set[str] = set()
    pending = ["photo-guard"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(edges.get(name, ()))
    return seen


def test_core_closure_excludes_heavy_and_duplicate_packages() -> None:
    closure = _core_closure(_lock())
    assert not (closure & FORBIDDEN), sorted(closure & FORBIDDEN)
    assert not [n for n in closure if n.startswith(FORBIDDEN_PREFIXES)], sorted(closure)


def test_core_closure_has_exactly_one_opencv_distribution() -> None:
    closure = _core_closure(_lock())
    assert sorted(n for n in closure if n.startswith("opencv-")) == ["opencv-python-headless"]


def test_core_closure_contains_expected_packages() -> None:
    """The whole core closure, pinned: the point of G1 is that this set *is* the install."""
    lock_closure = _core_closure(_lock())
    declared = {
        _dependency_name(spec)
        for spec in _pyproject()["project"]["dependencies"]
    }
    assert lock_closure == EXPECTED_CORE_CLOSURE, sorted(lock_closure)
    assert declared == EXPECTED_CORE_CLOSURE - {"photo-guard"}, sorted(declared)


def test_photoguard_extra_declares_torch_and_huggingface_hub() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]
    declared = {_dependency_name(spec) for spec in extras["photoguard"]}
    assert {"torch", "huggingface-hub"} <= declared, sorted(declared)
