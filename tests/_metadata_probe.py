"""P74 child-process probe: replay the desktop bundle's distribution-metadata view.

Run by ``tests/test_bundle_metadata.py`` with ``sys.executable``. pytest never collects it (the
name does not match ``test_*.py``) and the pytest process only loads it for
:func:`nuitka_top_level`, so the module level stays stdlib-only: torch and diffusers are
imported here, in the child, never in the test process.

A Nuitka standalone bundle carries no ``*.dist-info`` directory. Metadata exists only for the
distributions passed to ``--include-distribution-metadata``: at build time Nuitka keeps each
one's METADATA (else PKG-INFO) and entry_points.txt text and ties it to the distribution's
first top-level package (``nuitka/code_generation/ConstantCodes.py``,
``addDistributionMetadataValue``). At runtime its meta-path loader answers
``find_distributions`` by comparing ``context.name.lower()`` with each real name's
``lower()`` -- no PEP 503 normalisation (``build/static_src/MetaPathBasedLoader.c``,
``_nuitka_loader_find_distributions``) -- and yields ``nuitka_distribution`` objects whose
``read_text`` answers METADATA, entry_points.txt and top_level.txt only, so ``files`` is None
(``MetaPathBasedLoaderImportlibMetadataDistribution.c``). This probe snapshots the same texts
with the normal finder, silences ``PathFinder.find_distributions`` and installs a finder that
behaves like Nuitka's, then reports what diffusers and the SD path make of that view.

Usage::

    _metadata_probe.py setup MODEL_DIR
    _metadata_probe.py run --stage {cheap,full} --model MODEL_DIR (--source | --allow [NAME ...])

``--source`` leaves the environment's own metadata alone (the baseline); ``--allow`` replays the
bundle view with exactly the listed distributions. The result is one JSON document between
:data:`BEGIN` and :data:`END` on stdout; exit 0 means the probe itself ran to completion (an
import or load failure under test is part of the result, not a probe failure).
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.metadata
import importlib.util
import inspect
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback

BEGIN = "===P74_METADATA_PROBE_JSON==="
END = "===P74_METADATA_PROBE_END==="

_FLAG = re.compile(r"is_\w+_available")
# Messages are cut to their first line: that line identifies the failure, and diffusers puts
# its install advice on the lines after it.
_MESSAGE_CHARS = 300


def importable_top_level(name: str) -> bool:
    """``find_spec`` can locate ``name`` as a top-level module, without importing anything.

    Like Nuitka's ``hasModule`` it takes any name it can locate, identifier or not: mypyc
    helpers such as ``81d243bd2c585b0f4821__mypyc`` start with a digit.
    """
    # Dotted entries would make find_spec import their parent package; none of the closure's
    # distributions declares one, and nothing may be imported before the view is installed.
    # The dot test also covers relative names and the "foo.." / "foo." forms that Nuitka's
    # checkModuleName rejects; an empty name would make find_spec raise.
    return bool(name) and "." not in name and importlib.util.find_spec(name) is not None


def nuitka_top_level(dist: importlib.metadata.Distribution) -> str:
    """The package Nuitka ties ``dist``'s metadata to.

    Mirrors ``getDistributionTopLevelPackageNames(dist)[0]`` (``nuitka/utils/Distributions.py``):
    the first top_level.txt entry that exists, else the first top-level name among the
    recorded files (dist-info entries and dot-prefixed paths skipped), else the real name.
    In that files fallback Nuitka keeps every recorded name and drops those below another one
    (``numpy.libs`` below ``numpy``); this one counts only names find_spec locates without a
    dot, which agrees unless a recorded name is missing or a dotted name stands alone.
    Nuitka refuses to build when this package is missing from the bundle.
    """
    declared = dist.read_text("top_level.txt")
    if declared is not None:
        for line in declared.splitlines():
            name = line.strip().replace("/", ".")
            if name and importable_top_level(name):
                return name
    for entry in dist.files or ():
        path = entry.as_posix()
        if path.startswith("."):
            continue
        first, _, remainder = path.partition("/")
        if first.endswith((".dist-info", ".egg-info")) or first == "__pycache__":
            continue
        name = first if remainder else inspect.getmodulename(first)
        if name and importable_top_level(name):
            return name
    return dist.metadata["Name"]


class _NuitkaDistribution(importlib.metadata.Distribution):
    """Same shape and answers as Nuitka's ``nuitka_distribution``; ``files`` is therefore None."""

    def __init__(self, package_name, path, metadata, entry_points):
        self.package_name = package_name
        self._path = path
        self.metadata_data = metadata
        self.entry_points_data = entry_points

    def read_text(self, filename):
        if filename == "METADATA":
            return self.metadata_data
        elif filename == "entry_points.txt":
            return self.entry_points_data
        elif filename == "top_level.txt":
            return self.package_name + "\n"
        return None

    def locate_file(self, path):
        return os.path.join(self._path, path)


