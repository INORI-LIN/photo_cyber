"""P2 / G6 — the desktop window's own wiring: checkboxes → options, batch naming, --help.

Kept off the fast tier (needs PySide6). QSettings is redirected to a temporary INI before
``MainWindow`` exists, so a developer's real preferences can neither decide these tests nor
be modified by them.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from photo_guard import config, gui, outputs, pipeline

pytestmark = pytest.mark.gui

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    win = gui.MainWindow()
    win.payload.setText(config.DEFAULT_PAYLOAD)
    win.visible_text.setText(config.DEFAULT_VISIBLE_TEXT)
    win.suffix.setText(outputs.DEFAULT_SUFFIX)
    win.output_dir.setText(str(tmp_path))
    win.long_edge.setValue(320)
    try:
        yield win
    finally:
        win.close()


def test_default_checkboxes_are_invisible_and_visible(window) -> None:
    assert (
        window.layer_invisible.isChecked(),
        window.layer_sd.isChecked(),
        window.layer_visible.isChecked(),
    ) == (True, False, True)
    assert window._build_options().layers == pipeline.DEFAULT_LAYERS


@pytest.mark.parametrize(
    ("invisible", "sd", "visible", "expected"),
    [
        (True, False, True, {"invisible", "visible"}),
        (True, True, True, {"invisible", "perturb", "visible"}),
        (False, True, True, {"perturb", "visible"}),
        (True, False, False, {"invisible"}),
        (False, False, True, {"visible"}),
        (True, True, False, {"invisible", "perturb"}),
        (False, True, False, {"perturb"}),
    ],
)
def test_checkbox_combos_reach_pipeline(window, invisible, sd, visible, expected) -> None:
    window.layer_invisible.setChecked(invisible)
    window.layer_sd.setChecked(sd)
    window.layer_visible.setChecked(visible)

    options = window._build_options()
    assert options.layers == frozenset(expected)
    # The SD checkbox is what selects the perturber; the layer set alone must not drift.
    assert options.perturber == ("sd" if sd else "noop")


def test_plan_items_gives_two_distinct_outputs_for_same_stem_batch(window, tmp_path) -> None:
    first = tmp_path / "A" / "IMG_0001.JPG"
    second = tmp_path / "B" / "img_0001.jpg"
    first.parent.mkdir()
    second.parent.mkdir()
    Image.new("RGB", (320, 240), (120, 130, 140)).save(first, quality=90)
    Image.new("RGB", (320, 240), (140, 130, 120)).save(second, quality=90)

    window.suffix.setText("")  # an empty suffix must fall back to the shipped default
    items = window._plan_items([first, second])

    names = [item.output.name for item in items]
    assert len(set(names)) == 2, names
    assert names[0] == "IMG_0001" + outputs.DEFAULT_SUFFIX + ".jpg"
    assert all(item.output.parent == tmp_path for item in items)


def test_plan_items_rejects_a_relative_or_empty_output_dir(window, tmp_path) -> None:
    """P29: the live field must obey the same rule the settings layer applies on load.

    Pre-fix a relative string resolved against the process CWD and ``save_image_atomic``
    silently created the directory tree there.
    """
    source = tmp_path / "in.jpg"
    Image.new("RGB", (320, 240), (90, 100, 110)).save(source, quality=90)

    for bad in ("out", "", "   "):
        window.output_dir.setText(bad)
        with pytest.raises(ValueError, match="absolute"):
            window._plan_items([source])


def test_start_protect_routes_a_bad_output_dir_to_the_error_channel(window, monkeypatch) -> None:
    """P29: the guard fires before any worker starts and reports through ``_error``."""
    tmp = Path(window.output_dir.text())
    source = tmp / "in.jpg"
    Image.new("RGB", (320, 240), (90, 100, 110)).save(source, quality=90)
    window.protect_files.add_paths([source])
    window.output_dir.setText("relative-out")
    shown: list[str] = []
    monkeypatch.setattr(window, "_error", lambda message: shown.append(str(message)))

    window.start_protect()

    assert shown and "absolute" in shown[0]
    assert not window._threads  # no worker was ever started


def test_visible_mode_combo_ignores_text_outside_its_list(window) -> None:
    """P29 probe, measured on PySide6 6.11.1: a non-editable combo keeps its value.

    This is why the widget path cannot smuggle an illegal mode into ``apply`` — the guard
    that matters is the settings-layer whitelist plus ``validate_options``. The pin exists
    so that making the combo editable later cannot silently remove that assumption.
    """
    window.visible_mode.setCurrentText("Bogus")
    assert window.visible_mode.currentText() == config.DEFAULT_VISIBLE_MODE
    window.visible_mode.setCurrentText("tile")
    assert window.visible_mode.currentText() == "tile"


def test_image_filter_follows_the_supported_formats(monkeypatch) -> None:
    """G4: the dialog filter is derived from the loader's format table, not a copy."""
    base = gui._image_filter()
    assert "*.jpg" in base and "*.jpeg" in base and "*.tiff" in base
    assert ".gif" not in base and ".heic" not in base
    # The import-time constant must be the function's output, so a hardcoded copy that
    # silently diverges from the table cannot stay green.
    assert gui._IMAGE_FILTER == gui._image_filter()

    monkeypatch.setattr(config, "SUPPORTED_INPUT_FORMATS", ("PNG",))
    assert gui._image_filter() == "Images (*.png)"


def test_help_exits_zero_without_starting_the_event_loop() -> None:
    """G6: ``--help`` used to fall through to ``app.exec()`` and block until killed."""
    with pytest.raises(SystemExit) as excinfo:
        gui.main(["--help"])
    assert excinfo.value.code == 0


