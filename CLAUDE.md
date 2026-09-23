# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Hard rules from AGENTS.md (non-negotiable)

`AGENTS.md` defines the protection scheme AND the toolchain rules. Two rules in §6 are enforced and any future change must respect them:

1. **No `pip` ever.** All dependency work goes through `uv` (`uv add`, `uv remove`, `uv sync`). Do not introduce a `requirements.txt`, do not run `pip install`, and do not suggest those to the user. CI / review will fail on `grep -RIn "pip install"` hits in code or scripts (the string is allowed inside `AGENTS.md` and `README.md` because they document the rule itself).
2. **Use `uv run`** for every Python invocation; never `source .venv/bin/activate` and run python directly.

The Python version is pinned to 3.11 via `.python-version`. Heavy ML deps (torch / diffusers / accelerate) are isolated in the `photoguard` optional extra. PySide6 is isolated in the `desktop` extra, and Nuitka lives in the `package` dependency group.

## Common commands

```bash
# Setup (first time on a machine)
uv python install 3.11 && uv python pin 3.11
uv sync --frozen                       # core deps only
uv sync --extra photoguard --frozen    # + torch/diffusers for the SD perturber
uv sync --extra desktop --frozen       # + PySide6 desktop GUI
uv sync --extra desktop --extra photoguard --group package --frozen  # release build

# Run the CLI (both forms work)
uv run python -m photo_guard protect IN.jpg -o OUT.jpg [...]
uv run python -m photo_guard verify  SUSPECT.jpg --payload-bytes N
uv run photo-guard protect ...         # via [project.scripts]
uv run photo-guard download-models     # one-off: fetch SD VAE into models/ for fully offline runs
uv run photo-guard devices             # list CPU/CUDA/MPS and unsupported adapters
uv run photo-guard-gui                  # launch the PySide6 desktop app

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
    protect /work/in.jpg -o /work/out.jpg --layers invisible,perturb,visible --perturber noise --payload ci-test
docker run --rm -v /tmp/pg:/work photo-guard:dev \
    verify /work/out.jpg --payload-bytes 7   # → 线索（未验证）: ci-test
docker run --rm -v /tmp/pg:/work photo-guard:dev \
    verify /work/out_sd.jpg                  # → ci-test（盲检信封，无需长度）

# Strongest "model is really baked in" assertion
docker run --rm --network none -v /tmp/pg:/work photo-guard:dev \
    protect /work/in.jpg -o /work/out_sd.jpg --layers invisible,perturb,visible --perturber sd --perturber-steps 2 --long-edge 384
```

Build-step rules to preserve:

- **Only `RUN ... download-models` may touch the network at build time.** Everything else stays inside the wheels and the lockfile. Don't add `RUN curl …`, `RUN pip …`, etc. — see AGENTS.md §6.4.
- **`uv` binary comes from `COPY --from=ghcr.io/astral-sh/uv:latest /uv …`**, never `pip install uv` or a `curl | sh` install script.
- **`.dockerignore` must exclude `models/` and `.venv/`.** A user's local model copy or virtualenv would otherwise dominate build context (~5 GB) and would mask bugs in the in-image download step.

## Tests and CI

