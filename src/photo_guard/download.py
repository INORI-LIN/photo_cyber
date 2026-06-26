"""One-off model downloader.

Pulls the SD VAE used by :mod:`.photoguard` into the project-local
``models/`` directory so subsequent ``protect --perturber sd`` runs load
fully offline (no HuggingFace request at runtime).

This is the *only* place in the package allowed to talk to HuggingFace.
``photoguard.py`` itself uses ``local_files_only=True``.
"""
from __future__ import annotations

from pathlib import Path

from . import config


def download_sd_vae(
    *,
    repo: str = config.PHOTOGUARD_REMOTE_REPO,
    dest: Path | str | None = None,
) -> Path:
    """Download `repo` to ``models/<basename>/``; return the local path.

    Idempotent — if the destination already contains the full snapshot,
    HuggingFace's local cache short-circuits the network round trip.
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Model download needs the optional `photoguard` extra "
            "(provides huggingface_hub via diffusers). Install with: "
            "`uv sync --extra photoguard`"
        ) from exc

    if dest is None:
        dest = config.PHOTOGUARD_MODELS_DIR / config.PHOTOGUARD_MODEL_NAME
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # `local_dir` makes HF copy snapshot files directly into our path
    # rather than only populating the user-level cache. That gives us a
    # self-contained, relocatable model directory under the repo.
    snapshot_download(
        repo_id=repo,
        local_dir=str(dest),
        local_dir_use_symlinks=False,
        # We DO want network access here — this is the one explicit
        # online step. Don't set HF_HUB_OFFLINE before reaching this.
    )
    return dest
