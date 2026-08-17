"""CLI exit-code coverage.

Covers the three branches in cli.py:
- protect → 0 on success
- verify  → 0 when payload recovered
- verify  → 1 when output is empty / all-NUL ("no payload recovered")
- verify  → 2 when extraction itself raises (e.g. missing file)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from photo_guard.cli import main


def _seed_textured(path: Path) -> None:
    rng = np.random.default_rng(7)
    arr = rng.integers(60, 200, (1200, 1600, 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, quality=92)


def test_protect_then_verify_exits_zero(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    payload = "test#cli"
    code = main(["protect", str(src), "-o", str(out), "--payload", payload, "--visible-mode", "tile"])
    assert code == 0

    captured = capsys.readouterr()
    assert "protected" in captured.out

    code = main(["verify", str(out), "--payload-bytes", str(len(payload.encode()))])
    assert code == 0
    captured = capsys.readouterr()
    assert payload in captured.out


def test_verify_no_payload_exits_one(tmp_path: Path, capsys) -> None:
    """A clean image (no embed) → all-NUL payload → exit 1."""
    src = tmp_path / "clean.jpg"
    Image.new("RGB", (800, 600), (200, 220, 240)).save(src, quality=92)

    code = main(["verify", str(src), "--payload-bytes", "10"])
    assert code == 1
    err = capsys.readouterr().err
    assert "no payload recovered" in err


def test_verify_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    code = main(["verify", str(tmp_path / "does-not-exist.jpg"), "--payload-bytes", "10"])
    assert code == 2
    err = capsys.readouterr().err
    assert "verify failed" in err


def test_protect_with_layers_subset_succeeds(tmp_path: Path, capsys) -> None:
    """--layers picks a subset; output names what ran."""
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    code = main(
        [
            "protect",
            str(src),
            "-o",
            str(out),
            "--layers",
            "invisible,visible",
            "--payload",
            "subset",
            "--visible-mode",
            "tile",
        ]
    )
    assert code == 0
    line = capsys.readouterr().out
    assert "layers=invisible+visible" in line
    assert "perturber=None" in line


def test_non_noop_perturber_enables_perturb_layer(tmp_path: Path, capsys) -> None:
    """Selecting a real perturber is an explicit request to run that layer."""
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    code = main(
        [
            "protect",
            str(src),
            "-o",
            str(out),
            "--perturber",
            "noise",
            "--visible-mode",
            "tile",
        ]
    )

    assert code == 0
    line = capsys.readouterr().out
    assert "layers=invisible+perturb+visible" in line
    assert "perturber=noise" in line


def test_non_noop_perturber_augments_explicit_layer_subset(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    code = main(
        [
            "protect",
            str(src),
            "-o",
            str(out),
            "--layers",
            "visible",
            "--perturber",
            "noise",
            "--visible-mode",
            "tile",
        ]
    )

    assert code == 0
    line = capsys.readouterr().out
    assert "layers=perturb+visible" in line
    assert "perturber=noise" in line


def test_explicit_perturb_layer_rejects_noop(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    code = main(
        [
            "protect",
            str(src),
            "-o",
            str(out),
            "--layers",
            "perturb",
        ]
    )

    assert code == 2
    assert "perturb layer uses noop" in capsys.readouterr().err


def test_protect_with_unknown_layer_exits_two(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    code = main(
        [
            "protect",
            str(src),
            "-o",
            str(out),
            "--layers",
            "invisible,bogus",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown name" in err

