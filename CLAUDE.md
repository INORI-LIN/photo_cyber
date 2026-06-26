# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Hard rules from AGENTS.md (non-negotiable)

`AGENTS.md` defines the protection scheme AND the toolchain rules. Two rules in §6 are enforced and any future change must respect them:

1. **No `pip` ever.** All dependency work goes through `uv` (`uv add`, `uv remove`, `uv sync`). Do not introduce a `requirements.txt`, do not run `pip install`, and do not suggest those to the user. CI / review will fail on `grep -RIn "pip install"` hits in code or scripts (the string is allowed inside `AGENTS.md` and `README.md` because they document the rule itself).
2. **Use `uv run`** for every Python invocation; never `source .venv/bin/activate` and run python directly.

The Python version is pinned to 3.11 via `.python-version`. Heavy ML deps (torch / diffusers / accelerate) are isolated in the `photoguard` optional extra — core users do `uv sync`, opt-in users do `uv sync --extra photoguard`.

## Common commands

```bash
# Setup (first time on a machine)
uv python install 3.11 && uv python pin 3.11
uv sync --frozen                       # core deps only
uv sync --extra photoguard --frozen    # + torch/diffusers for the SD perturber

# Run the CLI (both forms work)
uv run python -m photo_guard protect IN.jpg -o OUT.jpg [...]
uv run python -m photo_guard verify  SUSPECT.jpg --payload-bytes N
uv run photo-guard protect ...         # via [project.scripts]

# After editing dependencies
uv add <pkg>                           # main deps
uv add --optional photoguard <pkg>     # add to the optional extra

# Compliance check before committing
grep -RIn --exclude-dir=.venv --exclude-dir=.git \
     --exclude=uv.lock --exclude=AGENTS.md --exclude=README.md \
     "pip install" .   # must return nothing
```

## Docker (开箱即用镜像)

