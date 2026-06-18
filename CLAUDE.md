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

There is no test suite or linter configured yet — the README lists "单元测试 / CI" as an open todo. Do not invent a `pytest` / `ruff` invocation; if you need to validate a change, run the CLI end-to-end on a synthetic image (the pattern used during development is `protect → verify`, asserting the payload round-trips).

## Architecture: the three-layer pipeline

The whole package implements the AGENTS.md three-layer scheme. `pipeline.protect` is the only orchestrator and the **order is load-bearing** — changing it silently breaks the watermark:

```
load → fit_long_edge(1080) → ① embed (DWT-DCT-SVD) → ② perturb → ③ visible WM → save JPEG
```

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