- `uv sync --group dev` brings in pytest. Then `uv run pytest -m 'not slow'` is the canonical fast-tier run (≈55 cases, ~20s). `slow`-marked tests exercise the real SD VAE attack and need `uv sync --extra photoguard` plus a local model prepared by `photo-guard download-models`; do not run them unless explicitly asked.
- `.github/workflows/ci.yml` runs a matrix over `ubuntu-latest` + `windows-latest`. The shell-based `pip install` grep step is Linux-only (POSIX `grep`); on Windows the same check is enforced by `tests/test_compliance.py`, which is a pure-Python `Path.rglob` walk that runs on every OS via pytest. Belt and braces — do not delete either.
- `.github/workflows/docker.yml` builds the all-in-one image, smoke-tests it (protect+verify with `--perturber noise`, then a `--network none` run with `--perturber sd` to prove the SD VAE is really baked in), and does not push. The runner uses `jlumbroso/free-disk-space@main` because GitHub-hosted ubuntu has only ~14 GB free and torch + nvidia wheels + SD VAE export to ~6 GB.
- Pytest files that act as fail-loud regression locks for non-obvious decisions documented elsewhere here:
  - `tests/test_invisible_watermark_roundtrip.py::test_embed_survives_jpeg85_and_visible_watermark` pins `dwtDctSvd`. Reverting `config.WATERMARK_METHOD` to `dwtDct` reds it instantly.
  - `tests/test_pipeline_order.py::test_protect_then_verify_round_trip` is end-to-end and breaks if anyone "fixes" the resize-before-embed ordering.
  - `tests/test_pipeline_layers.py` parametrises every non-empty subset of `{invisible, perturb, visible}` plus the empty/unknown cases — locks the "membership-only, never reorder" contract on `--layers`.
  - `tests/test_perturb_registry.py::test_importing_perturb_does_not_import_torch` guards the lazy-import contract for `SDEncoderPerturber`. Do not move `import torch` / `import diffusers` into `perturb.py` or any module loaded eagerly from `__init__.py` — the test will fail.

## Architecture: the three-layer pipeline

The whole package implements the AGENTS.md three-layer scheme. `pipeline.protect` is the only orchestrator and the **order is load-bearing** — changing it silently breaks the watermark:

```
load → fit_long_edge(1080) → ① embed (DWT-DCT-SVD) → ② perturb → ③ visible WM → save JPEG
```

`ProtectOptions.layers` (a `frozenset[str]` from `pipeline.ALL_LAYERS`) lets callers pick **which** of the three layers run. The order in the diagram above is fixed; the set only controls membership. Empty / unknown sets raise `ValueError` so the CLI can map them to exit code 2. The CLI exposes this as a comma-separated subset. The safe default is `--layers invisible,visible`; PhotoGuard must be explicitly enabled with the `perturb` layer and a non-noop perturber. When extending the pipeline, add new layers in canonical-order position with their own membership check — never make the set decide ordering.

Two non-obvious things future instances must know:

