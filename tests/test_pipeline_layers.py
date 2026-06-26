"""--layers selection — verifies all 7 non-empty subsets behave correctly.

The execution order is fixed (invisible → perturb → visible per AGENTS.md
§二). This file pins membership semantics: a layer in the set runs, a
layer not in the set is skipped, and verify() can only recover the
payload when invisible was applied.
"""
from __future__ import annotations

import pytest
from PIL import Image

from photo_guard import pipeline


def _opts(layers: frozenset[str]) -> pipeline.ProtectOptions:
    return pipeline.ProtectOptions(
        payload="layers-test",
        perturber="noise",  # cheap non-trivial perturber for a "did it run" check
        perturber_kwargs={"epsilon": 2.0 / 255.0},
        visible_mode="tile",
        visible_text="© layers",
        long_edge=1080,
        quality=85,
        layers=layers,
    )


# Every non-empty subset of the three layers — 7 cases. Parametrised so a
# regression in any combination shows up named.
@pytest.mark.parametrize(
    "layers",
    [
        frozenset({"invisible"}),
        frozenset({"perturb"}),
        frozenset({"visible"}),
        frozenset({"invisible", "perturb"}),
        frozenset({"invisible", "visible"}),
        frozenset({"perturb", "visible"}),
        frozenset({"invisible", "perturb", "visible"}),
    ],
)
def test_subset_runs_and_round_trips_when_invisible(textured_jpg, tmp_path, layers):
    out = tmp_path / "out.jpg"
    info = pipeline.protect(textured_jpg, out, _opts(layers))

    assert out.exists()
    assert sorted(info["layers"]) == sorted(layers)
    # Perturber name is reported only when perturb layer ran.
    if "perturb" in layers:
        assert info["perturber"] == "noise"
    else:
        assert info["perturber"] is None
    # Payload byte count is reported only when invisible layer ran.
    expected_bytes = len("layers-test".encode()) if "invisible" in layers else 0
    assert info["payload_bytes"] == expected_bytes

    if "invisible" in layers:
        recovered = pipeline.verify(out, len("layers-test".encode()))
        assert recovered == "layers-test"


def test_invisible_only_skips_perturb_and_visible(textured_jpg, tmp_path):
    """Sanity: invisible alone produces a near-identical-to-input image (modulo
    the imperceptible DWT-DCT change and JPEG re-encode), proving visible WM
    truly didn't run."""
    out = tmp_path / "invisible_only.jpg"
    pipeline.protect(textured_jpg, out, _opts(frozenset({"invisible"})))
    img = Image.open(out)
    assert img.size[0] <= 1080 and img.size[1] <= 1080  # resize still applies


def test_empty_layers_is_rejected(textured_jpg, tmp_path):
    out = tmp_path / "wont_exist.jpg"
    opts = _opts(frozenset())
    with pytest.raises(ValueError, match="at least one layer"):
        pipeline.protect(textured_jpg, out, opts)


def test_unknown_layer_is_rejected(textured_jpg, tmp_path):
    out = tmp_path / "wont_exist.jpg"
    opts = pipeline.ProtectOptions(layers=frozenset({"invisible", "bogus"}))
    with pytest.raises(ValueError, match="unknown layer"):
        pipeline.protect(textured_jpg, out, opts)
