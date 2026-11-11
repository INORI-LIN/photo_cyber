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

from photo_guard import config, gui, outputs, pipeline
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


def test_export_csv_failure_goes_through_the_error_channel(window, monkeypatch, tmp_path) -> None:
    """P29: an unwritable target must surface as a dialog, not as an unhandled slot error.

    Pre-fix the bare ``open()`` let ``OSError`` escape the slot — the failure mode P25
    measured as a process abort for worker slots.
    """
    window.verify_results = [("in.jpg", "成功", "out.jpg")]
    target = tmp_path / "missing-dir" / "x.csv"
    monkeypatch.setattr(
        gui.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )
    shown: list[str] = []
    monkeypatch.setattr(window, "_error", lambda message: shown.append(str(message)))

    window.export_csv()

    assert shown, "the OSError must be reported through _error"
    assert "导出失败" in shown[0]
    assert not target.exists()


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


_CLOSE_ROUNDS = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import config, gui, outputs

work = Path(os.environ["PG_WORK"])
mode = os.environ["PG_CLOSE_MODE"]
work_seconds = float(os.environ["PG_WORK_SECONDS"])
gui._CLOSE_GRACE_SECONDS = float(os.environ["PG_CLOSE_GRACE"])
gui._CLOSE_RETRY_MS = int(os.environ["PG_CLOSE_RETRY_MS"])

source = work / "in.jpg"
Image.fromarray(
    np.random.default_rng(1).integers(40, 210, (240, 320, 3), dtype=np.uint8), "RGB"
).save(source, quality=90)


def fake_protect(source_path, output_path, options):
    time.sleep(work_seconds)
    return {}


gui.pipeline.protect = fake_protect


class CountingWindow(gui.MainWindow):
    close_events = 0

    def closeEvent(self, event):
        self.close_events += 1
        super().closeEvent(event)


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(work))

window = CountingWindow()
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


def pump(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms=10000):
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
    assert predicate(), "condition not met"


window.start_protect()
pump(80)  # let the thread start; the fake protect still sleeps
window.close()

if mode == "within":
    pump_until(lambda: not window._threads, 10000)
    pump_until(lambda: not window.isVisible(), 5000)
    assert window.close_events >= 2, window.close_events
else:
    pump(400)
    assert window.isVisible(), "timeout path must keep the window open"
    assert window.statusBar().currentMessage() == gui._CLOSE_TIMEOUT_MESSAGE, (
        window.statusBar().currentMessage()
    )
    first = window.close_events
    pump(300)
    assert window.close_events == first, (first, window.close_events)
    pump_until(lambda: not window._threads, 10000)
    window.close()
    pump_until(lambda: not window.isVisible(), 5000)

print("CLOSE_OK")
"""


def _run_close_child(tmp_path, *, mode: str, work: float, grace: float, retry_ms: int) -> None:
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PG_WORK": str(tmp_path),
        "PG_CLOSE_MODE": mode,
        "PG_WORK_SECONDS": str(work),
        "PG_CLOSE_GRACE": str(grace),
        "PG_CLOSE_RETRY_MS": str(retry_ms),
    }
    result = subprocess.run(
        [sys.executable, "-c", _CLOSE_ROUNDS],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"child exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "CLOSE_OK" in result.stdout
    assert "QThread: Destroyed" not in result.stderr
    assert "Internal C++ object" not in result.stderr


def test_close_within_grace_closes_when_worker_finishes(tmp_path) -> None:
    _run_close_child(tmp_path, mode="within", work=0.3, grace=3.0, retry_ms=20)


def test_close_after_grace_keeps_window_and_stops_retrying(tmp_path) -> None:
    _run_close_child(tmp_path, mode="timeout", work=1.2, grace=0.15, retry_ms=20)


def _p35_product(tmp_path, payload: str, *, size: int = 320) -> Path:
    rng = np.random.default_rng(size)
    pixels = rng.integers(40, 210, (size, size, 3), dtype=np.uint8)
    source = tmp_path / "p35-in.jpg"
    product = tmp_path / "p35-out.jpg"
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


def test_start_verify_with_auto_and_wrong_expected_reports_failure(window, tmp_path) -> None:
    """P35: the UI path must show the mismatch instead of a false pass."""
    product = _p35_product(tmp_path, "owner:alice#001")
    window.verify_files.add_paths([product])
    window.verify_auto.setChecked(True)
    window.expected_payload.setText("owner:alice#002")

    window.start_verify()
    _pump_until(lambda: window.worker is None and not window._threads)

    assert window.verify_results
    assert window.verify_results[0][1] == "未通过"
