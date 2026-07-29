"""Layer ① — invisible watermark via DWT-DCT-SVD.

New images use a small versioned envelope with CRC32. The low-level
``embed``/``extract`` functions remain raw for compatibility and focused tests.
"""
from __future__ import annotations

import base64
import binascii
import zlib

import numpy as np
from imwatermark import WatermarkDecoder, WatermarkEncoder

from . import config

_MAGIC = "PG1"


def embed(image_bgr: np.ndarray, payload: str) -> np.ndarray:
    encoder = WatermarkEncoder()
    encoder.set_watermark("bytes", payload.encode("utf-8"))
    return encoder.encode(image_bgr, config.WATERMARK_METHOD)


def extract(image_bgr: np.ndarray, payload_bytes: int) -> str:
    if payload_bytes <= 0:
        raise ValueError("payload_bytes must be positive")
    decoder = WatermarkDecoder("bytes", payload_bytes * 8)
    raw = decoder.decode(image_bgr, config.WATERMARK_METHOD)
    return raw.decode("utf-8", errors="replace")


def pack_payload(payload: str) -> str:
    raw = payload.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return f"{_MAGIC}:{crc:08x}:{encoded}"


def unpack_payload(stored: str) -> tuple[str, bool]:
    """Return ``(payload, verified)``; raw legacy payloads are unverified."""
    if not stored.startswith(f"{_MAGIC}:"):
        return stored, False
    try:
        _, crc_text, encoded = stored.split(":", 2)
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        expected = int(crc_text, 16)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid photo-guard watermark envelope") from exc
    if (zlib.crc32(raw) & 0xFFFFFFFF) != expected:
        raise ValueError("watermark CRC check failed")
    return raw.decode("utf-8"), True


def packed_size(payload: str) -> int:
    return len(pack_payload(payload).encode("utf-8"))
