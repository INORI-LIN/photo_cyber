"""Shared, Qt-free test helpers.

Kept out of ``conftest.py`` on purpose: the historical ``textured_jpg`` fixture
(``tests/conftest.py:18-28``) is pinned by ``docs/fix-plan.md`` and must not change, so the
new helpers live here and call sites opt in explicitly. Nothing in this module imports
PySide6, torch or diffusers, so the core-only tier can import it safely.

Every helper is stateless: ``load_script`` returns a fresh module per call because tests
monkeypatch attributes on it; a cache would leak those patches across cases.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]


def textured_rgb(
    size: tuple[int, int] = (640, 480),
    *,
    seed: int,
    low: int = 40,
    high: int = 210,
    gradient: bool = False,
) -> Image.Image:
    """A deterministic textured RGB image.

    ``size`` is ``(width, height)``. ``gradient=True`` reproduces the conftest fixture's
    ``R += x//8`` / ``G += y//8`` ramp; the other historical helpers use flat noise.
    The random bounds, seed and gradient flag are per-call parameters because they are the
    measured preconditions of different round-trip tests, not style choices.
    """
    width, height = size
    rng = np.random.default_rng(seed)
    arr = rng.integers(low, high, (height, width, 3), dtype=np.uint8)
    if gradient:
        yy, xx = np.mgrid[0:height, 0:width]
        arr[..., 0] = np.clip(arr[..., 0].astype(int) + (xx // 8), 0, 255).astype(np.uint8)
        arr[..., 1] = np.clip(arr[..., 1].astype(int) + (yy // 8), 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def write_textured(
    path: Path | str,
    size: tuple[int, int] = (640, 480),
    *,
    seed: int,
    low: int = 60,
    high: int = 200,
    gradient: bool = False,
    quality: int = 92,
) -> Path:
    """Write a deterministic textured JPEG to ``path`` and return it."""
    destination = Path(path)
    textured_rgb(size, seed=seed, low=low, high=high, gradient=gradient).save(
        destination, quality=quality
    )
    return destination


def load_script(path: Path | str, name: str) -> ModuleType:
    """Load a repository script by path into a fresh, unregistered module.

    A relative path is resolved against the repository root. The module is deliberately
    not inserted into ``sys.modules``: each caller gets its own namespace, so
    ``monkeypatch.setattr(module, ...)`` cannot leak into the next test.
    """
    script = Path(path)
    if not script.is_absolute():
        script = REPO_ROOT / script
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_model(
    path: Path | str, *, weights: str = "diffusion_pytorch_model.safetensors"
) -> Path:
    """Create the minimal directory ``config.model_dir_is_complete`` accepts."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text("{}", encoding="utf-8")
    (directory / weights).write_bytes(b"")
    return directory
