"""Build a standalone Photo Guard GUI with Nuitka through the uv environment.

The version lives in ``pyproject.toml`` only (G5): :func:`project_version` reads it instead of
a literal being copied into the Nuitka flags, the macOS bundle and the Inno Setup script.
``--print-version`` answers before the platform, model and metadata guards, because the release
workflow asks every runner (including ones that cannot build) for the version it is about to
stamp.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path
import platform
import subprocess
import sys
import tomllib

from photo_guard import config as pg_config

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MODEL = ROOT / "models" / "sd-vae-ft-mse"

# P74: a bundle has no *.dist-info, so distribution metadata exists only where
# --include-distribution-metadata puts it, and the SD path reads it at runtime. Keys are the
# real distribution names: the bundle's finder compares the queried name lower-cased with the
# real name, without PEP 503 folding. Values are the distribution's top-level modules: Nuitka
# ties the metadata to the first one and, if that package is not in the build, aborts after
# optimizing every module (before any C code is generated), so each one is also passed to
# --include-module unless NO_FORCE_INCLUDE_MODULES names it.
# tests/test_bundle_metadata.py proves the set is sufficient, and that each entry is needed.
RUNTIME_METADATA: dict[str, tuple[str, ...]] = {
    # diffusers' import-time version check (dependency_versions_check) reads these three;
    # without any one of them `import diffusers` fails, as in both release bundles.
    "requests": ("requests",),
    "filelock": ("filelock",),
    "numpy": ("numpy",),
    # is_torch_available(): without it diffusers exports a dummy AutoencoderKL whose
    # from_pretrained raises ImportError.
    "torch": ("functorch", "torch", "torchgen"),
    # is_accelerate_available(): without it from_pretrained logs a warning and falls back to
    # low_cpu_mem_usage=False.
    "accelerate": ("accelerate",),
    # The last three only flip a diffusers flag (the SD path ran without each); they keep every
    # diffusers is_*_available flag equal to the source environment the tests compare with.
    # Flags other packages read from metadata outside this set still differ in the bundle
    # (accelerate's tqdm check; huggingface_hub's httpx, Pillow and xet checks).
    # is_safetensors_available().
    "safetensors": ("safetensors",),
    # is_opencv_available(), which looks the real name up among the opencv-python variants.
    "opencv-python-headless": ("cv2",),
    # is_jinja_available(), huggingface_hub's flag that diffusers re-exports.
    "Jinja2": ("jinja2",),
}

# Modules of RUNTIME_METADATA that must not be forced in with --include-module. Nuitka lets an
# --include-module match (sub-modules included) outrank the anti-bloat plugin
# (importing/Recursion.py, _decideRecursion), so --include-module=numpy would override the
# anti-bloat rule "numpy: no-auto-follow numpy.distutils" and compile numpy.distutils plus a
# setuptools chain into the bundle. numpy needs no forcing: photo_guard imports it directly,
# and so do torch and diffusers, so the build compiles it and Nuitka's package check passes.
NO_FORCE_INCLUDE_MODULES = frozenset({"numpy"})


def project_version() -> str:
    """The single source of truth for the version string."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _check_runtime_metadata() -> None:
    """P74: refuse to start a multi-hour build that cannot embed ``RUNTIME_METADATA``."""
    for name, modules in RUNTIME_METADATA.items():
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit(f"runtime metadata: distribution {name!r} is not installed") from None
        # importlib normalises the lookup name, so a mis-cased or mis-separated key is still
        # found; Nuitka would then warn and embed the real name instead, and the key would no
        # longer be the name the bundle and the metadata tests use.
        real_name = distribution.metadata["Name"]
        if real_name != name:
            raise SystemExit(
                f"runtime metadata: key {name!r} must be the real distribution name {real_name!r}"
            )
        for module in modules:
            if importlib.util.find_spec(module) is None:
                raise SystemExit(
                    f"runtime metadata: module {module!r} of {name!r} is not importable"
                )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--print-version" in argv:
        print(project_version())
        return 0

    if platform.system() not in {"Windows", "Darwin"}:
        raise SystemExit("Desktop release builds are supported on Windows and macOS runners")
    if platform.system() == "Darwin" and platform.machine().lower() not in {"arm64", "aarch64"}:
        raise SystemExit("Only Apple Silicon macOS release builds are supported")
    if not pg_config.model_dir_is_complete(MODEL):
        raise SystemExit(f"bundled model is missing or incomplete: {MODEL}")
    _check_runtime_metadata()

    version = project_version()
    DIST.mkdir(exist_ok=True)
    command = [
        sys.executable, "-m", "nuitka",
        "--standalone", "--assume-yes-for-downloads",
        "--enable-plugin=pyside6", "--include-package=photo_guard",
        "--include-package=diffusers", "--include-package=torch",
        f"--include-data-dir={MODEL}=models/sd-vae-ft-mse",
        # G2: licence material must travel with the bundle; desktop_entry's smoke test
        # checks both files are reachable through resources.application_root().
        f"--include-data-dir={ROOT / 'licenses'}=licenses",
        f"--include-data-files={ROOT / 'LICENSE'}=LICENSE",
        f"--include-data-files={ROOT / 'THIRD_PARTY_NOTICES.md'}=THIRD_PARTY_NOTICES.md",
        "--output-dir=dist",
        "--product-name=Photo Guard", f"--file-version={version}",
        f"--product-version={version}", "--company-name=PhotoGuard",
        "--file-description=Offline photo anti-theft protection",
    ]
    command.extend(f"--include-distribution-metadata={name}" for name in RUNTIME_METADATA)
    command.extend(
        f"--include-module={module}"
        for modules in RUNTIME_METADATA.values()
        for module in modules
        if module not in NO_FORCE_INCLUDE_MODULES
    )
    if platform.system() == "Windows":
        command.extend(["--windows-console-mode=disable", "--output-filename=PhotoGuard.exe"])
    else:
        command.extend([
            "--macos-create-app-bundle", "--macos-app-name=Photo Guard",
            f"--macos-app-version={version}", "--macos-signed-app-name=com.photoguard.desktop",
        ])
    command.append(str(ROOT / "packaging" / "desktop_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
