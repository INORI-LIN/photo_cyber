"""P2 / G6 — the desktop window's own wiring: checkboxes → options, batch naming, --help.

Kept off the fast tier (needs PySide6). QSettings is redirected to a temporary INI before
``MainWindow`` exists, so a developer's real preferences can neither decide these tests nor
be modified by them.
"""
from __future__ import annotations

import csv
import os
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import config, gui, outputs, pipeline

pytestmark = pytest.mark.gui

_APP = QApplication.instance() or QApplication([])


def _pump_until(predicate, timeout_ms: int = 10_000) -> None:
    """Run the main loop until ``predicate`` holds (no sleeps in the test body)."""
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    assert predicate(), f"condition not met within {timeout_ms} ms"


def _ini_settings_factory():
    """Force QSettings to an INI under the path set by the test.

    QSettings.setDefaultFormat does not affect ``QSettings(org, app)`` on PySide6 6.11
    (measured while adding Q3/N7): the constructor kept using the native plist, so the
    fixture was silently reading the developer's real preferences. Passing the format and
    scope explicitly is the only reliable redirect.
    """
    return lambda *_args, **_kwargs: QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "PhotoGuard",
        "PhotoGuardDesktop",
    )


@pytest.fixture
def window(tmp_path, monkeypatch):
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr(gui, "QSettings", _ini_settings_factory())
    # Q3/N6: discovery is asynchronous now; never import the real torch in a GUI test.
    monkeypatch.setattr(
        gui.device,
        "discover_devices",
        lambda **_kwargs: [gui.device.DeviceInfo("cpu", "test-cpu")],
    )
    win = gui.MainWindow()
    _pump_until(lambda: not win._device_discovery_running())
    win.payload.setText(config.DEFAULT_PAYLOAD)
    win.visible_text.setText(config.DEFAULT_VISIBLE_TEXT)
    win.suffix.setText(outputs.DEFAULT_SUFFIX)
    win.output_dir.setText(str(tmp_path))
    win.long_edge.setValue(320)
    try:
        yield win
    finally:
        win.close()
        _pump_until(lambda: not win._device_discovery_running())


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


def test_protect_worker_surfaces_pipeline_warnings(monkeypatch) -> None:
    """Q1/N2: the blind-ceiling warning must reach the GUI log, not just the process stderr."""
    options = pipeline.ProtectOptions(layers=frozenset({pipeline.LAYER_VISIBLE}))
    items = [gui.BatchItem(Path("a.jpg"), Path("a_out.jpg"))]
    rows: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        gui.pipeline,
        "protect",
        lambda source, output, opts: {"warnings": ["use --max-payload-bytes 257"]},
    )

    worker = gui.ProtectWorker(items, options)
    worker.item_done.connect(lambda source, status, detail: rows.append((source, status, detail)))
    worker.run()

    assert rows[0][1] == "成功"
    assert "use --max-payload-bytes 257" in rows[0][2]


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
    """A 200-byte payload packs to 281 stored bytes, beyond the current 256 default."""
    payload = "L" * 200
    product = _envelope_product(tmp_path, payload, size=1200)
    rows = _verify_rows(product, payload, True)

    assert len(rows) == 1
    assert rows[0][1] == "通过（自动发现）"


def test_expected_only_mismatch_still_fails(tmp_path) -> None:
    product = _envelope_product(tmp_path, "owner:alice#001")
    rows = _verify_rows(product, "owner:alice#002", False)

    assert len(rows) == 1
    assert rows[0][1] == "未通过"


# --- Q3: device discovery, settings, mutual exclusion, CSV export -------------------


def _redirect_settings(tmp_path: Path, monkeypatch) -> None:
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr(gui, "QSettings", _ini_settings_factory())


def _device(backend: str, name: str, index: int | None = None):
    return gui.device.DeviceInfo(backend, name, index=index)


def _construct_window(tmp_path: Path, monkeypatch, fake):
    _redirect_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(gui.device, "discover_devices", fake)
    return gui.MainWindow()


def test_device_discovery_runs_off_the_main_thread(tmp_path, monkeypatch) -> None:
    """Q3/N6: constructing the window must not import torch/probe devices synchronously."""
    gate = threading.Event()
    seen: dict[str, int] = {}

    def fake(**_kwargs):
        seen["ident"] = threading.get_ident()
        gate.wait(5)
        return [_device("cpu", "test-cpu")]

    timer = threading.Timer(0.5, gate.set)
    timer.start()
    win = _construct_window(tmp_path, monkeypatch, fake)
    try:
        assert win.device_table.rowCount() == 0
        _pump_until(lambda: not win._device_discovery_running())
        assert seen["ident"] != threading.get_ident()
        assert win.device_table.rowCount() == 1
    finally:
        gate.set()
        _pump_until(lambda: not win._device_discovery_running())
        win.close()
        _pump_until(lambda: not win._device_discovery_running())


def test_device_discovery_failure_keeps_the_window_usable(tmp_path, monkeypatch) -> None:
    def fake(**_kwargs):
        raise RuntimeError("probe exploded")

    win = _construct_window(tmp_path, monkeypatch, fake)
    try:
        _pump_until(lambda: not win._device_discovery_running())
        assert "设备检测失败" in win.statusBar().currentMessage()
        assert win.device_combo.count() >= 1
        assert tuple(win.device_combo.currentData()) == ("auto", None)
    finally:
        win.close()
        _pump_until(lambda: not win._device_discovery_running())


