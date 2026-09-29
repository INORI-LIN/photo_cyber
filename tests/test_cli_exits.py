"""CLI exit-code coverage.

Covers the branches in cli.py:
- protect → 0 on success
- verify  → 0 when the payload is recovered as evidence (envelope match, or blind discovery)
- verify  → 3 when only a checksum-less *clue* is recovered (P19: it used to be 0, which
  made an unverified guess indistinguishable from a verified hit on the machine-readable
  channel; the human-readable stdout/stderr wording is unchanged)
- verify  → 1 when nothing is recoverable ("no payload recovered")
- verify  → 2 when extraction itself raises (e.g. missing file, bad argument)

The blind-discovery and clue branches were added by P3; the legacy branch now labels its
output as a clue, which is why the payload only has to appear in stdout there.
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


def test_protect_then_raw_verify_reports_a_clue(tmp_path: Path, capsys) -> None:
    """protect succeeds (0); verifying the raw payload is a clue, not evidence (3, P19)."""
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    payload = "test#cli"
    code = main(["protect", str(src), "-o", str(out), "--payload", payload, "--visible-mode", "tile"])
    assert code == 0

    captured = capsys.readouterr()
    assert "protected" in captured.out

    # P19: the raw (checksum-less) path reports a clue and exits 3.
    code = main(["verify", str(out), "--payload-bytes", str(len(payload.encode()))])
    assert code == 3
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


# --- P3: blind discovery and the clue-labelled legacy path --------------------------
#
# Every payload length used here is one that this fixture was measured to survive
# end-to-end (see docs/fix-plan.md P10 — the envelope round trip is NOT reliable for
# every length on this noise fixture, so a test must not pick a length at random).


def test_verify_without_flags_discovers_the_envelope(tmp_path: Path, capsys) -> None:
    """No length, no expected payload — the CRC envelope is enough."""
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    payload = "test#cli"  # 8 bytes: measured to survive protect -> verify on this fixture
    assert main(
        ["protect", str(src), "-o", str(out), "--payload", payload, "--payload-envelope"]
    ) == 0
    capsys.readouterr()

    code = main(["verify", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == payload


def test_verify_without_flags_on_an_unmarked_image_exits_one(tmp_path: Path, capsys) -> None:
    src = tmp_path / "clean.jpg"
    Image.new("RGB", (800, 600), (200, 220, 240)).save(src, quality=92)

    assert main(["verify", str(src)]) == 1
    assert "no payload recovered" in capsys.readouterr().err


def test_legacy_verify_labels_its_output_as_a_clue(tmp_path: Path, capsys) -> None:
    """A checksum-less payload is a clue: stdout says so, stderr carries the metrics,
    and the exit code says so too (3 since P19)."""
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    payload = "test#cli"
    assert main(["protect", str(src), "-o", str(out), "--payload", payload]) == 0
    capsys.readouterr()

    code = main(["verify", str(out), "--payload-bytes", str(len(payload.encode()))])
    assert code == 3
    captured = capsys.readouterr()
    assert "线索" in captured.out and "未验证" in captured.out
    assert payload in captured.out
    assert "clue, not proof" in captured.err


def test_legacy_clue_path_exits_three_not_zero(tmp_path: Path, capsys) -> None:
    """The same file: blind discovery (evidence) exits 0, the raw clue path exits 3.

    P19's whole point is that a caller can tell the two apart without parsing stdout. The
    clue is read at the stored envelope's length, so the bytes it recovers really are the
    envelope text — a recoverable-looking clue that is still not evidence.
    """
    from photo_guard import watermark_invisible as wi

    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    payload = "test#cli"
    code = main(
        ["protect", str(src), "-o", str(out), "--payload", payload, "--payload-envelope"]
    )
    assert code == 0
    capsys.readouterr()

    assert main(["verify", str(out)]) == 0
    capsys.readouterr()

    stored = len(wi.pack_payload(payload).encode())
    clue_code = main(["verify", str(out), "--payload-bytes", str(stored)])
    assert clue_code == 3
    assert clue_code not in (0, 1, 2), "the clue path must be machine-readably distinct"
    assert "线索（未验证）" in capsys.readouterr().out


def test_verify_with_a_zero_payload_bytes_exits_two(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.jpg"
    _seed_textured(src)
    assert main(["verify", str(src), "--payload-bytes", "0"]) == 2
    assert "positive" in capsys.readouterr().err


def test_verify_with_an_impossible_payload_bytes_exits_two(tmp_path: Path, capsys) -> None:
    """P14: 1200x1600 holds 3750 stored bytes, so 100000 is a parameter error (exit 2).

    The old code treated it as "no payload recovered" (exit 1) after a multi-second spin.
    """
    src = tmp_path / "in.jpg"
    _seed_textured(src)
    assert main(["verify", str(src), "--payload-bytes", "100000"]) == 2
    err = capsys.readouterr().err
    assert "capacity" in err and "100000" in err


def test_protect_with_an_out_of_range_carrier_exits_two(tmp_path: Path, monkeypatch, capsys) -> None:
    """P21: a channel the library cannot carry bits in must fail loudly, not no-op.

    Pre-fix this exited 0 and wrote an *unmarked* image while claiming success.
    """
    from photo_guard import config

    monkeypatch.setattr(config, "CARRIER_CHANNEL", 2)
    src = tmp_path / "in.jpg"
    out = tmp_path / "out.jpg"
    _seed_textured(src)

    assert main(["protect", str(src), "-o", str(out), "--visible-mode", "tile"]) == 2
    assert "carrier" in capsys.readouterr().err
    assert not out.exists()

