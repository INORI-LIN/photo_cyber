"""Centralized defaults for the three protection layers.

Values picked to match AGENTS.md sections 三 / 五:
- visible watermark alpha 5%-15% range, default 10%
- precompress long edge ~1080
"""
from __future__ import annotations

# Layer ① invisible watermark
# AGENTS.md 三①: 频域方案 (DWT-DCT 系) — dwtDctSvd is the SVD-augmented variant
# from the same family; in practice it survives JPEG q≥75 reliably while plain
# dwtDct collapses below q≈95. Since G1 the arithmetic is transcribed in-repo
# (`_dwt_dct_svd.py`), so dwtDctSvd is the only implemented method: any other
# value is rejected loudly by `watermark_invisible._require_method`.
WATERMARK_METHOD = "dwtDctSvd"
DEFAULT_PAYLOAD = "photo-guard"
# Layer ① carrier (P10, 2026-09-23). The payload used to ride channel 1 (the Cb/U chroma
# channel) at step 36. Every JPEG 4:2:0 re-encode -- our own save and the platform's
# re-compression alike -- decimates chroma, which wiped the block votes: measured round-trip
# pass rates were 31/66 and 17/66 over payload lengths 1..66. Luma is not decimated, so the
# carrier moves there; step 72 raises the per-block margin. Together they measured 66/66 on
# both fixtures, before AND after an extra platform-style re-encode.
CARRIER_CHANNEL = 0
CARRIER_SCALE = 72

# Read side tries the current carrier first, then these. A (channel, scale) mismatch fails
# bidirectionally (131 / 117 bit errors measured), so keeping the legacy entry is what makes
# already-published images stay verifiable.
LEGACY_CARRIERS = ((1, 36),)

# Legacy (raw, checksum-less) verification. These two are ADVISORY garbage filters
# only — they must never be presented as proof. Spike P3-A (2026-09-23, 335 rows over
# this repo's own fixtures) measured real products at mean_margin 0.2567-0.3247 and
# printable garbage at 0.2005-0.5000: the bands overlap completely, and a corrupted
# real product sits inside the true band at 0.2567. No threshold can separate them,
# which is why the raw path reports a clue and only the CRC envelope is evidence.
DEFAULT_MAX_PAYLOAD_BYTES = 128  # stored bytes; ceiling for the blind envelope search
LEGACY_MIN_MEAN_MARGIN = 0.20    # kills q50/q70/clean-texture/non-multiple-length garbage
LEGACY_MIN_BLOCKS_PER_BIT = 16   # advisory; unsatisfiable at the 320x320 floor for K >= 14

# Layer ② perturbation
DEFAULT_PERTURBER = "noop"  # explicit wiring/test mode; not AI protection
NOISE_EPSILON = 2.0 / 255.0  # 肉眼几乎无感的轻量占位扰动

# PhotoGuard SD-encoder attack (AGENTS.md 三② 真实实现).
# Loaded lazily; only used when --perturber sd. ε in image-space [0,1].
#
# Model is loaded **offline-only** from `models/sd-vae-ft-mse/` under the repo
# root — no HuggingFace request at runtime. Use `photo-guard download-models`
# (one-off) to populate that directory.
from . import resources as _resources

PHOTOGUARD_MODEL_NAME = "sd-vae-ft-mse"
# P33: probe the bundle's candidate roots before falling back to a single path, so a macOS
# bundle that keeps data-dirs in Contents/Resources and data-files in Contents/MacOS resolves
# either layout. The `or` fallback deliberately yields a non-existent path when the model was
# never shipped — the is_dir() checks (G6) must fail loudly, not silently succeed.
PHOTOGUARD_MODELS_DIR = _resources.find_resource("models") or (
    _resources.application_root() / "models"
)
PHOTOGUARD_REMOTE_REPO = "stabilityai/sd-vae-ft-mse"
# P15: the immutable commit the download and the loader both pin to, so the Docker bake and
# the desktop bundles are reproducible. Measured 2026-09-29 (last modified 2023-06-06).
PHOTOGUARD_REVISION = "31f26fdeee1355a5c34592e401dd41e45d25a493"
PHOTOGUARD_MODEL_ID = str(PHOTOGUARD_MODELS_DIR / PHOTOGUARD_MODEL_NAME)
PHOTOGUARD_EPSILON = 8.0 / 255.0
PHOTOGUARD_STEP_SIZE = 2.0 / 255.0
PHOTOGUARD_STEPS = 10

# Layer ③ visible watermark
# AGENTS.md 三③ wants "压在主体关键纹理上" — `subject` mode binds the
# watermark to a detected face/saliency box, which is the most faithful
# realisation. `tile` and `center` are kept as fallbacks / stylistic choices.
DEFAULT_VISIBLE_MODE = "subject"
DEFAULT_VISIBLE_TEXT = "© photo-guard"
DEFAULT_VISIBLE_ALPHA = 0.10  # AGENTS.md 三③: 5%–15% 平铺
DEFAULT_VISIBLE_FONT_SIZE = 36
DEFAULT_VISIBLE_ANGLE = 30.0
DEFAULT_VISIBLE_TILE_GAP = 220  # px

# Precompress (AGENTS.md 五)
DEFAULT_LONG_EDGE = 1080
DEFAULT_JPEG_QUALITY = 85
