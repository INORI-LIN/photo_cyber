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

The block layout below is a transcription of the DWT-DCT-SVD method with its upstream
defaults (``scales=[0, 36, 0]``, ``block=4`` and the ``//4*4`` crop). It was proven
byte-for-byte equal to the library's ``WatermarkDecoder("bytes", n * 8).decode(...,
"dwtDctSvd")`` on 264/264 cases (4 images x n = 1..66; spike P3-B), and since G1 the
arithmetic itself lives in-repo (:mod:`photo_guard._dwt_dct_svd`, a verbatim transcription of
``imwatermark/dwtDctSvd.py`` 0.2.0, oracle sha256 ``221c856e…``) so the core install no longer
carries torch. Re-check it if those defaults ever change.
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

from . import _dwt_dct_svd, config

_MAGIC = "PG1"

# The library's embed/decode loops run over ``range(2)``, so only channels 0..1 can carry
# bits at all (P21).
_MAX_EMBEDDABLE_CHANNEL = 1
_BLOCK = 4
_DWT_CROP = 4
_DECISION = 127.0 / 255.0  # the library tests `avg * 255 > 127`


def _require_embeddable_channel(channel: int) -> None:
    """Reject a carrier channel the library cannot carry bits in (P21).

    ``EmbedDwtDctSvd.encode``/``decode`` loop over ``range(2)``, so a channel ≥ 2 leaves the
    scales vector all-zero: embedding silently becomes a no-op and every reader fails
    forever, with nothing raising. A plain ``ValueError`` (never ``NoPayloadError``) keeps
    the CLI mapping it to exit 2.
    """
    if not 0 <= channel <= _MAX_EMBEDDABLE_CHANNEL:
        raise ValueError(
            f"carrier channel {channel} is out of range: the watermark library only carries "
            f"bits in channels 0..{_MAX_EMBEDDABLE_CHANNEL} (check config.CARRIER_CHANNEL)"
        )


def _scales_for(channel: int, scale: int) -> list[int]:
    """The library's ``scales`` vector for a single carrier channel."""
    _require_embeddable_channel(channel)
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
        _require_embeddable_channel(candidate[0])
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


