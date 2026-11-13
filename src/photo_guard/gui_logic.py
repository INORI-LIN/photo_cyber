"""Qt-free GUI logic (P2).

The desktop GUI kept its checkbox→layer mapping and its QSettings coercion inline in
``gui.py``, which left the tests restating the logic instead of calling it. Both live here
now: stdlib only, no Qt import, so the core test tier exercises exactly what the GUI runs.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from . import config, pipeline

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


def validate_output_dir(raw: str) -> str:
    """Return the normalised absolute output directory, or raise ``ValueError``.

    P29: one rule shared by the settings layer (on load) and the live output-dir field
    (before a protect run starts). The live field used to bypass the check entirely, so a
    relative string resolved against the process CWD — the red run for this fix literally
    wrote ``relative-out/in_protected.jpg`` next to the repository. Order matters:
    ``strip`` first, then expand ``~``, and only then demand an absolute path.
    """
    text = (raw or "").strip()
    expanded = os.path.expanduser(text)
    if not expanded or not os.path.isabs(expanded):
        raise ValueError(f"output directory must be a non-empty absolute path: {raw!r}")
    return expanded


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


_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe_cell(value: object) -> str:
    """Prefix a spreadsheet-formula lead-in with an apostrophe (Q3/P37).

    CSV quoting is transport syntax: a consumer still parses ``=1+1`` as a formula after
    splitting the columns, so ``QUOTE_ALL`` is not a defence. Excel/LibreOffice treat a
    leading apostrophe as "text"; some importers display it, so the guarantee is "not
    evaluated", not "invisible".
    """
    text = str(value)
    if text.startswith(_CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text


def verify_argument_conflict(expected: str, legacy_bytes: int | None) -> bool:
    """True when both verify modes are requested (Q3/N8).

    The CLI makes ``--expected-payload`` and ``--payload-bytes`` mutually exclusive; the GUI
    used to let both through and ``VerifyWorker`` silently ignored ``legacy_bytes``. Empty or
    whitespace-only expected and 0/None legacy count as "not set".
    """
    return bool((expected or "").strip()) and legacy_bytes not in (None, 0)


def load_settings(
    raw: Mapping[str, object] | None, defaults: Mapping[str, object]
) -> dict[str, object]:
    """Coerce stored settings, falling back **per key** to ``defaults``.

    ``raw`` is what the GUI read back from QSettings (``None`` when that failed); a value
    that cannot be used falls back instead of propagating junk into the widgets.
    ``output_dir`` goes through :func:`validate_output_dir` (non-empty, ``~`` expanded,
    absolute) and ``mode`` must be one of ``config.VISIBLE_MODES`` — a relative path or an
    unknown mode would otherwise be written straight back into the widgets (P29).
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
                if isinstance(stored, str):
                    values[key] = validate_output_dir(stored)
            elif key == "mode":
                if isinstance(stored, str) and stored in config.VISIBLE_MODES:
                    values[key] = stored
            elif key in _NUMERIC_COERCERS:
                values[key] = _NUMERIC_COERCERS[key](stored)
            elif isinstance(stored, str):
                values[key] = stored
        except (TypeError, ValueError):
            continue
    return values