def test_protect_worker_does_not_mutate_caller_options(monkeypatch) -> None:
    """P7: the worker writes cancel_check/instance into its own copy, never the caller's."""
    options = pipeline.ProtectOptions(
        layers=frozenset({pipeline.LAYER_PERTURB}), perturber="sd"
    )
    items = [
        gui.BatchItem(Path("a.jpg"), Path("a_out.jpg")),
        gui.BatchItem(Path("b.jpg"), Path("b_out.jpg")),
    ]

    seen: list[pipeline.ProtectOptions] = []
    monkeypatch.setattr(
        gui.pipeline, "protect", lambda source, output, opts: seen.append(opts) or {}
    )
    sentinel = object()
    gets: list[tuple[str, dict]] = []

    def fake_get(name, **kwargs):
        gets.append((name, kwargs))
        return sentinel

    monkeypatch.setattr(gui.perturb, "get", fake_get)

    worker = gui.ProtectWorker(items, options)
    worker.run()

    assert worker.options is not options
    assert options.perturber_kwargs == {}
    assert options.perturber_instance is None
    assert len(gets) == 1
    assert len(seen) == 2 and seen[0] is seen[1] is worker.options
    assert seen[0].perturber_instance is sentinel
    assert seen[0].perturber_kwargs["cancel_check"]() is False


def test_protect_worker_skips_perturber_without_layer(monkeypatch) -> None:
    options = pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_VISIBLE}))
    items = [gui.BatchItem(Path("a.jpg"), Path("a_out.jpg"))]
    calls: list[object] = []
    monkeypatch.setattr(
        gui.pipeline, "protect", lambda source, output, opts: calls.append(opts) or {}
    )
    monkeypatch.setattr(
        gui.perturb, "get", lambda *a, **k: pytest.fail("must not build a perturber")
    )

    gui.ProtectWorker(items, options).run()

    assert len(calls) == 1


def test_cancel_task_is_idempotent_before_any_task(window) -> None:
    """P7/T10: a fresh window has no worker; cancel must be a quiet no-op."""
    window.cancel_task()
    window.cancel_task()

    assert window.worker is None
    assert window._threads == []


def test_verify_worker_stops_after_current_item_when_cancelled(monkeypatch) -> None:
    """P7/T10: cancellation is observed between items, not in the middle of one."""
    calls: list[Path] = []
    seen: list[str] = []
    finished: list[bool] = []

    def fake_verify(path, expected):
        calls.append(path)
        return {"payload": expected}

    monkeypatch.setattr(gui.pipeline, "verify_expected", fake_verify)
    worker = gui.VerifyWorker([Path("a.jpg"), Path("b.jpg")], "expected", None)
    worker.item_done.connect(
        lambda source, status, detail: (seen.append(source), setattr(worker, "cancelled", True))
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert calls == [Path("a.jpg")]
    assert seen == ["a.jpg"]
    assert finished == [True]


def _envelope_product(tmp_path: Path, payload: str, *, size: int = 320) -> Path:
    """A real envelope product; ``size`` also sets the output long edge."""
    rng = np.random.default_rng(size)
    pixels = rng.integers(40, 210, (size, size, 3), dtype=np.uint8)
    source = tmp_path / f"p35-source-{size}.jpg"
    product = tmp_path / f"p35-product-{size}.jpg"
    Image.fromarray(pixels, "RGB").save(source, quality=92)
    pipeline.protect(
        source,
        product,
        pipeline.ProtectOptions(
            payload=payload,
            payload_envelope=True,
            layers=frozenset({pipeline.LAYER_INVISIBLE}),
            long_edge=size,
            quality=92,
        ),
    )
    return product


def _verify_rows(product: Path, expected: str, auto: bool) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    worker = gui.VerifyWorker([product], expected, None, auto_discover=auto)
    worker.item_done.connect(lambda *args: rows.append(args))
    worker.run()
    return rows


def test_auto_discover_combines_with_expected_and_reports_mismatch(tmp_path) -> None:
    """P35: auto discovery must not hide a mismatch with the expected payload."""
    product = _envelope_product(tmp_path, "owner:alice#001")
    rows = _verify_rows(product, "owner:alice#002", True)

    assert len(rows) == 1
    _, status, detail = rows[0]
    assert status == "未通过"
    assert "owner:alice#001" in detail
    assert "owner:alice#002" in detail


def test_auto_discover_with_matching_expected_passes(tmp_path) -> None:
    product = _envelope_product(tmp_path, "owner:alice#001")
    rows = _verify_rows(product, "owner:alice#001", True)

    assert len(rows) == 1
    assert rows[0][1] == "通过（自动发现）"


def test_auto_discover_without_expected_is_unchanged(tmp_path) -> None:
    product = _envelope_product(tmp_path, "owner:alice#001")
    rows = _verify_rows(product, "", True)

    assert len(rows) == 1
    assert rows[0][1] == "通过（自动发现）"


def test_auto_discover_search_ceiling_covers_expected_envelope(tmp_path) -> None:
    """A 100-byte payload packs to 149 stored bytes, beyond the default 128 search."""
    payload = "L" * 100
    product = _envelope_product(tmp_path, payload, size=800)
    rows = _verify_rows(product, payload, True)

    assert len(rows) == 1
    assert rows[0][1] == "通过（自动发现）"


def test_expected_only_mismatch_still_fails(tmp_path) -> None:
    product = _envelope_product(tmp_path, "owner:alice#001")
    rows = _verify_rows(product, "owner:alice#002", False)

    assert len(rows) == 1
    assert rows[0][1] == "未通过"
