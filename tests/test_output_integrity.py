"""P0 / G3 — output writes must be complete, and never land on the input.

Three defects are pinned here (``docs/fix-plan.md`` §6 G3):

* a save that failed part-way left a truncated JPEG under the final, normal-looking name;
* ``protect in.jpg -o in.jpg`` replaced the only original and still exited 0;
* a batch whose sources shared a stem (routine for phone exports) resolved to one output
  path, so the second write silently replaced the first while both reported success.

Two of these tests are required to fail against the pre-fix code: see the batch evidence
in ``docs/fix-plan.md`` (``git worktree`` at the parent commit).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from photo_guard import outputs, pipeline
from photo_guard.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


def _textured(path: Path, size: tuple[int, int] = (640, 480)) -> Path:
    """A small textured JPEG: cheap, and the invisible layer needs ≥256×256."""
    import numpy as np

    rng = np.random.default_rng(11)
    arr = rng.integers(60, 200, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, quality=92)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fail_save(*_args, **_kwargs):
    raise OSError(28, "No space left on device")


# --- atomic write -------------------------------------------------------------------
def test_atomic_write_keeps_previous_output_when_save_fails(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "out.jpg"
    destination.write_bytes(b"previous-good-bytes")
    monkeypatch.setattr(Image.Image, "save", _fail_save)

    with pytest.raises(OSError, match="failed to write"):
        outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)

    assert destination.read_bytes() == b"previous-good-bytes"


def test_atomic_write_creates_no_file_when_destination_absent(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "out.jpg"
    monkeypatch.setattr(Image.Image, "save", _fail_save)

    with pytest.raises(OSError, match="failed to write"):
        outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(f"{outputs._TEMP_PREFIX}*"))


def test_atomic_write_temp_creation_failure_names_the_target(tmp_path, monkeypatch) -> None:
    """A failure before the temp path exists must still report the destination."""
    destination = tmp_path / "out.jpg"

    def boom(_directory):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(outputs, "_create_temp_file", boom)

    with pytest.raises(OSError) as excinfo:
        outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)

    assert str(destination) in str(excinfo.value)


def test_atomic_write_output_is_decodable_at_the_final_path(tmp_path) -> None:
    destination = tmp_path / "nested" / "out.jpg"
    outputs.save_image_atomic(Image.new("RGB", (32, 24)), destination, quality=80)

    with Image.open(destination) as image:
        image.load()
        assert image.size == (32, 24)
        assert image.format == "JPEG"
    assert not list(destination.parent.glob(f"{outputs._TEMP_PREFIX}*"))


def test_atomic_write_preserves_existing_file_permissions(tmp_path) -> None:
    """A pre-existing mode must survive the atomic write.

    Windows has no rwx bits: `st_mode & 0o777` can only be 0o666 (writable) or 0o444
    (read-only), so `0o604` is not a representable state there. The branch below asserts the
    one permission state Windows *can* observe — which is exactly the property
    `outputs.save_image_atomic` implements when it re-applies the previous mode.
    """
    destination = tmp_path / "out.jpg"
    destination.write_bytes(b"x")
    if sys.platform == "win32":
        os.chmod(destination, 0o444)
        outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)
        assert destination.stat().st_mode & 0o200 == 0  # still read-only
        with Image.open(destination) as image:  # and the content is the new image
            image.load()
            assert image.format == "JPEG"
    else:
        os.chmod(destination, 0o604)
        outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)
        assert destination.stat().st_mode & 0o777 == 0o604


def test_atomic_write_new_file_follows_umask(tmp_path) -> None:
    destination = tmp_path / "out.jpg"
    current = os.umask(0)
    os.umask(current)

    outputs.save_image_atomic(Image.new("RGB", (8, 8)), destination)

    assert destination.stat().st_mode & 0o777 == 0o666 & ~current


def test_atomic_write_fsyncs_a_write_capable_handle(tmp_path, monkeypatch) -> None:
    """The flush must go through a handle opened for writing.

    On Windows `os.fsync` reaches FlushFileBuffers, whose contract requires the handle to
    carry GENERIC_WRITE, so `os.open(temp, os.O_RDONLY)` made **every** save fail with
    `OSError: failed to write … [Errno 9] Bad file descriptor` (windows-latest: 25 failed /
    114 passed). POSIX flushes a read-only handle happily, so no run on macOS or Linux can
    tell the two implementations apart — pinning the flag is the only cross-platform lock
    that reds if someone reverts it.
    """
    real_open = os.open
    real_fsync = os.fsync
    flags_by_fd: dict[int, int] = {}
    flushed: list[int] = []

    def spy_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        flags_by_fd[fd] = flags
        return fd

    def spy_fsync(fd):
        flushed.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)

    outputs.save_image_atomic(Image.new("RGB", (8, 8)), tmp_path / "out.jpg")

    assert flushed, "the atomic write must flush its temp file"
    flags = flags_by_fd[flushed[0]]
    assert flags & (os.O_WRONLY | os.O_RDWR), f"fsync'd handle is not writable: flags={flags!r}"


# --- never write the input ----------------------------------------------------------
def test_protect_refuses_output_equal_to_input(tmp_path, capsys) -> None:
    source = _textured(tmp_path / "in.jpg")
    before = _digest(source)

    assert main(["protect", str(source), "-o", str(source)]) == 2

    captured = capsys.readouterr()
    assert "refusing to overwrite the input" in captured.err
    assert _digest(source) == before


def test_protect_refuses_an_aliased_input(tmp_path, capsys) -> None:
    """A hard link is the same file under another name."""
    source = _textured(tmp_path / "in.jpg")
    alias = tmp_path / "alias.jpg"
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")
    before = _digest(source)

    assert main(["protect", str(source), "-o", str(alias)]) == 2

    assert "refusing to overwrite the input" in capsys.readouterr().err
    assert _digest(source) == before


def test_protect_replaces_a_symlink_without_touching_its_target(tmp_path) -> None:
    """``os.replace`` swaps the link itself, which is what a user pointing -o at a link
    expects; the link's target must be left alone."""
    source = _textured(tmp_path / "in.jpg")
    target = tmp_path / "target.jpg"
    target.write_bytes(b"untouched")
    link = tmp_path / "out.jpg"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    assert main(["protect", str(source), "-o", str(link)]) == 0

    assert not link.is_symlink()
    with Image.open(link) as image:
        image.load()
    assert target.read_bytes() == b"untouched"


