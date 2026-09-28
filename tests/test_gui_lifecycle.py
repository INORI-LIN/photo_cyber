"""P12 / P25 / P26 — worker lifecycle: release, exception safety, cross-thread progress.

P12 (reproduced pre-fix in separate processes, offscreen): after one protect run the window
still pointed at the deleted ``QThread`` wrapper, so a second ``start_protect()`` raised
``RuntimeError: Internal C++ object (PySide6.QtCore.QThread) already deleted`` and a plain
``win.close()`` ended the process with SIGSEGV (exit 139).

P25: an exception escaping ``run()`` meant ``finished`` never fired — the thread stayed
registered, the start button stayed disabled and ``close()`` was refused forever.

P26: progress connected through a plain lambda ran in the *worker* thread, so Qt repainted
from outside the GUI thread; with a shown window under offscreen the second round died with
SIGSEGV (exit 139). Delivered through bound slots, it is queued to the main thread.

Skipped in a core-only environment (no PySide6); the desktop tier runs it with zero skips.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import config, gui, outputs
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


def test_worker_exception_still_releases_the_thread(window, monkeypatch) -> None:
    """P25 — pre-fix the escaped exception stranded the thread, disabled the start button
    and made ``close()`` return False forever."""
    def boom(*args, **kwargs):
        raise RuntimeError("boom from perturb.get")

    monkeypatch.setattr(gui.perturb, "get", boom)
    window.layer_invisible.setChecked(False)
    window.layer_sd.setChecked(True)  # the only path that calls perturb.get
    window.layer_visible.setChecked(False)

    window.start_protect()
    _pump_until(lambda: window.protect_start.isEnabled() and not window._threads)

    assert [status for _, status, _ in window.protect_results] == ["失败"]
    assert "boom" in window.protect_results[0][2]
    assert window.close()


_SHOWN_ROUNDS = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import config, gui, outputs

work = Path(os.environ["PG_WORK"])
source = work / "in.jpg"
Image.fromarray(
    np.random.default_rng(1).integers(40, 210, (240, 320, 3), dtype=np.uint8), "RGB"
).save(source, quality=90)

app = QApplication.instance() or QApplication([])
window = gui.MainWindow()
window._save_settings = lambda: None
window.payload.setText(config.DEFAULT_PAYLOAD)
window.visible_text.setText(config.DEFAULT_VISIBLE_TEXT)
window.suffix.setText(outputs.DEFAULT_SUFFIX)
window.layer_invisible.setChecked(False)
window.layer_sd.setChecked(False)
window.layer_visible.setChecked(True)
window.long_edge.setValue(320)
window.output_dir.setText(str(work))
window.protect_files.add_paths([source])
window.show()


def pump():
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(
        lambda: loop.quit() if (not window._threads and window.protect_start.isEnabled()) else None
    )
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(20000)
    loop.exec()
    poll.stop()
    assert not window._threads, "round did not settle"


for _ in range(2):
    window.start_protect()
    pump()
print("two shown rounds completed")
"""


def test_two_shown_rounds_under_offscreen_do_not_crash(tmp_path) -> None:
    """P26 — the crash is SIGSEGV, so the rounds run in a child process (exit 139 pre-fix)."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PG_WORK": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", _SHOWN_ROUNDS],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"child exited {result.returncode}\n{result.stderr}"
    assert "two shown rounds completed" in result.stdout
