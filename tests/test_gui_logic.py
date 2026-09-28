"""P2 — the Qt-free GUI logic must be callable from the core test tier.

Before P2 the checkbox→layer mapping and the QSettings coercion lived inline in ``gui.py``,
so the only "tests" either restated the logic or built a ``ProtectOptions`` directly — they
could not fail when ``gui.py`` broke. These tests call ``gui_logic`` instead, which is the
implementation the GUI itself imports.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from photo_guard import config, gui_logic, outputs, pipeline

_GUI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "photo_guard" / "gui.py"

DEFAULTS = {
    "output_dir": "/tmp/out",
    "suffix": outputs.DEFAULT_SUFFIX,
    "visible_text": config.DEFAULT_VISIBLE_TEXT,
    "mode": config.DEFAULT_VISIBLE_MODE,
    "alpha": config.DEFAULT_VISIBLE_ALPHA,
    "long_edge": config.DEFAULT_LONG_EDGE,
    "quality": config.DEFAULT_JPEG_QUALITY,
}


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
        (False, False, False, set()),
    ],
)
def test_layers_all_combos(invisible, sd, visible, expected) -> None:
    assert gui_logic.layers_from_checks(invisible, sd, visible) == frozenset(expected)


def test_default_checkbox_state_is_the_safe_default() -> None:
    """The startup state (invisible + visible checked) must equal the documented default."""
    assert gui_logic.layers_from_checks(True, False, True) == pipeline.DEFAULT_LAYERS
    # "No layers" stays representable — validate_options owns the rejection.
    with pytest.raises(ValueError):
        pipeline.validate_options(pipeline.ProtectOptions(layers=frozenset()))


def test_load_settings_coerces_saved_values() -> None:
    values = gui_logic.load_settings(
        {
            "output_dir": "/abs/out",
            "suffix": "_x",
            "visible_text": "© t",
            "mode": "tile",
            "alpha": "0.25",
            "long_edge": "640",
            "quality": 70.9,
        },
        DEFAULTS,
    )
    assert values == {
        "output_dir": "/abs/out",
        "suffix": "_x",
        "visible_text": "© t",
        "mode": "tile",
        "alpha": 0.25,
        "long_edge": 640,
        "quality": 70,
    }


def test_load_settings_junk_falls_back_per_key() -> None:
    assert gui_logic.load_settings(None, DEFAULTS) == DEFAULTS
    values = gui_logic.load_settings(
        {
            "output_dir": "relative/path",
            "suffix": 5,
            "visible_text": None,
            "mode": 7,
            "alpha": "not-a-number",
            "long_edge": None,
            "quality": None,
        },
        DEFAULTS,
    )
    assert values == DEFAULTS
    for bad in ("", "out", "../out"):
        assert gui_logic.load_settings({"output_dir": bad}, DEFAULTS)["output_dir"] == DEFAULTS["output_dir"]


def test_load_settings_only_overrides_provided_keys() -> None:
    values = gui_logic.load_settings({"suffix": "_mine"}, DEFAULTS)
    assert values["suffix"] == "_mine"
    assert values["alpha"] == DEFAULTS["alpha"]
    assert values["output_dir"] == DEFAULTS["output_dir"]


def _protect_call_lines(node: ast.AST) -> set[int]:
    return {
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "protect"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "pipeline"
    }


def test_pipeline_protect_is_only_called_by_the_worker_class() -> None:
    """The heavy protect call must never run on the GUI thread (P26's neighbourhood).

    AST-based so reformatting cannot fool it: moving ``pipeline.protect(...)`` into
    ``MainWindow`` — where it would freeze the window for the whole batch — turns this red.
    """
    tree = ast.parse(_GUI_SOURCE.read_text(encoding="utf-8"))
    worker = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProtectWorker"
    )
    assert _protect_call_lines(tree) == _protect_call_lines(worker) != set()
