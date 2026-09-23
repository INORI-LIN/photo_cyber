"""Layer ① — invisible watermark via DWT-DCT-SVD.

Two read paths, deliberately unequal in authority:

* **Envelope** (``pack_payload`` / ``find_envelope`` / ``extract_envelope``): the stored
  string starts with a ``PG1:<crc32>:<base64>`` header, so a decoded candidate is either
  integrity-checked or rejected. This is the only path that constitutes 确权 evidence.
* **Legacy raw** (``extract_legacy``): no checksum exists, and no threshold can stand in
  for one. Spike P3-A (2026-09-23, 335 rows over this repo's own fixtures) measured real
  products at ``mean_margin`` 0.2567-0.3247 against printable garbage at 0.2005-0.5000 —
  the bands overlap completely, and a corrupted real product sits inside the true band at
  0.2567. This path therefore returns a *clue* (:class:`LegacyExtraction`), never a proof.

The block layout below is a transcription of ``imwatermark.dwtDctSvd`` with its defaults
(``scales=[0, 36, 0]``, ``block=4`` and the ``//4*4`` crop) and was proven byte-for-byte
equal to ``WatermarkDecoder("bytes", n * 8).decode(..., "dwtDctSvd")`` on 264/264 cases
(4 images x n = 1..66; spike P3-B). Re-check it if those library defaults ever change.
"""
from __future__ import annotations

import base64
import binascii
import unicodedata
import zlib
from dataclasses import dataclass

import cv2
import numpy as np
import pywt
from imwatermark import WatermarkDecoder
from imwatermark.dwtDctSvd import EmbedDwtDctSvd

from . import config

_MAGIC = "PG1"

# Transcribed from imwatermark.dwtDctSvd's defaults. Only channel 1 — the Cb/U channel of
# BGR2YUV — carries the watermark, because scales[0] and scales[2] are both 0.
_SCALE = 36
_BLOCK = 4
_DWT_CROP = 4
_DECISION = 127.0 / 255.0  # the library tests `avg * 255 > 127`


def _scales_for(channel: int, scale: int) -> list[int]:
    """The library's ``scales`` vector for a single carrier channel."""
    return [scale if index == channel else 0 for index in range(3)]


def carrier_candidates() -> tuple[tuple[int, int], ...]:
    """Carriers to try on read, current first.

    A ``(channel, scale)`` mismatch scrambles the reading rather than degrading it (measured
    131 / 117 bit errors either way round), so already-released images only stay readable if
    the legacy carrier is still tried.
    """
    current = (config.CARRIER_CHANNEL, config.CARRIER_SCALE)
    ordered: list[tuple[int, int]] = []
    for candidate in (current, *config.LEGACY_CARRIERS):
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


