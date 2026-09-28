"""P12 — a finished worker's QThread must be released before Qt deletes it.

Reproduced before the fix (separate processes, offscreen): after one protect run the window
still pointed at the deleted ``QThread`` wrapper, so a second ``start_protect()`` raised
``RuntimeError: Internal C++ object (PySide6.QtCore.QThread) already deleted`` and a plain
``win.close()`` ended the process with SIGSEGV (exit 139).

Skipped in a core-only environment (no PySide6); the desktop tier runs it with zero skips.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import config, outputs
from photo_guard.gui import MainWindow

pytestmark = pytest.mark.gui

_APP = QApplication.instance() or QApplication([])


def _settle(milliseconds: int = 50) -> None:
    """Pump the loop once more so deferred deletes queued by the teardown are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _pump_until(predicate, timeout_ms: int = 30_000) -> None:
    """Run the main event loop until ``predicate`` holds, then let Qt settle."""
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    _settle()
    assert predicate(), f"worker did not settle within {timeout_ms} ms"


@pytest.fixture
def window(tmp_path, monkeypatch):
    source = tmp_path / "in.jpg"
    rng = np.random.default_rng(5)
    pixels = rng.integers(40, 210, (240, 320, 3), dtype=np.uint8)
    Image.fromarray(pixels, "RGB").save(source, quality=90)

    win = MainWindow()
    monkeypatch.setattr(win, "_save_settings", lambda: None)  # never write the real QSettings
    # Whatever this machine's QSettings hold must not decide the test's validity.
    win.payload.setText(config.DEFAULT_PAYLOAD)
    win.visible_text.setText(config.DEFAULT_VISIBLE_TEXT)
    win.suffix.setText(outputs.DEFAULT_SUFFIX)
    win.layer_invisible.setChecked(False)
    win.layer_sd.setChecked(False)
    win.layer_visible.setChecked(True)
    win.long_edge.setValue(320)
    win.output_dir.setText(str(tmp_path))
    win.protect_files.add_paths([source])
    try:
        yield win
    finally:
        win.close()


def test_two_consecutive_protect_runs_each_release_their_thread(window) -> None:
    for round_number in (1, 2):
        window.start_protect()  # pre-fix: the second call dereferences the deleted QThread
        _pump_until(lambda: window.protect_start.isEnabled() and not window._threads)
        assert window.thread is None, f"round {round_number} kept a stale QThread"
        assert window._threads == [], f"round {round_number} kept a thread registered"
        assert [status for _, status, _ in window.protect_results] == ["成功"]


def test_close_after_a_completed_run_is_safe(window) -> None:
    window.start_protect()
    _pump_until(lambda: window.protect_start.isEnabled() and not window._threads)

    assert window.close(), "close() must return True once the worker is released"


def test_cancel_after_a_completed_run_is_a_no_op(window) -> None:
    window.start_protect()
    _pump_until(lambda: window.protect_start.isEnabled() and not window._threads)

    window.cancel_task()  # pre-fix: reaches into the deleted worker wrapper
    assert window.worker is None
