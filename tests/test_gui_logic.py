"""GUI-level logic that is testable without Qt.

``test_unique_output_policy`` used to live here, but it re-implemented the renaming loop
instead of calling it, so it could not fail when the real code broke. That coverage now
lives in ``tests/test_output_integrity.py``, which drives the shipped function.

``test_gui_defaults_are_safe`` is still a weak assertion — it builds a ``ProtectOptions``
directly and so has no coupling to ``gui.py``'s defaults. It is scheduled for replacement
when P2 (fix-plan batch 3) extracts the Qt-free logic and rewrites this file.
"""
from __future__ import annotations

from photo_guard import pipeline


def test_gui_defaults_are_safe() -> None:
    options = pipeline.ProtectOptions(payload_envelope=True)
    assert options.layers == frozenset({"invisible", "visible"})
    assert "perturb" not in options.layers
    pipeline.validate_options(options)
