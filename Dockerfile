# photo-guard — single image that works on both CPU and GPU hosts.
#
# torch 2.12.1 on Linux ships its CUDA runtime as separate PyPI wheels
# (nvidia-cudnn-cu13, nvidia-cublas, triton, …) so a python:3.11-slim base
# is sufficient: CPU hosts run as-is, GPU hosts add `--gpus all` and the
# `torch.cuda.is_available()` branch in src/photo_guard/photoguard.py picks
# CUDA automatically.
#
# Build:
#   docker build -t photo-guard:dev .
#
# Run (CPU):
#   docker run --rm -v "$PWD:/work" photo-guard:dev \
#     protect /work/in.jpg -o /work/out.jpg
#
# Run (GPU):
#   docker run --rm --gpus all -v "$PWD:/work" photo-guard:dev \
#     protect /work/in.jpg -o /work/out.jpg --perturber sd
#
# The image is fully offline at runtime: HF_HUB_OFFLINE=1 is set and the
# SD VAE weights are baked in at /app/models/sd-vae-ft-mse via the
# build-time `download-models` step (the one and only network-allowed
# call site, per src/photo_guard/download.py).

FROM python:3.11-slim AS runtime

# uv binary, copied from Astral's official image — never installed via
# pip and never via a `curl | sh` bootstrap. AGENTS.md §6 forbids pip;
# this is the recommended Astral pattern.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Minimal native deps for the wheels we use.
# - libgomp1: OpenMP runtime, linked by numpy/torch wheels.
# - libglib2.0-0 + libxcb1: opencv-python-headless still soft-links against
#   these two on debian:trixie. They're tiny (~1 MB combined) and cv2 fails
#   to import without them ("ImportError: libxcb.so.1"). Despite the name,
#   `headless` only drops the GUI/Qt deps — basic X protocol libs remain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
        libglib2.0-0 \
        libxcb1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Two-stage sync so changes to src/ don't bust the (huge) torch+diffusers
# layer:
#   1. COPY only the manifest/lock → `uv sync --no-install-project` installs
#      *only* the dependency tree. The project itself isn't built yet, so
#      src/ doesn't need to exist.
#   2. COPY src → second `uv sync` adds the project (editable) on top. This
#      layer is small and rebuilds on every code change.
COPY pyproject.toml uv.lock .python-version README.md /app/

RUN uv sync --frozen --extra photoguard --no-dev --no-install-project

COPY src /app/src

RUN uv sync --frozen --extra photoguard --no-dev

# Bake the SD VAE into the image. This is the only build step that
# reaches the network; the result is a fully self-contained model dir at
# /app/models/sd-vae-ft-mse, matching config.PHOTOGUARD_MODEL_ID.
RUN uv run --no-sync photo-guard download-models

# Lock runtime to offline mode — matches the os.environ.setdefault calls
# in photoguard.py, but applied unconditionally so users can't accidentally
# trigger a HuggingFace request from inside the container.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    UV_NO_SYNC=1

# /work is the conventional mount point for the user's input/output
# directory. /app stays as the read-only project root.
WORKDIR /work

ENTRYPOINT ["uv", "run", "--project", "/app", "--no-sync", "photo-guard"]
CMD ["--help"]