class _CarrierEmbed(EmbedDwtDctSvd):
    """Embedder that fixes the library's H/V detail-band swap (P11).

    ``imwatermark`` 0.2.0 unpacks ``dwt2`` as ``(h1, v1, d1)`` but hands ``idwt2``
    ``(v1, h1, d1)`` (``dwtDctSvd.py:27`` vs ``:30``), swapping the horizontal and vertical
    detail bands on the way back. Extraction only reads ``cA``, so the swap is invisible to
    decoding — but it injects an unintended image distortion: negligible while the carrier was
    chroma (mean 0.50 / max 19 of 255) and clearly visible once the carrier moved to luma
    (mean 10.3–12.8 / max 106). AGENTS.md forbids editing the dependency, hence a subclass.
    ``cA`` itself is bit-identical to the library's, so images stay mutually readable.
    """

    def encode(self, bgr: np.ndarray) -> np.ndarray:
        row, col = bgr.shape[:2]
        yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
        for channel in range(2):
            if self._scales[channel] <= 0:
                continue
            ca1, (h1, v1, d1) = pywt.dwt2(
                yuv[: row // _DWT_CROP * _DWT_CROP, : col // _DWT_CROP * _DWT_CROP, channel],
                "haar",
            )
            self.encode_frame(ca1, self._scales[channel])
            yuv[: row // _DWT_CROP * _DWT_CROP, : col // _DWT_CROP * _DWT_CROP, channel] = (
                pywt.idwt2((ca1, (h1, v1, d1)), "haar")  # original order, not (v1, h1, d1)
            )
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


class NoPayloadError(ValueError):
    """No recoverable payload at the requested or reachable length."""


class IntegrityUncertainError(ValueError):
    """An envelope-shaped decode failed its CRC32 check.

    Two causes are indistinguishable from the pixels alone: the payload really is
    different, or the chroma-clipping rounding documented in spike P3-B flipped bits.
    Reported as *uncertain* rather than *mismatch* for exactly that reason.
    """


# --------------------------------------------------------------- geometry ----
def total_blocks(height: int, width: int) -> int:
    """Blocks in the cA sub-band: crop to ``//4*4``, halve for the DWT, then tile 4x4."""
    ca_rows = (height // _DWT_CROP * _DWT_CROP) // 2
    ca_cols = (width // _DWT_CROP * _DWT_CROP) // 2
    return (ca_rows // _BLOCK) * (ca_cols // _BLOCK)


def max_stored_bytes(height: int, width: int) -> int:
    """Largest payload the decoder can recover from an image of this size.

    Each bit consumes one block, so the ceiling is ``blocks // 8``. The library does not
    raise past it — the excess bits read as ``nan`` and land on 0 — which is why P4 adds
    an explicit pre-flight check instead of trusting a silent truncation.
    """
    return total_blocks(height, width) // 8


def _block_scores(
    image_bgr: np.ndarray, *, channel: int | None = None, scale: int | None = None
) -> np.ndarray:
    """Per-block votes in scan order (row-major over the 4x4 blocks of ``ca1``).

    ``channel``/``scale`` must match the embed-time carrier: the vote is
    ``(s[0] % scale) > scale * 0.5``, so a mismatch scrambles the reading instead of
    degrading it. Defaults come from ``config`` (the current carrier).

    Deliberately vectorisation-free: this is a faithful transcription of the library's
    loop, and the measurement that proved equivalence (P3-B) ran on exactly this shape.
    """
    if channel is None:
        channel = config.CARRIER_CHANNEL
    if scale is None:
        scale = config.CARRIER_SCALE
    row, col = image_bgr.shape[:2]
    yuv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2YUV)
    ca1, _ = pywt.dwt2(
        yuv[: row // _DWT_CROP * _DWT_CROP, : col // _DWT_CROP * _DWT_CROP, channel], "haar"
    )
    fr, fc = ca1.shape
    scores = np.empty((fr // _BLOCK) * (fc // _BLOCK), dtype=np.int64)
    position = 0
    for i in range(fr // _BLOCK):
        for j in range(fc // _BLOCK):
            block = ca1[i * _BLOCK : i * _BLOCK + _BLOCK, j * _BLOCK : j * _BLOCK + _BLOCK]
            _, singular, _ = np.linalg.svd(cv2.dct(block))
            scores[position] = int((singular[0] % scale) > scale * 0.5)
            position += 1
    return scores


def _reconstruct_bytes(scores: np.ndarray, nbytes: int) -> bytes:
    """Bytes from block votes: majority per bit (``mean * 255 > 127``), MSB-first."""
    wm_len = nbytes * 8
    bits = np.zeros(wm_len, dtype=np.uint8)
    for b in range(wm_len):
        group = scores[b::wm_len]
        # An empty bucket is nan in the library, and `nan * 255 > 127` is False -> 0.
        bits[b] = 1 if (float(group.mean()) if group.size else 0.0) * 255 > 127 else 0
    return np.packbits(bits).tobytes()[:nbytes]


def _bit_agreements(scores: np.ndarray, nbytes: int) -> np.ndarray:
    """Per-bit fraction of blocks voting 1 (empty bucket -> 0, matching the library)."""
    wm_len = nbytes * 8
    out = np.zeros(wm_len, dtype=np.float64)
    for b in range(wm_len):
        group = scores[b::wm_len]
        out[b] = float(group.mean()) if group.size else 0.0
    return out


def boundary_margin(scores: np.ndarray, nbytes: int) -> float:
    """Mean distance of each bit from the library's decision boundary, on a 0..1 scale.

    This is a linear rescaling of the block-vote agreement rate (``agreement`` is roughly
    ``0.498 + margin``) with a ceiling near 0.5020, which is why the "2x safety" target of
    0.40 is unreachable for real products.
    """
    return float(np.mean(np.abs(_bit_agreements(scores, nbytes) - _DECISION)))


# ------------------------------------------------------------------ layer ① ---
def embed(image_bgr: np.ndarray, payload: str) -> np.ndarray:
    """Embed ``payload`` in the carrier named by ``config.CARRIER_*``."""
    if image_bgr.shape[0] * image_bgr.shape[1] < 256 * 256:
        raise RuntimeError("image too small, should be larger than 256x256")
    bits = list(np.unpackbits(np.frombuffer(payload.encode("utf-8"), dtype=np.uint8)))
    encoder = _CarrierEmbed(
        watermarks=bits,
        wmLen=len(bits),
        scales=_scales_for(config.CARRIER_CHANNEL, config.CARRIER_SCALE),
        block=_BLOCK,
    )
    return encoder.encode(image_bgr)


def extract(
    image_bgr: np.ndarray, payload_bytes: int, carrier: tuple[int, int] | None = None
) -> str:
    """Low-level raw decode, permissive by design. Prefer :func:`extract_legacy`."""
    if payload_bytes <= 0:
        raise ValueError("payload_bytes must be positive")
    channel, scale = carrier or (config.CARRIER_CHANNEL, config.CARRIER_SCALE)
    decoder = WatermarkDecoder("bytes", payload_bytes * 8)
    raw = decoder.decode(
        image_bgr, config.WATERMARK_METHOD, scales=_scales_for(channel, scale)
    )
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


def envelope_lengths(max_bytes: int) -> list[int]:
    """Stored lengths an envelope can occupy: ``PG1:<8 hex>:<base64>`` is ``13 + 4k``."""
    lengths = []
    length = 13 + 4
    while length <= max_bytes:
        lengths.append(length)
        length += 4
    return lengths


def find_envelope(
    image_bgr: np.ndarray, max_bytes: int | None = None
) -> tuple[str, int] | None:
    """Blind search: ``(payload, stored_length)`` or ``None``.

    Validity comes from the CRC32 header alone — never from byte equality with an expected
    payload. Spike P3-B showed the library's own round trip is already wrong for some
    lengths on noisy images, so a "known" payload is not an oracle; the checksum is.
    """
    if max_bytes is None:
        max_bytes = config.DEFAULT_MAX_PAYLOAD_BYTES
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    height, width = image_bgr.shape[:2]
    ceiling = min(max_bytes, max_stored_bytes(height, width))
    lengths = envelope_lengths(ceiling)
    if not lengths:
        return None
    # One extraction pass per carrier, then one cheap reconstruction per candidate length:
    # the score array depends on the carrier but not on the length.
    for channel, scale in carrier_candidates():
        scores = _block_scores(image_bgr, channel=channel, scale=scale)
        for length in lengths:
            raw = _reconstruct_bytes(scores, length)
            if not raw.startswith(_MAGIC.encode("ascii") + b":"):
                continue
            try:
                payload, verified = unpack_payload(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                continue
            if verified:
                return payload, length
    return None


def extract_envelope(image_bgr: np.ndarray, payload_bytes: int) -> str:
    """Decode an envelope at a known stored length. CRC is the only authority."""
    if payload_bytes <= 0:
        raise ValueError("payload_bytes must be positive")
    saw_envelope = False
    for channel, scale in carrier_candidates():
        raw = _reconstruct_bytes(
            _block_scores(image_bgr, channel=channel, scale=scale), payload_bytes
        )
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not text.startswith(f"{_MAGIC}:"):
            continue
        saw_envelope = True
        try:
            payload, verified = unpack_payload(text)
        except ValueError:
            continue
        if verified:
            return payload
    if saw_envelope:
        raise IntegrityUncertainError(
            "envelope decoded but its CRC32 failed — the payload may differ, or the "
            "carrier may have lost bits (see P10/P11)"
        )
    raise NoPayloadError("no photo-guard envelope at that length")


# --------------------------------------------------------------- legacy raw ---
def _is_periodic(raw: bytes) -> bool:
    """True when ``raw`` is a whole number of repeats of a shorter block.

    Kills the multiple-length false-accept family (``layers-testlayers-test``): reading a
    payload at a multiple of its true length yields a perfectly printable repetition that
    the advisory margin gate cannot reject.
    """
    size = len(raw)
    if size < 2:
        return False
    for period in range(1, size // 2 + 1):
        if size % period == 0 and raw == raw[:period] * (size // period):
            return True
    return False


def is_recoverable_text(raw: bytes) -> bool:
    """Strict UTF-8 plus zero-tolerance printability, plus the anti-repetition rule.

    Zero tolerance replaces the old ">= 50% bad characters" heuristic, which let a
    partially corrupted payload decode to garbage and still exit 0.
    """
    if not raw:
        return False
    try:
        text = raw.decode("utf-8")  # strict: no U+FFFD substitution
    except UnicodeDecodeError:
        return False
    if _is_periodic(raw):
        return False
    for char in text:
        if char in "\t\n\r":
            continue
        if char == "\ufffd" or unicodedata.category(char).startswith("C"):
            return False
        if not char.isprintable():
            return False
    return True


@dataclass(frozen=True)
class LegacyExtraction:
    """A checksum-less decode. ``advisory_pass`` is a garbage filter, not evidence."""

    text: str
    blocks_per_bit: int
    mean_margin: float
    advisory_pass: bool
    notes: str
    carrier: tuple[int, int]


def extract_legacy(image_bgr: np.ndarray, payload_bytes: int) -> LegacyExtraction:
    """Decode a raw (checksum-less) payload as a *clue*, with its advisory metrics."""
    if payload_bytes <= 0:
        raise ValueError("payload_bytes must be positive")
    # Without a checksum the carrier cannot be confirmed, so each candidate is tried and the
    # first that yields recoverable text wins; the result records which one it was.
    found: tuple[int, int] | None = None
    for channel, scale in carrier_candidates():
        scores = _block_scores(image_bgr, channel=channel, scale=scale)
        raw = _reconstruct_bytes(scores, payload_bytes)
        if is_recoverable_text(raw):
            found = (channel, scale)
            break
    if found is None:
        raise NoPayloadError(
            "decoded bytes are not recoverable text "
            "(strict UTF-8, printable, non-repetitive)"
        )
    channel, scale = found
    bits = payload_bytes * 8
    blocks_per_bit = len(scores) // bits
    margin = boundary_margin(scores, payload_bytes)
    advisory = (
        margin >= config.LEGACY_MIN_MEAN_MARGIN
        and blocks_per_bit >= config.LEGACY_MIN_BLOCKS_PER_BIT
    )
    if advisory:
        notes = "advisory gates passed"
    elif blocks_per_bit < config.LEGACY_MIN_BLOCKS_PER_BIT:
        notes = (
            f"advisory gate unmet: {blocks_per_bit} blocks/bit "
            f"< {config.LEGACY_MIN_BLOCKS_PER_BIT}"
        )
    else:
        notes = (
            f"advisory gate unmet: mean_margin {margin:.4f} "
            f"< {config.LEGACY_MIN_MEAN_MARGIN}"
        )
    return LegacyExtraction(
        text=raw.decode("utf-8"),
        blocks_per_bit=blocks_per_bit,
        mean_margin=margin,
        advisory_pass=advisory,
        notes=notes + "; raw payloads carry no checksum, so this is a clue, not proof",
        carrier=(channel, scale),
    )
