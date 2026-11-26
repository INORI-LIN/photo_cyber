"""P74 — the desktop bundle's runtime-metadata allowlist is sufficient, minimal and complete.

A Nuitka bundle carries no ``*.dist-info``, yet diffusers and accelerate read distribution
metadata at runtime: on 2026-11-19 (release run 44473940993) both bundles died in
``import diffusers`` on the missing ``requests`` metadata. The bundle sees exactly the
distributions named in ``build_desktop.RUNTIME_METADATA``. ``tests/_metadata_probe.py`` replays
that view in a child process -- torch and diffusers are never imported by this process -- and
the cases below compare it with the source environment:

1. sufficiency: with only the allowlist, diffusers imports, every no-argument
   ``is_*_available()`` and every diffusers warning equals the source environment, and the SD
   path (a tiny seeded VAE: ``latent_norm`` plus one PGD step) works; the view's distribution
   objects answer like Nuitka's (``files`` is None, top_level.txt is one package);
2. necessity: dropping any single entry changes something observable;
3. anchor: with nothing allowed, the import fails with the release log's text;
4. mapping: each entry lists exactly its distribution's importable top-level modules, among
   them the package Nuitka insists on finding in the build (``build_desktop`` passes each to
   ``--include-module`` unless ``NO_FORCE_INCLUDE_MODULES`` leaves it to import following).

Two more cases check the probe itself: it picks Nuitka's package the way ``hasModule`` does,
and its children share one bytecode cache.

Neither ``slow`` nor ``gui``: the release legs run it with all extras before the model download
(the tiny model is built in tmp), and the core legs skip it with the command that enables it.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from photo_guard import config
from tests.support import REPO_ROOT, load_script

PROBE = REPO_ROOT / "tests" / "_metadata_probe.py"
BUILD_DESKTOP = REPO_ROOT / "packaging" / "build_desktop.py"
PROBE_TIMEOUT = 300
# The probe's module level is stdlib-only, so loading it here imports neither torch nor diffusers.
probe = load_script(PROBE, "pg_metadata_probe")

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or importlib.util.find_spec("diffusers") is None,
    reason="needs the photoguard extra (torch + diffusers): uv sync --extra photoguard",
)

# Flags the source environment must report True: each one is how an allowlisted distribution
# shows up, so "equal to the baseline" would prove little if the baseline lacked them.
_SOURCE_FLAGS = (
    "is_accelerate_available",
    "is_jinja_available",
    "is_opencv_available",
    "is_safetensors_available",
    "is_torch_available",
)


@dataclass(frozen=True)
class ProbeRun:
    args: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    result: dict | None


@dataclass(frozen=True)
class ProbeRuns:
    model: Path
    pycache: Path
    allowlist: list[str]
    runs: dict[str, ProbeRun]


def _runtime_metadata() -> dict[str, tuple[str, ...]]:
    return load_script(BUILD_DESKTOP, "pg_build_desktop_p74").RUNTIME_METADATA


def _text(output: str | bytes | None) -> str:
    # A timed-out child's partial output can still be bytes (POSIX collects it undecoded).
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


def _parse(stdout: str) -> dict | None:
    begin, end = stdout.find(probe.BEGIN), stdout.find(probe.END)
    if begin < 0 or end < begin:
        return None
    return json.loads(stdout[begin + len(probe.BEGIN):end])


def _run_probe(*args: str, pycache: Path) -> ProbeRun:
    env = {
        **os.environ,
        # Every child of one run shares this bytecode cache: torch and diffusers compile once
        # per run instead of once per child (fresh CI venvs ship no pyc), and the bytecode
        # lands in pytest's tmp, never in the repository or the venv (P79).
        "PYTHONPYCACHEPREFIX": str(pycache),
        "HF_HUB_OFFLINE": "1",
        # The Windows release leg would otherwise encode the child's stdout with the ANSI code
        # page (d07128f).
        "PYTHONIOENCODING": "utf-8",
    }
    # A parent that sets PYTHONDONTWRITEBYTECODE (the local P79 hygiene) would otherwise pass
    # it on and defeat the cache.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    command = (sys.executable, str(PROBE), *args)
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = f"{_text(exc.stderr)}\n[probe timed out after {PROBE_TIMEOUT} s]"
        return ProbeRun(args, None, _text(exc.stdout), stderr, None)
    return ProbeRun(
        args, completed.returncode, completed.stdout, completed.stderr, _parse(completed.stdout)
    )


def _run_args(model: Path, stage: str, allowed: list[str] | None) -> tuple[str, ...]:
    view = ("--source",) if allowed is None else ("--allow", *allowed)
    return ("run", "--stage", stage, "--model", str(model), *view)


def _failure(run: ProbeRun) -> str:
    tail = "\n".join(run.stderr.splitlines()[-40:])
    return (
        f"probe {' '.join(run.args)} exited {run.returncode}\n"
        f"--- result ---\n{run.result}\n--- stderr tail ---\n{tail}"
    )


def _result(run: ProbeRun) -> dict:
    assert run.returncode == 0 and run.result is not None, _failure(run)
    return run.result


def _emulated(run: ProbeRun, allowed: list[str]) -> dict:
    """A bundle-view result whose view held exactly ``allowed`` from start to finish."""
    result = _result(run)
    view = result["view"]
    # Another finder answering, or one added mid-run (the importlib_metadata backport appends
    # its own), would make every conclusion about a larger view than the bundle's.
    assert view["before"] == view["after"] == sorted(allowed), _failure(run)
    return result


def _sd_path_problem(result: dict) -> str | None:
    if result["load_error"] is not None:
        return f"load error: {result['load_error']}"
    norm = result["vae"]["latent_norm"]
    if not isinstance(norm, float) or not math.isfinite(norm):
        return f"latent_norm is not finite: {norm!r}"
    pgd = result["pgd"]
    if pgd["shape"] != [8, 8, 3] or pgd["dtype"] != "uint8":
        return f"PGD output is not an 8x8x3 uint8 image: {pgd}"
    if pgd["budget"] != math.ceil(config.PHOTOGUARD_EPSILON * 255) + 1:
        return f"PGD budget is not ceil(epsilon*255)+1: {pgd}"
    if not 0 < pgd["max_delta"] <= pgd["budget"]:
        return f"PGD moved no pixel or left the budget: {pgd}"
    return None


def _difference(result: dict, baseline: dict) -> str | None:
    """What tells ``result`` apart from the source environment, or None."""
    if result["import_error"] is not None:
        return f"import fails: {result['import_error']['type']}"
    flags, expected = result["flags"], baseline["flags"]
    changed = sorted(
        name for name in flags.keys() | expected.keys() if flags.get(name) != expected.get(name)
    )
    if changed:
        return "flags differ: " + ", ".join(changed)
    if result["warnings"]["import"] != baseline["warnings"]["import"]:
        return "import warnings differ"
    if result["stage"] != "full":
        return None
    if result.get("autoencoder_kl") != baseline["autoencoder_kl"]:
        return f"AutoencoderKL is {result.get('autoencoder_kl')}"
    if result["warnings"]["load"] != baseline["warnings"]["load"]:
        return "load warnings differ"
    return _sd_path_problem(result)


@pytest.fixture(scope="module")
def probes(tmp_path_factory) -> ProbeRuns:
    allowlist = list(_runtime_metadata())
    model = tmp_path_factory.mktemp("p74") / "tiny-vae"
    pycache = tmp_path_factory.mktemp("p74-pycache")
    _result(_run_probe("setup", str(model), pycache=pycache))

    jobs = {
        "baseline": _run_args(model, "full", None),
        "allowlist": _run_args(model, "full", allowlist),
        "empty": _run_args(model, "cheap", []),
    }
    for name in allowlist:
        rest = [other for other in allowlist if other != name]
        # The cheap stage suffices unless it ties with the baseline (see the necessity case).
        jobs[f"without {name}"] = _run_args(model, "cheap", rest)
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        futures = {
            key: pool.submit(_run_probe, *args, pycache=pycache) for key, args in jobs.items()
        }
        runs = {key: future.result() for key, future in futures.items()}
    return ProbeRuns(model, pycache, allowlist, runs)


def test_probe_children_share_one_bytecode_cache(monkeypatch, tmp_path) -> None:
    """The children write bytecode to the run's cache, even under a no-bytecode parent."""
    seen: dict[str, str] = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_probe("setup", str(tmp_path / "model"), pycache=tmp_path / "pycache")
    assert "PYTHONDONTWRITEBYTECODE" not in seen
    assert seen["PYTHONPYCACHEPREFIX"] == str(tmp_path / "pycache")
    assert seen["HF_HUB_OFFLINE"] == "1"
    assert seen["PYTHONIOENCODING"] == "utf-8"


