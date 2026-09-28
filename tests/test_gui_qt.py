"""P2 / G6 — the desktop window's own wiring: checkboxes → options, batch naming, --help.

Kept off the fast tier (needs PySide6). QSettings is redirected to a temporary INI before
``MainWindow`` exists, so a developer's real preferences can neither decide these tests nor
be modified by them.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def test_help_exits_zero_without_starting_the_event_loop() -> None:
    """G6: ``--help`` used to fall through to ``app.exec()`` and block until killed."""
    with pytest.raises(SystemExit) as excinfo:
        gui.main(["--help"])
    assert excinfo.value.code == 0
