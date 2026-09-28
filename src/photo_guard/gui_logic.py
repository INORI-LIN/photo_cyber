"""Qt-free GUI logic (P2).

The desktop GUI kept its checkbox→layer mapping and its QSettings coercion inline in
``gui.py``, which left the tests restating the logic instead of calling it. Both live here
now: stdlib only, no Qt import, so the core test tier exercises exactly what the GUI runs.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from . import pipeline

# Keys MainWindow persists, in the order it reads them back.
SETTINGS_KEYS = (
    "output_dir",
    "suffix",
    "visible_text",
    "mode",
    "alpha",
    "long_edge",
    "quality",
)

# QSettings hands numerics back as strings from INI/registry stores, so they are coerced.
_NUMERIC_COERCERS = {"alpha": float, "long_edge": int, "quality": int}


def layers_from_checks(invisible: bool, sd: bool, visible: bool) -> frozenset[str]:
    """Map the three checkboxes to the layer set.

    Membership only — never order (AGENTS §8.1). All three unchecked stays representable as
    the empty set on purpose; ``pipeline.validate_options`` owns that rejection.
    """
    layers: set[str] = set()
    if invisible:
        layers.add(pipeline.LAYER_INVISIBLE)
    if sd:
        layers.add(pipeline.LAYER_PERTURB)
    if visible:
        layers.add(pipeline.LAYER_VISIBLE)
    return frozenset(layers)


def load_settings(
    raw: Mapping[str, object] | None, defaults: Mapping[str, object]
) -> dict[str, object]:
    """Coerce stored settings, falling back **per key** to ``defaults``.

    ``raw`` is what the GUI read back from QSettings (``None`` when that failed); a value
    that cannot be used falls back instead of propagating junk into the widgets.
    ``output_dir`` is only adopted as a non-empty absolute path — a relative string would
    silently resolve against the process CWD.
    """
    values = dict(defaults)
    if raw is None:
        return values
    for key in SETTINGS_KEYS:
        stored = raw.get(key)
        if stored is None:
            continue
        try:
            if key == "output_dir":
                if isinstance(stored, str) and stored and os.path.isabs(stored):
                    values[key] = stored
            elif key in _NUMERIC_COERCERS:
                values[key] = _NUMERIC_COERCERS[key](stored)
            elif isinstance(stored, str):
                values[key] = stored
        except (TypeError, ValueError):
            continue
    return values