`Dockerfile` builds a single image that works on both CPU and GPU hosts (torch's CUDA runtime ships inside the wheels — no `nvidia/cuda` base needed). The SD VAE is **baked into the image** via `RUN uv run --no-sync photo-guard download-models` during build, so the runtime container is fully offline (`HF_HUB_OFFLINE=1` is set).

```bash
# Local build (≈5–10 min first time; subsequent rebuilds reuse the
# torch/diffusers layer if pyproject.toml + uv.lock unchanged)
docker build -t photo-guard:dev .

# Smoke (mirrors .github/workflows/docker.yml)
mkdir -p /tmp/pg && cp some.jpg /tmp/pg/in.jpg
docker run --rm -v /tmp/pg:/work photo-guard:dev \
    protect /work/in.jpg -o /work/out.jpg --perturber noise --payload ci-test
docker run --rm -v /tmp/pg:/work photo-guard:dev \
    verify /work/out.jpg --payload-bytes 7   # → "ci-test"

# Strongest "model is really baked in" assertion
docker run --rm --network none -v /tmp/pg:/work photo-guard:dev \
    protect /work/in.jpg -o /work/out_sd.jpg --perturber sd --perturber-steps 2 --long-edge 384
```

Build-step rules to preserve:

- **Only `RUN ... download-models` may touch the network at build time.** Everything else stays inside the wheels and the lockfile. Don't add `RUN curl …`, `RUN pip …`, etc. — see AGENTS.md §6.4.
- **`uv` binary comes from `COPY --from=ghcr.io/astral-sh/uv:latest /uv …`**, never `pip install uv` or a `curl | sh` install script.
- **`.dockerignore` must exclude `models/` and `.venv/`.** A user's local model copy or virtualenv would otherwise dominate build context (~5 GB) and would mask bugs in the in-image download step.

## Tests and CI

- `uv sync --group dev` brings in pytest. Then `uv run pytest -m 'not slow'` is the canonical fast-tier run (≈26 cases, ~11s). `slow`-marked tests exercise the real SD VAE attack and need `uv sync --extra photoguard` plus a HuggingFace download; do not run them unless explicitly asked.
- `.github/workflows/ci.yml` runs three steps: AGENTS.md 6.4 grep, `uv sync --frozen --group dev`, then the fast pytest tier. The grep step exists both in CI and as `tests/test_compliance.py` (belt and braces).
- Two pytest files act as fail-loud regression locks for the non-obvious decisions documented elsewhere here:
  - `tests/test_invisible_watermark_roundtrip.py::test_embed_survives_jpeg85_and_visible_watermark` pins `dwtDctSvd`. Reverting `config.WATERMARK_METHOD` to `dwtDct` reds it instantly.
  - `tests/test_pipeline_order.py::test_protect_then_verify_round_trip` is end-to-end and breaks if anyone "fixes" the resize-before-embed ordering.
- `tests/test_perturb_registry.py::test_importing_perturb_does_not_import_torch` guards the lazy-import contract for `SDEncoderPerturber`. Do not move `import torch` / `import diffusers` into `perturb.py` or any module loaded eagerly from `__init__.py` — the test will fail.

## Architecture: the three-layer pipeline

The whole package implements the AGENTS.md three-layer scheme. `pipeline.protect` is the only orchestrator and the **order is load-bearing** — changing it silently breaks the watermark:

```
load → fit_long_edge(1080) → ① embed (DWT-DCT-SVD) → ② perturb → ③ visible WM → save JPEG
```

`ProtectOptions.layers` (a `frozenset[str]` from `pipeline.ALL_LAYERS`) lets callers pick **which** of the three layers run. The order in the diagram above is fixed; the set only controls membership. Empty / unknown sets raise `ValueError` so the CLI can map them to exit code 2. The CLI exposes this as `--layers invisible,perturb,visible` (default = all three, comma-separated subset). When extending the pipeline, add new layers in canonical-order position with their own membership check — never make the set decide ordering.

Two non-obvious things future instances must know:

- **Resize happens BEFORE invisible-watermark embedding.** AGENTS.md §2 says "隐 → 扰 → 明" but §5 step 1 says resize first. They appear to conflict; the resolution (proven empirically and recorded in `pipeline.py`'s docstring) is that DWT-DCT is sensitive to geometric resampling, so embedding must happen on the post-resize pixels. Don't "fix" the order back to literal §2.
- **Invisible watermark uses `dwtDctSvd`, not plain `dwtDct`.** Plain `dwtDct` from `invisible-watermark` collapses at JPEG q≤95; the SVD variant survives q≥75. This is a deliberate choice in `config.WATERMARK_METHOD`. AGENTS.md §3① says "频域方案 (DWT-DCT)" — the SVD variant is in the same family.

### Module map and what is plug-replaceable

| File | Role | Plug-replaceable? |
|------|------|-------------------|
| `pipeline.py` | The only orchestrator. Read its docstring before reordering anything. | No |
| `cli.py` / `__main__.py` | argparse → `ProtectOptions` → `pipeline.protect`. | Add new flags here. |
| `config.py` | Single source of defaults for all layers. New tunables go here, not buried in modules. | Yes |
| `watermark_invisible.py` | Layer ① — `embed` / `extract`, thin wrapper over `imwatermark`. | Yes (whole-file) |
| `perturb.py` | Layer ② — `Perturber` ABC + name registry `_REGISTRY`. `get(name, **kwargs)` is the factory. | Yes — add a class, register, done |
| `photoguard.py` | The real PhotoGuard PGD attack on a SD VAE encoder. **Imports torch / diffusers and is loaded lazily by `perturb.SDEncoderPerturber.apply()` — never at import time.** | Yes |
| `subject.py` | Three-tier subject detection: haar face → Sobel-saliency window → geometric centre. Used only by visible-WM `subject` mode. Pure cv2, no extra deps (haar XML ships with `opencv-python-headless`). | Yes |
| `watermark_visible.py` | Layer ③ — `apply()` dispatches to `apply_subject` / `apply_tile` / `apply_center`. | Yes |
| `compress.py` | One function: `fit_long_edge`. | Yes |

When extending Layer ②, follow the existing pattern: subclass `Perturber`, accept tunables as kwargs with defaults from `config.py`, register in `_REGISTRY`, then add the matching CLI flags in `cli.py`. The pipeline doesn't need to change.

### Lazy import contract for optional extras

`perturb.py` must remain importable in the **core** environment (no diffusers). The pattern is: `SDEncoderPerturber.__init__` only stores config; the heavy import happens inside `_ensure()` which is called from `apply()`. If you add another optional-extra-backed perturber, replicate this — do not add top-level `import torch` anywhere outside `photoguard.py`.

If diffusers is missing, `photoguard._SDEncoderAttack._load` raises a `RuntimeError` whose message tells the user to run `uv sync --extra photoguard`. `cli.py` catches `RuntimeError` from `pipeline.protect` and prints it; preserve that path.

## Repo conventions

- **`AGENTS.md` is authoritative and not edited by code changes.** It defines the scheme; the implementation conforms to it. If you find a real conflict, surface it to the user rather than editing the spec.
- **Branch is `main` (renamed from the default `master` at init).** Remote is `origin → https://github.com/INORI-LIN/photo_cyber.git`.
- Commit messages so far follow `type(scope): 中文摘要` then a body in Chinese describing rationale. Match that style and add the existing `Co-Authored-By` trailer when committing.
- Do not push without explicit user confirmation — prior turns have established that `git push` is treated as a remote-effecting action requiring an OK.
