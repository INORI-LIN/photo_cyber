"""Build a standalone Photo Guard GUI with Nuitka through the uv environment."""
from __future__ import annotations

from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MODEL = ROOT / "models" / "sd-vae-ft-mse"


def main() -> int:
    if platform.system() not in {"Windows", "Darwin"}:
        raise SystemExit("Desktop release builds are supported on Windows and macOS runners")
    if platform.system() == "Darwin" and platform.machine().lower() not in {"arm64", "aarch64"}:
        raise SystemExit("Only Apple Silicon macOS release builds are supported")
    if not MODEL.is_dir():
        raise SystemExit(f"bundled model is missing: {MODEL}")

    DIST.mkdir(exist_ok=True)
    command = [
        sys.executable, "-m", "nuitka",
        "--standalone", "--assume-yes-for-downloads",
        "--enable-plugin=pyside6", "--include-package=photo_guard",
        "--include-package=diffusers", "--include-package=torch",
        f"--include-data-dir={MODEL}=models/sd-vae-ft-mse",
        "--output-dir=dist",
        "--product-name=Photo Guard", "--file-version=0.1.0",
        "--product-version=0.1.0", "--company-name=PhotoGuard",
        "--file-description=Offline photo anti-theft protection",
    ]
    if platform.system() == "Windows":
        command.extend(["--windows-console-mode=disable", "--output-filename=PhotoGuard.exe"])
    else:
        command.extend([
            "--macos-create-app-bundle", "--macos-app-name=Photo Guard",
            "--macos-app-version=0.1.0", "--macos-signed-app-name=com.photoguard.desktop",
        ])
    command.append(str(ROOT / "packaging" / "desktop_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