class _CarrierEmbed(_dwt_dct_svd.EmbedDwtDctSvd):
    """Embedder that fixes the upstream H/V detail-band swap (P11).

    The upstream 0.2.0 code (now transcribed byte-for-byte in :mod:`photo_guard._dwt_dct_svd`)
    unpacks ``dwt2`` as ``(h1, v1, d1)`` but hands ``idwt2`` ``(v1, h1, d1)``
    (``dwtDctSvd.py:27`` vs ``:30``), swapping the horizontal and vertical detail bands on the
    way back. Extraction only reads ``cA`` — the sum of the bands that feed the next ``LL`` is
    unchanged — so the swap is invisible to decoding, but it injects an unintended image
    distortion: negligible while the carrier was chroma (mean 0.50 / max 19 of 255) and clearly
    visible once the carrier moved to luma (mean 10.3–12.8 / max 106). The transcription must
    stay verbatim (G1), hence a subclass. ``cA`` itself is bit-identical to the upstream
    encoder's, so images stay mutually readable.
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


def _require_bgr(image_bgr: np.ndarray) -> None:
    """P31: every layer-① entry point takes a 3-channel BGR array.

    Two failure modes motivated this: a 2-D array dies inside ``cv2.cvtColor``/``cv2.dct``
    with ``cv2.error`` (which the CLI's exit-2 mapping does not catch, since it handles only
    ``ValueError``/``OSError``/``RuntimeError``) and a 4-channel array is quietly accepted
    with its extra channel ignored. Both are refused here instead, as ``ValueError``.

    Called *after* each function's pre-existing gates on purpose: the error precedence the
    existing tests pin (area → method, capacity → floor → method) stays exactly as measured.
    """
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError(
            f"image must be a 3-channel BGR array, got shape {tuple(image_bgr.shape)}"
        )


def _require_capacity(image_bgr: np.ndarray, payload_bytes: int) -> None:
    """Reject a stored length the image can never carry, before any block loop (P14).

    ``payload_bytes`` is only a loop bound to the decoder, so an impossible length used to
    spin for ``payload_bytes * 8`` iterations and then report "no payload" — a parameter
    error misfiled as an extraction outcome. A plain ``ValueError`` (never
    ``NoPayloadError``) keeps the CLI mapping it to exit 2.
    """
    if payload_bytes <= 0:
        raise ValueError("payload_bytes must be positive")
    height, width = image_bgr.shape[:2]
    capacity = max_stored_bytes(height, width)
    if payload_bytes > capacity:
        raise ValueError(
            f"payload_bytes {payload_bytes} exceeds this image's capacity of {capacity} bytes"
        )


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
def _require_method() -> None:
    """Only ``dwtDctSvd`` is implemented in-repo; anything else must fail loudly (G1).

    The constant used to select a method from the third-party library. Since the arithmetic is
    transcribed, there is no second implementation to select, and silently accepting another
    name would mean "the watermark you asked for did not happen" — the exact failure mode the
    ``dwtDct``/``dwtDctSvd`` note in ``config`` warns about.
    """
    if config.WATERMARK_METHOD != "dwtDctSvd":
        raise ValueError(
            f"unsupported watermark method {config.WATERMARK_METHOD!r}: this build only "
            "implements 'dwtDctSvd' (see config.WATERMARK_METHOD)"
        )


def embed(image_bgr: np.ndarray, payload: str) -> np.ndarray:
    """Embed ``payload`` in the carrier named by ``config.CARRIER_*``."""
    if image_bgr.shape[0] * image_bgr.shape[1] < 256 * 256:
        raise RuntimeError("image too small, should be larger than 256x256")
    _require_method()
    if not payload:
        # P31: wmLen == 0 used to surface as a ZeroDivisionError from inside the
        # transcribed loop, and the empty envelope is undiscoverable by construction.
        raise ValueError("payload must not be empty")
    _require_bgr(image_bgr)
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
    """Low-level raw decode, permissive by design. Prefer :func:`extract_legacy`.

    Permissive about its *output* (undecodable bytes become ``errors="replace"``), strict
    about the *request*: a length beyond the image's capacity is a parameter error (P14).
    """
    # Order is contract: capacity first (a parameter error), then the 256x256 floor the
    # removed decoder raised, then the method gate. Reordering would change which error a
    # 255x255 + over-capacity request gets.
    _require_capacity(image_bgr, payload_bytes)
    if image_bgr.shape[0] * image_bgr.shape[1] < 256 * 256:
        raise RuntimeError("image too small, should be larger than 256x256")
    _require_method()
    _require_bgr(image_bgr)
    channel, scale = carrier or (config.CARRIER_CHANNEL, config.CARRIER_SCALE)
    bits = _dwt_dct_svd.decode_bits(
        image_bgr, payload_bytes * 8, scales=_scales_for(channel, scale), block=_BLOCK
    )
    raw = np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()[:payload_bytes]
    return raw.decode("utf-8", errors="replace")


def pack_payload(payload: str) -> str:
    if not payload:
        # P31: ``PG1:00000000:`` is 13 characters, and the recoverable ladder starts at 17
        # (one byte of base64), so an empty payload would embed fine and then be
        # undiscoverable. Refuse it instead of producing a dead envelope.
        raise ValueError("payload must not be empty")
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
    _require_bgr(image_bgr)
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
    """Decode an envelope at a known stored length. CRC is the only authority.

    P27 closed the last gap in P14's rule: an impossible length is a parameter error on
    every read path, so this one runs the same capacity gate as ``extract``/
    ``extract_legacy`` instead of scanning every block and then claiming "no envelope".
    """
    _require_capacity(image_bgr, payload_bytes)
    _require_bgr(image_bgr)
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
    _require_capacity(image_bgr, payload_bytes)
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