def test_refresh_preserves_the_selected_device_and_falls_back(tmp_path, monkeypatch) -> None:
    """Q3/N6: the old code cleared the combo before the probe returned."""
    devices = [_device("cpu", "test-cpu"), _device("cuda", "test-gpu", index=0)]

    def fake(**_kwargs):
        return list(devices)

    win = _construct_window(tmp_path, monkeypatch, fake)
    try:
        _pump_until(lambda: not win._device_discovery_running())
        index = next(
            i for i in range(win.device_combo.count())
            if tuple(win.device_combo.itemData(i)) == ("cuda", 0)
        )
        win.device_combo.setCurrentIndex(index)

        win.refresh_devices()
        assert tuple(win.device_combo.currentData()) == ("cuda", 0)
        _pump_until(lambda: not win._device_discovery_running())
        assert tuple(win.device_combo.currentData()) == ("cuda", 0)

        devices.pop()  # the next probe no longer offers cuda
        win.refresh_devices()
        _pump_until(lambda: not win._device_discovery_running())
        assert tuple(win.device_combo.currentData()) == ("auto", None)
    finally:
        win.close()
        _pump_until(lambda: not win._device_discovery_running())


class _Event:
    def __init__(self) -> None:
        self.accepted = False

    def ignore(self) -> None:
        pass

    def accept(self) -> None:
        self.accepted = True


def test_close_saves_settings_for_the_next_window(tmp_path, monkeypatch) -> None:
    """Q3/N7: changing settings and closing must persist them (old code saved only on protect)."""
    first = _construct_window(tmp_path, monkeypatch, lambda **_kwargs: [])
    _pump_until(lambda: not first._device_discovery_running())
    first.quality.setValue(77)
    event = _Event()
    first.closeEvent(event)
    assert event.accepted

    second = _construct_window(tmp_path, monkeypatch, lambda **_kwargs: [])
    try:
        _pump_until(lambda: not second._device_discovery_running())
        assert second.quality.value() == 77
    finally:
        second.close()
        _pump_until(lambda: not second._device_discovery_running())


def test_verify_start_saves_settings(tmp_path, monkeypatch) -> None:
    win = _construct_window(tmp_path, monkeypatch, lambda **_kwargs: [])
    try:
        _pump_until(lambda: not win._device_discovery_running())
        source = tmp_path / "verify.jpg"
        Image.new("RGB", (320, 320), (40, 80, 120)).save(source, quality=92)
        win.verify_files.add_paths([source])
        win.expected_payload.setText("owner:x")
        win.quality.setValue(66)
        monkeypatch.setattr(win, "_start_worker", lambda *_args: True)  # no thread needed
        win.start_verify()
        assert int(win.settings.value("quality")) == 66
    finally:
        win.close()
        _pump_until(lambda: not win._device_discovery_running())


def test_verify_worker_rejects_both_modes() -> None:
    """Q3/N8: the worker is the second gate for programmatic callers."""
    with pytest.raises(ValueError, match="二选一"):
        gui.VerifyWorker([Path("a.jpg")], "owner", 4, False)


def test_start_verify_rejects_both_modes_without_touching_results(window, monkeypatch) -> None:
    source = Path(window.output_dir.text()) / "verify.jpg"
    Image.new("RGB", (320, 320), (40, 80, 120)).save(source, quality=92)
    window.verify_files.add_paths([source])
    window.expected_payload.blockSignals(True)
    window.expected_payload.setText("owner")
    window.legacy_bytes.blockSignals(True)
    window.legacy_bytes.setValue(4)
    window.verify_results = [("old.jpg", "成功", "out.jpg")]
    errors: list[str] = []
    monkeypatch.setattr(window, "_error", lambda message: errors.append(message))
    monkeypatch.setattr(window, "_start_worker", lambda *_args: False)

    window.start_verify()

    assert "二选一" in errors[-1]
    assert window.verify_results == [("old.jpg", "成功", "out.jpg")]


def test_expected_and_legacy_inputs_disable_each_other(window) -> None:
    window.legacy_bytes.setValue(5)
    assert window.expected_payload.isEnabled() is False
    window.legacy_bytes.setValue(0)
    assert window.expected_payload.isEnabled() is True

    window.expected_payload.setText("owner")
    assert window.legacy_bytes.isEnabled() is False
    assert window.legacy_bytes.value() == 0
    window.expected_payload.clear()
    assert window.legacy_bytes.isEnabled() is True


def test_export_csv_neutralises_formula_cells(window, monkeypatch, tmp_path) -> None:
    """Q3/P37: every untrusted cell that looks like a formula gets the apostrophe."""
    window.verify_results = [
        ("-2+3.jpg", "成功", "=1+1"),
        ("normal.jpg", "结果", "normal"),
    ]
    target = tmp_path / "verify.csv"
    monkeypatch.setattr(
        gui.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(target), "CSV (*.csv)")
    )

    window.export_csv()

    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1] == ["'-2+3.jpg", "成功", "'=1+1"]
    assert rows[2] == ["normal.jpg", "结果", "normal"]


def test_export_csv_unicode_error_goes_through_the_error_channel(window, monkeypatch, tmp_path) -> None:
    """Q3/P37: a surrogate in a recovered path must not escape the slot."""
    window.verify_results = [("in.jpg", "成功", "\ud800")]
    target = tmp_path / "verify.csv"
    monkeypatch.setattr(
        gui.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(target), "CSV (*.csv)")
    )
    errors: list[str] = []
    monkeypatch.setattr(window, "_error", lambda message: errors.append(message))

    window.export_csv()

    assert errors and "导出失败" in errors[0]