class _NuitkaMetadataFinder:
    """``_nuitka_loader_find_distributions``: case-insensitive exact names, no imports."""

    def __init__(self, snapshot: dict[str, tuple[str, str, str, str]]) -> None:
        self._snapshot = snapshot

    def find_spec(self, fullname, path=None, target=None):
        return None

    def find_distributions(self, context=importlib.metadata.DistributionFinder.Context()):
        name = context.name
        for real_name in sorted(self._snapshot):  # Nuitka walks its sorted build-time table
            if name is None or name.lower() == real_name.lower():
                yield _NuitkaDistribution(*self._snapshot[real_name])


def _no_distributions(*_args, **_kwargs):
    return iter(())


def _snapshot(names: list[str]) -> dict[str, tuple[str, str, str, str]]:
    """Read the allowed distributions with the normal finder, keyed like Nuitka's table."""
    snapshot = {}
    for requested in names:
        # A missing distribution raises here, as Nuitka stops the build on one.
        dist = importlib.metadata.distribution(requested)
        package = nuitka_top_level(dist)
        spec = importlib.util.find_spec(package)
        path = os.path.dirname(spec.origin) if spec is not None and spec.origin else ""
        snapshot[dist.metadata["Name"]] = (
            package,
            path,
            str(dist.read_text("METADATA") or dist.read_text("PKG-INFO") or ""),
            str(dist.read_text("entry_points.txt") or ""),
        )
    return snapshot


def _install_view(snapshot: dict[str, tuple[str, str, str, str]]) -> None:
    # PathFinder is the only stock finder with find_distributions (a staticmethod in 3.11); a
    # bundle has no dist-info for it to find, so it must answer nothing here either.
    importlib.machinery.PathFinder.find_distributions = staticmethod(_no_distributions)
    sys.meta_path.insert(0, _NuitkaMetadataFinder(snapshot))


def _view() -> list[str]:
    return sorted(dist.metadata["Name"] for dist in importlib.metadata.distributions())


def _found(name: str) -> bool:
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _semantics(real_names: list[str]) -> dict[str, bool]:
    """How lookups resolve: e.g. ``opencv-python-headless`` yes, ``opencv_python_headless`` no."""
    queries = set()
    for real_name in real_names:
        queries.update({real_name, real_name.lower(), real_name.replace("-", "_")})
    return {query: _found(query) for query in sorted(queries)}


def _objects(real_names: list[str]) -> dict[str, dict[str, object]]:
    """What each distribution object in the view answers beyond METADATA and entry_points.txt.

    Nuitka's object answers nothing else (no RECORD, so ``files`` is None) and gives
    top_level.txt as a single line: the package the metadata is tied to.
    """
    objects: dict[str, dict[str, object]] = {}
    for real_name in real_names:
        dist = importlib.metadata.distribution(real_name)
        objects[real_name] = {
            "files_is_none": dist.files is None,
            "top_level_txt": dist.read_text("top_level.txt"),
        }
    return objects


def _first_line(text: str) -> str:
    lines = text.splitlines()
    return (lines[0] if lines else "")[:_MESSAGE_CHARS]