def test_allowlist_view_reproduces_the_source_environment(probes) -> None:
    baseline = _result(probes.runs["baseline"])
    assert baseline["import_error"] is None, _failure(probes.runs["baseline"])
    assert {flag: baseline["flags"].get(flag) for flag in _SOURCE_FLAGS} == dict.fromkeys(
        _SOURCE_FLAGS, True
    )
    assert _sd_path_problem(baseline) is None, _failure(probes.runs["baseline"])

    run = probes.runs["allowlist"]
    allowed = _emulated(run, probes.allowlist)
    semantics = allowed["view"]["semantics"]
    # Nuitka matches the queried name lower-cased against the real name: no PEP 503 folding.
    assert semantics == {
        query: any(query.lower() == name.lower() for name in probes.allowlist)
        for query in semantics
    }
    if "opencv-python-headless" in probes.allowlist:
        assert semantics["opencv-python-headless"] is True
        assert semantics["opencv_python_headless"] is False
    # The bundle's distribution objects answer METADATA, entry_points.txt and top_level.txt
    # only: no RECORD, so files is None, and top_level.txt is the one package Nuitka ties the
    # metadata to (worked out here from the real dist-info, not from the child's snapshot).
    assert allowed["view"]["objects"] == {
        name: {
            "files_is_none": True,
            "top_level_txt": probe.nuitka_top_level(importlib.metadata.distribution(name)) + "\n",
        }
        for name in probes.allowlist
    }
    assert allowed["import_error"] is None, _failure(run)
    assert allowed["flags"] == baseline["flags"]
    assert allowed["warnings"] == baseline["warnings"]
    assert allowed["autoencoder_kl"] == baseline["autoencoder_kl"]
    assert _sd_path_problem(allowed) is None, _failure(run)
    # Same seeded weights, CPU float32: the replayed view must load and attack them the same way.
    assert math.isclose(
        allowed["vae"]["latent_norm"], baseline["vae"]["latent_norm"], rel_tol=1e-6
    )
    assert allowed["pgd"] == baseline["pgd"]
    # Both read real dist-info on their own, which would bypass the replayed view.
    assert allowed["backport_loaded"] is False
    assert allowed["pkg_resources_loaded"] is False


