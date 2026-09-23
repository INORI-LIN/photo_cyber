"""Centralized defaults for the three protection layers.

Values picked to match AGENTS.md sections 三 / 五:
- visible watermark alpha 5%-15% range, default 10%
- precompress long edge ~1080
"""
from __future__ import annotations

# Layer ① invisible watermark
# AGENTS.md 三①: 频域方案 (DWT-DCT 系) — dwtDctSvd is the SVD-augmented variant
# from the same family; in practice it survives JPEG q≥75 reliably while plain
# dwtDct collapses below q≈95. Use SVD by default; switch to dwtDct only when
# encoder/decoder must both be the lighter variant.
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
PHOTOGUARD_MODELS_DIR = _resources.application_root() / "models"
PHOTOGUARD_REMOTE_REPO = "stabilityai/sd-vae-ft-mse"
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
