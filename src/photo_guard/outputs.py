"""Output ownership: where a processed image goes, and how it gets there.

Two P0 failure modes lived here before (see ``docs/fix-plan.md`` §6 G3):

* the destination path was used as the working path, so an interrupted save left a
  truncated JPEG under a normal-looking name, and
* batch naming only asked ``candidate.exists()`` once, up front, so two same-stem inputs
  (``DCIM/100APPLE/IMG_0001.JPG`` next to ``DCIM/101APPLE/IMG_0001.JPG`` — routine for
  phone exports) resolved to one path and the second write silently replaced the first
  while both reported success.

Imports are stdlib + Pillow only, so this module stays usable from the CLI, the GUI and
tests without pulling Qt or torch.
"""
from __future__ import annotations

import os
import secrets
import unicodedata
from pathlib import Path
from typing import Iterable

from PIL import Image

DEFAULT_SUFFIX = "_protected"
_TEMP_PREFIX = ".photoguard-"
_TEMP_SUFFIX = ".tmp"
_TEMP_ATTEMPTS = 16
_ILLEGAL_SUFFIX_CHARS = frozenset('/\\:*?"<>|')


def _create_temp_file(directory: Path) -> Path:
    """Reserve a uniquely-named temp file in ``directory`` (same filesystem, so the
    later ``os.replace`` is atomic rather than a cross-device copy)."""
    for _ in range(_TEMP_ATTEMPTS):
        candidate = directory / f"{_TEMP_PREFIX}{secrets.token_hex(8)}{_TEMP_SUFFIX}"
        try:
            handle = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            continue
        os.close(handle)
        return candidate
    raise OSError(f"could not create a temporary file in {directory}")


def save_image_atomic(
    image: Image.Image,
    path: Path | str,
    *,
    image_format: str = "JPEG",
    quality: int | None = None,
    icc_profile: bytes | None = None,
) -> None:
    """Write ``image`` to ``path`` without ever exposing a partial file.

    The bytes land in a temp file in the destination directory, are flushed, and only
    then replace the destination. A crash, a full disk or Ctrl-C therefore leaves either
    the previous file or no file — never a truncated image under the final name.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = destination.stat().st_mode & 0o7777 if destination.exists() else None
    unprotected = False  # True while the swap has lifted the destination's write protection
    temp: Path | None = None
    try:
        temp = _create_temp_file(destination.parent)
        save_kwargs: dict[str, object] = {"format": image_format, "optimize": True}
        if quality is not None:
            save_kwargs["quality"] = quality
        if icc_profile is not None:
            save_kwargs["icc_profile"] = icc_profile
        image.save(temp, **save_kwargs)
        # Read-write, not read-only: on Windows `os.fsync` reaches FlushFileBuffers, whose
        # contract requires the handle to carry GENERIC_WRITE — a read-only handle raises
        # OSError(EBADF) and would fail every save. On POSIX the two are equivalent for
        # flushing, so this costs nothing and removes the platform split entirely.
        handle = os.open(temp, os.O_RDWR)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
        # Windows refuses to replace a read-only destination (measured on windows-latest:
        # WinError 5 "Access is denied" out of `os.replace`), and a read-only output is
        # precisely the mode this function promises to carry over — so lift the protection for
        # the swap and re-apply it below. Best-effort: POSIX replaces regardless of the file's
        # mode, and a destination we have no right to chmod (foreign owner) must still be
        # allowed to proceed, leaving `os.replace` as the final authority on permissions.
        if previous_mode is not None and not previous_mode & 0o200:
            try:
                os.chmod(destination, previous_mode | 0o200)
                unprotected = True
            except OSError:
                pass
        os.replace(temp, destination)
        temp = None  # ownership handed to the destination; nothing left to clean up
        # Re-applying the mode only *after* the replace keeps the swap free of a read-only
        # destination. Cost: the mode lags the content by the chmod in between; the content
        # swap itself stays atomic.
        if previous_mode is not None:
            os.chmod(destination, previous_mode)
    except OSError as exc:
        raise OSError(f"failed to write {destination}: {exc}") from exc
    finally:
        if unprotected and previous_mode is not None and temp is not None:
            try:  # a failed save must not leave a read-only output writable
                os.chmod(destination, previous_mode)
            except OSError:
                pass
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass


def sanitize_suffix(raw: str) -> str:
    """Return a filename-safe suffix, or raise ``ValueError``.

    Rejecting rather than stripping is deliberate: silently rewriting ``../x`` would put
    the file somewhere the user did not choose. Non-ASCII is kept.
    """
    suffix = (raw or "").strip()
    if not suffix:
        return DEFAULT_SUFFIX
    if not suffix.strip("."):
        raise ValueError("suffix must not be only dots")
    for char in suffix:
        if char in _ILLEGAL_SUFFIX_CHARS or unicodedata.category(char).startswith("C"):
            raise ValueError(f"suffix contains an illegal character: {char!r}")
    return suffix


def _unique_output(
    directory: Path, stem: str, extension: str, taken: frozenset[str] | set[str] = frozenset()
) -> Path:
    candidate = directory / f"{stem}{extension}"
    number = 2
    while candidate.name in taken or candidate.exists():
        candidate = directory / f"{stem}_{number}{extension}"
        number += 1
    return candidate


def plan_batch(
    directory: Path | str,
    sources: Iterable[Path | str],
    suffix: str,
    extension: str = ".jpg",
) -> list[Path]:
    """Resolve one distinct output path per source, in the same order as ``sources``.

    ``taken`` is what makes this correct for a batch: two same-stem sources that do not
    exist on disk yet still cannot collide, because the first reservation is remembered.
    """
    suffix = sanitize_suffix(suffix)
    directory = Path(directory)
    taken: set[str] = set()
    planned: list[Path] = []
    for source in sources:
        candidate = _unique_output(directory, Path(source).stem + suffix, extension, taken)
        taken.add(candidate.name)
        planned.append(candidate)
    return planned