- **Resize happens BEFORE invisible-watermark embedding.** AGENTS.md §2 says "隐 → 扰 → 明" but §5 step 1 says resize first. They appear to conflict; the resolution (proven empirically and recorded in `pipeline.py`'s docstring) is that DWT-DCT is sensitive to geometric resampling, so embedding must happen on the post-resize pixels. Don't "fix" the order back to literal §2.
- **Invisible watermark uses `dwtDctSvd`, not plain `dwtDct`.** Plain `dwtDct` from `invisible-watermark` collapses at JPEG q≤95; the SVD variant survives q≥75. This is a deliberate choice in `config.WATERMARK_METHOD`. AGENTS.md §3① says "频域方案 (DWT-DCT)" — the SVD variant is in the same family.

### Module map and what is plug-replaceable

| File | Role | Plug-replaceable? |
|------|------|-------------------|
| `pipeline.py` | The only orchestrator. Read its docstring before reordering anything. Refuses an output path that is the input file (`_same_file`, AGENTS.md 五). | No |
| `outputs.py` | Atomic write + batch naming (`save_image_atomic`, `plan_batch`, `sanitize_suffix`). stdlib + Pillow only — never add Qt or torch here. Output naming has exactly ONE implementation and the GUI/CLI both consume it; do not reintroduce a second one (a tautological test once hid that duplication). | Yes |
| `cli.py` / `__main__.py` | argparse → `ProtectOptions` → `pipeline.protect`. | Add new flags here. |
| `config.py` | Single source of defaults for all layers. New tunables go here, not buried in modules. | Yes |
| `watermark_invisible.py` | Layer ① — `embed`, plus **two read paths with different authority**: the CRC envelope (integrity-checked, supports blind discovery) and the checksum-less raw path (a *clue* only). Contains a transcription of `imwatermark.dwtDctSvd`'s block scan, proven byte-exact against the library (spike P3-B) — keep it in sync if the library's `scales`/`block` defaults change. | Yes (whole-file) |
| `perturb.py` | Layer ② — `Perturber` ABC + name registry `_REGISTRY`. `get(name, **kwargs)` is the factory. | Yes — add a class, register, done |
| `photoguard.py` | The real PhotoGuard PGD attack on a SD VAE encoder. **Imports torch / diffusers and is loaded lazily by `perturb.SDEncoderPerturber.apply()` — never at import time.** Loads weights with `local_files_only=True` from `<repo>/models/sd-vae-ft-mse` only — runtime never touches HuggingFace. | Yes |
| `download.py` | One-off model fetcher (`photo-guard download-models`). The **only** module allowed to talk to HuggingFace; called once at install/build time, never at runtime. Docker `RUN` invokes it during build to bake the SD VAE into the image. | No (intentionally minimal — don't broaden the network surface) |
| `subject.py` | Three-tier subject detection: haar face → Sobel-saliency window → geometric centre. Used only by visible-WM `subject` mode. Pure cv2, no extra deps (haar XML ships with `opencv-python-headless`). | Yes |
| `watermark_visible.py` | Layer ③ — `apply()` dispatches to `apply_subject` / `apply_tile` / `apply_center`. `_load_font` walks a list of conventional TTF paths (Linux Debian/RHEL, macOS, Windows) before falling back to Pillow's bitmap default. Don't shrink that list — Pillow's bitmap default ignores `size`, which silently breaks `--visible-text` on systems with no matching TTF. | Yes |
| `compress.py` | `fit_long_edge`; zero preserves original size and negative values are invalid. | Yes |
| `device.py` | Lazy CPU/CUDA/MPS discovery and explicit backend selection. | Yes |
| `gui.py` | PySide6 batch protect/verify UI; work runs outside the Qt main thread. | Yes |
| `resources.py` | Resolves models/resources in source and frozen app layouts. | No |

When extending Layer ②, follow the existing pattern: subclass `Perturber`, accept tunables as kwargs with defaults from `config.py`, register in `_REGISTRY`, then add the matching CLI flags in `cli.py`. The pipeline doesn't need to change.

### Lazy import contract for optional extras

`perturb.py` must remain importable in the **core** environment (no diffusers). The pattern is: `SDEncoderPerturber.__init__` only stores config; the heavy import happens inside `_ensure()` which is called from `apply()`. If you add another optional-extra-backed perturber, replicate this — do not add top-level `import torch` anywhere outside `photoguard.py`.

If diffusers is missing, `photoguard._SDEncoderAttack._load` raises a `RuntimeError` whose message tells the user to run `uv sync --extra photoguard`. `cli.py` catches `RuntimeError` from `pipeline.protect` and prints it; preserve that path.

## Repo conventions

- **`AGENTS.md` is authoritative and not edited by code changes.** It defines the scheme; the implementation conforms to it. If you find a real conflict, surface it to the user rather than editing the spec.
- **Branch is `main` (renamed from the default `master` at init).** Remote is `origin → https://github.com/INORI-LIN/photo_cyber.git`.
- Commit messages so far follow `type(scope): 中文摘要` then a body in Chinese describing rationale. Match that style and add the existing `Co-Authored-By` trailer when committing.
- Do not push without explicit user confirmation — prior turns have established that `git push` is treated as a remote-effecting action requiring an OK.

## Desktop application and release packaging

- `src/photo_guard/gui.py` is the PySide6 desktop UI. Keep image processing in workers; never run the pipeline on the Qt main thread.
- GUI defaults to invisible + visible watermark and uses the CRC payload envelope; its verify tab can **blind-discover** the envelope instead of being told the payload length. The CLI stays raw-payload compatible, but that path is now reported as a **clue, never a proof** (spike P3-A proved no threshold separates real products from printable garbage) — see `docs/fix-plan.md` §6 P3.
- Supported accelerated devices are CUDA and MPS. Unsupported adapters are display-only and use CPU.
- Desktop dependencies are in the `desktop` optional extra; Nuitka is in the `package` dependency group.
- `packaging/build_desktop.py` must run on the target OS. Release CI produces Windows x64 and Apple Silicon macOS artifacts; Intel macOS is intentionally unsupported.