# --- batch naming -------------------------------------------------------------------
@pytest.mark.parametrize(
    "sources,expected",
    [
        (["a/IMG_0001.JPG", "b/IMG_0001.JPG"], ["IMG_0001_protected.jpg", "IMG_0001_protected_2.jpg"]),
        (["IMG_0001.JPG", "IMG_0001.png"], ["IMG_0001_protected.jpg", "IMG_0001_protected_2.jpg"]),
        (["IMG_0001.png"], ["IMG_0001_protected.jpg"]),
        (["a/IMG_0001.JPG", "b/IMG_0001.JPG", "c/IMG_0001.jpg"],
         ["IMG_0001_protected.jpg", "IMG_0001_protected_2.jpg", "IMG_0001_protected_3.jpg"]),
    ],
)
def test_plan_batch_gives_same_stem_inputs_distinct_paths(tmp_path, sources, expected) -> None:
    planned = outputs.plan_batch(tmp_path / "out", [tmp_path / s for s in sources], "_protected")
    assert [p.name for p in planned] == expected
    assert len(set(planned)) == len(sources)


def test_plan_batch_composes_with_existing_files(tmp_path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "IMG_0001_protected.jpg").write_bytes(b"x")

    planned = outputs.plan_batch(
        out_dir, [tmp_path / "a" / "IMG_0001.JPG", tmp_path / "b" / "IMG_0001.JPG"], "_protected"
    )

    assert [p.name for p in planned] == ["IMG_0001_protected_2.jpg", "IMG_0001_protected_3.jpg"]


def test_plan_batch_normalizes_suffix_through_sanitize(tmp_path) -> None:
    planned = outputs.plan_batch(tmp_path, [tmp_path / "IMG_0001.JPG"], "   ")
    assert planned[0].name == f"IMG_0001{outputs.DEFAULT_SUFFIX}.jpg"


@pytest.mark.parametrize(
    "raw",
    ["../x", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b", "..", "...", "a\x00b", "a\nb"],
)
def test_sanitize_suffix_rejects_illegal_and_traversal_values(raw: str) -> None:
    with pytest.raises(ValueError):
        outputs.sanitize_suffix(raw)


@pytest.mark.parametrize("raw,expected", [("_protected", "_protected"), ("©水印", "©水印"), ("v2-final", "v2-final"), ("  _x_  ", "_x_")])
def test_sanitize_suffix_accepts_normal_values(raw: str, expected: str) -> None:
    assert outputs.sanitize_suffix(raw) == expected
    assert outputs.sanitize_suffix("   ") == outputs.DEFAULT_SUFFIX


# --- module hygiene -----------------------------------------------------------------
def test_outputs_module_import_does_not_pull_qt_or_torch() -> None:
    """Loaded by path so the package ``__init__`` — which does pull torch through the
    watermark chain — cannot mask a stray import in this module."""
    probe = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('outputs_probe', r'%s')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "print('torch' in sys.modules, 'PySide6' in sys.modules)\n"
    ) % (REPO_ROOT / "src" / "photo_guard" / "outputs.py")
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False False"


def test_gui_delegates_output_naming_to_outputs_module() -> None:
    source = (REPO_ROOT / "src" / "photo_guard" / "gui.py").read_text(encoding="utf-8")
    assert "_unique_output" not in source
    assert "outputs.plan_batch" in source


def test_pipeline_saves_through_the_atomic_helper() -> None:
    source = (REPO_ROOT / "src" / "photo_guard" / "pipeline.py").read_text(encoding="utf-8")
    assert "outputs.save_image_atomic" in source
    assert 'format="JPEG"' not in source