def test_every_allowlisted_distribution_is_necessary(probes) -> None:
    baseline = _result(probes.runs["baseline"])
    unnecessary = []
    for name in probes.allowlist:
        rest = [other for other in probes.allowlist if other != name]
        if _difference(_emulated(probes.runs[f"without {name}"], rest), baseline) is not None:
            continue
        # Same flags and import warnings: only the SD path can still tell the views apart.
        full = _run_probe(*_run_args(probes.model, "full", rest), pycache=probes.pycache)
        if _difference(_emulated(full, rest), baseline) is None:
            unnecessary.append(name)
    assert not unnecessary, f"dropping these changes nothing observable: {unnecessary}"


def test_empty_view_fails_like_the_release_bundles(probes) -> None:
    run = probes.runs["empty"]
    error = _emulated(run, [])["import_error"]
    assert error is not None and error["type"] == "PackageNotFoundError", _failure(run)
    # What both bundles logged on 2026-11-19, from diffusers' import-time version check.
    assert "No package metadata" in error["message"], error
    assert "'requests'" in error["message"], error


def test_runtime_metadata_lists_each_distributions_top_level_modules() -> None:
    owners: dict[str, set[str]] = defaultdict(set)
    for top_level, names in importlib.metadata.packages_distributions().items():
        for name in names:
            owners[name].add(top_level)
    for name, modules in _runtime_metadata().items():
        importable = sorted(m for m in owners.get(name, ()) if probe.importable_top_level(m))
        assert sorted(modules) == importable, name
        # Nuitka ties the metadata to this package and stops the build when it is missing.
        assert probe.nuitka_top_level(importlib.metadata.distribution(name)) in modules, name


def test_nuitka_top_level_takes_any_findable_name(monkeypatch, tmp_path) -> None:
    """Nuitka's ``hasModule`` accepts any name it can locate, identifier or not.

    charset-normalizer's mypyc wheels list a helper module such as
    ``81d243bd2c585b0f4821__mypyc`` first in top_level.txt; that helper, not the package, is
    what Nuitka ties the metadata to, so a mypyc entry would have to list it.
    """
    helper = "81d243bd2c585b0f4821__mypyc"
    (tmp_path / f"{helper}.py").write_text("", encoding="utf-8")
    (tmp_path / "pg_probe_fake").mkdir()
    (tmp_path / "pg_probe_fake" / "__init__.py").write_text("", encoding="utf-8")
    info = tmp_path / "pg_probe_fake-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pg-probe-fake\nVersion: 1.0\n", encoding="utf-8"
    )
    (info / "top_level.txt").write_text(f"{helper}\npg_probe_fake\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert probe.nuitka_top_level(importlib.metadata.PathDistribution(info)) == helper
