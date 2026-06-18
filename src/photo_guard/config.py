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

# Layer ② perturbation
DEFAULT_PERTURBER = "noop"  # AGENTS.md 三②: 预留接入位
NOISE_EPSILON = 2.0 / 255.0  # 肉眼几乎无感的轻量占位扰动

# PhotoGuard SD-encoder attack (AGENTS.md 三② 真实实现).
# Loaded lazily; only used when --perturber sd. ε in image-space [0,1].
PHOTOGUARD_MODEL_ID = "stabilityai/sd-vae-ft-mse"
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
