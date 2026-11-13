"""Qt test harness shared by the two GUI test modules.

Import this **after** ``pytest.importorskip("PySide6")``: the core-only tier must never
load Qt. The two modules keep their own ``window`` fixtures because their preconditions
differ (one seeds a source file and disables settings writes; the other does not), but the
event-loop pump, the QSettings redirect and the envelope product builder are identical.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from photo_guard import pipeline

from tests.support import textured_rgb


def ensure_app() -> QApplication:
    """Return the process-wide QApplication, creating it on first use."""
    return QApplication.instance() or QApplication([])


def settle(milliseconds: int = 50) -> None:
    """Pump the event loop once more so deferred deletes queued by teardown are delivered."""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def pump_until(
    predicate: Callable[[], bool],
    timeout_ms: int = 10_000,
    *,
    settle_ms: int = 0,
    failure: str | None = None,
) -> None:
    """Run the main loop until ``predicate`` holds.

    ``settle_ms`` must stay a per-call choice: ``test_gui_qt`` has always exited as soon as
    the predicate held, while ``test_gui_lifecycle`` needs a 50 ms settle for deferred
    deletes. Unifying the default would either slow one module down or make the other
    flaky.
    """
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
    if settle_ms:
        settle(settle_ms)
    assert predicate(), failure or f"condition not met within {timeout_ms} ms"


def ini_settings_factory():
    """Force QSettings to the INI file under the path set by the test.

    ``QSettings.setDefaultFormat`` does not affect ``QSettings(org, app)`` on PySide6 6.11
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


def redirect_settings(tmp_path: Path, monkeypatch) -> None:
    """Point ``QSettings`` at ``tmp_path`` before any ``MainWindow`` exists."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    import photo_guard.gui as gui

    monkeypatch.setattr(gui, "QSettings", ini_settings_factory())


def envelope_product(
    tmp_path: Path, payload: str, *, size: int = 320, prefix: str = "envelope"
) -> Path:
    """Build a real envelope product at ``long_edge=size`` and return its path.

    The source/payload names include the size so a test that builds two products in one
    ``tmp_path`` cannot silently overwrite the first (the old ``p35-in/out.jpg`` did).
    """
    pixels = textured_rgb((size, size), seed=size, low=40, high=210)
    source = tmp_path / f"{prefix}-{size}-in.jpg"
    product = tmp_path / f"{prefix}-{size}-out.jpg"
    pixels.save(source, quality=92)
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