def _describe(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": _first_line(str(exc))}


class _Capture(logging.Handler):
    """WARNING+ records reaching the ``diffusers`` logger, split by stage."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.stage = "import"
        self.records: dict[str, list[str]] = {"import": [], "load": []}

    def emit(self, record: logging.LogRecord) -> None:
        line = _first_line(record.getMessage())
        self.records[self.stage].append(f"{record.name}:{record.levelname}:{line}")


def _takes_no_arguments(function) -> bool:
    try:
        inspect.signature(function).bind()
    except (TypeError, ValueError):
        return False
    return True


def _flags(import_utils) -> dict[str, object]:
    """Every no-argument ``is_*_available`` diffusers exposes, re-exports included."""
    flags: dict[str, object] = {}
    for name in sorted(dir(import_utils)):
        if not _FLAG.fullmatch(name):
            continue
        function = getattr(import_utils, name)
        if not callable(function) or not _takes_no_arguments(function):
            continue
        try:
            value = function()
        except Exception as exc:  # recorded, so a flag that starts raising is a difference
            flags[name] = f"error: {type(exc).__name__}"
        else:
            flags[name] = value if isinstance(value, bool) else repr(value)
    return flags


def _load_and_attack(model: str, result: dict) -> None:
    import numpy as np
    from diffusers import AutoencoderKL

    from photo_guard import photoguard

    result["autoencoder_kl"] = f"{AutoencoderKL.__module__}.{AutoencoderKL.__qualname__}"
    attack = photoguard.build_attack(photoguard.PGDConfig(model_id=model, steps=1, device="cpu"))
    norm = attack.latent_norm(np.zeros((8, 8, 3), np.uint8))
    result["vae"] = {"latent_norm": norm if math.isfinite(norm) else repr(norm)}
    image = np.full((8, 8, 3), 128, np.uint8)
    adversarial = attack.attack(image)
    delta = np.abs(adversarial.astype(np.int16) - image.astype(np.int16))
    result["pgd"] = {
        "shape": list(adversarial.shape),
        "dtype": str(adversarial.dtype),
        "max_delta": int(delta.max()),
        "budget": math.ceil(attack.cfg.epsilon * 255) + 1,
    }


def _emit(result: dict) -> None:
    sys.stdout.write(f"{BEGIN}\n{json.dumps(result, sort_keys=True)}\n{END}\n")
    sys.stdout.flush()


def _setup(model_dir: str) -> int:
    import torch
    from diffusers import AutoencoderKL

    torch.manual_seed(0)
    vae = AutoencoderKL(
        block_out_channels=(8,),
        down_block_types=("DownEncoderBlock2D",),
        up_block_types=("UpDecoderBlock2D",),
        layers_per_block=1,
        latent_channels=4,
        norm_num_groups=8,
        sample_size=8,
    )
    vae.save_pretrained(model_dir, safe_serialization=True)
    files = sorted(path.name for path in Path(model_dir).iterdir())
    weights = [name for name in files if name.endswith(".safetensors")]
    result = {"mode": "setup", "files": files}
    # The loader must take the safetensors path (P15), so nothing but these may be present.
    if "config.json" not in files or not weights or len(files) != len(weights) + 1:
        result["setup_error"] = "expected config.json plus *.safetensors only"
        _emit(result)
        return 3
    _emit(result)
    return 0


def _run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    result: dict = {
        "mode": "source" if args.source else "nuitka",
        "stage": args.stage,
        "requested": None if args.source else list(args.allow),
        "import_error": None,
        "load_error": None,
        "flags": None,
        "timings": {},
    }
    if not args.source:
        snapshot = _snapshot(list(args.allow))
        allowed = sorted(snapshot)
        _install_view(snapshot)
        result["allowed"] = allowed
        result["top_level"] = {name: snapshot[name][0] for name in allowed}
        result["view"] = {
            "before": _view(),
            "semantics": _semantics(allowed),
            "objects": _objects(allowed),
        }
        # Any other finder answering would make every conclusion below about a larger view.
        if result["view"]["before"] != allowed:
            result["view_error"] = "distributions() does not match the allowed names"
            _emit(result)
            return 3

    capture = _Capture()
    logging.getLogger("diffusers").addHandler(capture)
    # diffusers sets its logger level from this at import; pin the default so the warning
    # comparison cannot be switched off by the caller's environment.
    os.environ["DIFFUSERS_VERBOSITY"] = "warning"
    try:
        import diffusers  # noqa: F401
    except Exception as exc:
        result["import_error"] = _describe(exc)
        traceback.print_exc()
    else:
        from diffusers.utils import import_utils

        result["flags"] = _flags(import_utils)
        result["timings"]["import"] = round(time.perf_counter() - started, 2)
        if args.stage == "full":
            capture.stage = "load"
            try:
                _load_and_attack(args.model, result)
            except Exception as exc:
                result["load_error"] = _describe(exc)
                traceback.print_exc()
            result["timings"]["load"] = round(time.perf_counter() - started, 2)

    result["warnings"] = capture.records
    # The backport appends its own path finder and pkg_resources scans sys.path itself; both
    # would read the real dist-info here (a bundle has none), so a run that imported either is
    # not a faithful replay.
    result["backport_loaded"] = "importlib_metadata" in sys.modules
    result["pkg_resources_loaded"] = "pkg_resources" in sys.modules
    if not args.source:
        result["view"]["after"] = _view()
    _emit(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="save a tiny seeded AutoencoderKL")
    setup.add_argument("model")
    run = commands.add_parser("run", help="import diffusers (and in full mode run the SD path)")
    run.add_argument("--stage", choices=("cheap", "full"), required=True)
    run.add_argument("--model", required=True)
    view = run.add_mutually_exclusive_group(required=True)
    view.add_argument("--source", action="store_true", help="keep the environment's metadata")
    view.add_argument("--allow", nargs="*", metavar="NAME", help="replay the bundle view")
    args = parser.parse_args(argv)

    # A bundle has no tests/ directory on its path; keep e.g. tests/fixtures from turning into a
    # namespace package that find_spec could see.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or os.curdir) != here]

    if args.command == "setup":
        return _setup(args.model)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
