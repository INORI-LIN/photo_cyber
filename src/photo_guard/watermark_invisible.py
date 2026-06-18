"""Layer ① — invisible watermark via DWT-DCT (AGENTS.md 三①).

Frequency-domain embedding survives JPEG re-compression and mild scaling.
Backed by `invisible-watermark` (method='dwtDct').
"""
from __future__ import annotations

import numpy as np
from imwatermark import WatermarkDecoder, WatermarkEncoder

from . import config


def embed(image_bgr: np.ndarray, payload: str) -> np.ndarray:
    """Embed `payload` (utf-8) into BGR uint8 image via DWT-DCT."""
    encoder = WatermarkEncoder()
    encoder.set_watermark("bytes", payload.encode("utf-8"))
    return encoder.encode(image_bgr, config.WATERMARK_METHOD)


def extract(image_bgr: np.ndarray, payload_bytes: int) -> str:
    """Extract a `payload_bytes`-long utf-8 payload (length must match embed)."""
    decoder = WatermarkDecoder("bytes", payload_bytes * 8)
    raw = decoder.decode(image_bgr, config.WATERMARK_METHOD)
    return raw.decode("utf-8", errors="replace")
