"""Build a standalone Photo Guard GUI with Nuitka through the uv environment.

The version lives in ``pyproject.toml`` only (G5): :func:`project_version` reads it instead of
a literal being copied into the Nuitka flags, the macOS bundle and the Inno Setup script.
``--print-version`` answers before the platform and model guards, because the release workflow
asks every runner (including ones that cannot build) for the version it is about to stamp.
"""
from __future__ import annotations

from pathlib import Path
import platform
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MODEL = ROOT / "models" / "sd-vae-ft-mse"


def project_version() -> str:
    """The single source of truth for the version string."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--print-version" in argv:
        print(project_version())
        return 0

    if platform.system() not in {"Windows", "Darwin"}:
        raise SystemExit("Desktop release builds are supported on Windows and macOS runners")
    if platform.system() == "Darwin" and platform.machine().lower() not in {"arm64", "aarch64"}:
        raise SystemExit("Only Apple Silicon macOS release builds are supported")
    if not MODEL.is_dir():
        raise SystemExit(f"bundled model is missing: {MODEL}")

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
