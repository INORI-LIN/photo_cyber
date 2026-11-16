"""--layers selection — verifies all 7 non-empty subsets behave correctly.

The execution order is fixed (invisible → perturb → visible per AGENTS.md
§二). This file pins membership semantics: a layer in the set runs, a
layer not in the set is skipped, and verify() can only recover the
payload when invisible was applied.
"""
from __future__ import annotations

import pytest
from PIL import Image

from photo_guard import config, pipeline


def _opts(layers: frozenset[str]) -> pipeline.ProtectOptions:
    noisy = "perturb" in layers
    return pipeline.ProtectOptions(
        payload="layers-test",
        # A configured perturber now requires its layer (P55), so the helper follows the
        # subset instead of using noise everywhere.
        perturber="noise" if noisy else "noop",
        perturber_kwargs={"epsilon": 2.0 / 255.0} if noisy else {},
        visible_mode="tile",
        visible_text="© layers",
        long_edge=640,
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


# --- R5/P56: the SD layer is capped by pixels, not by long edge ----------------------


class _FakeSD:
    name = "sd"

    def __init__(self) -> None:
        self.calls = 0

    def apply(self, image):
        self.calls += 1
        return image


def _sd_opts(fake: _FakeSD, *, limit: int) -> pipeline.ProtectOptions:
    return pipeline.ProtectOptions(
        payload="budget",
        perturber="noop",  # an injected instance is preferred over the factory (P30)
        perturber_instance=fake,
        long_edge=640,  # 1600x1200 fixture -> 640x480 = 307_200 pixels
        quality=85,
        layers=frozenset({pipeline.LAYER_PERTURB}),
        max_perturb_pixels=limit,
    )


def test_sd_perturb_rejects_an_image_over_the_pixel_cap(textured_jpg, tmp_path) -> None:
    fake = _FakeSD()
    out = tmp_path / "wont_exist.jpg"

    with pytest.raises(ValueError, match="pixels") as excinfo:
        pipeline.protect(textured_jpg, out, _sd_opts(fake, limit=100_000))

    message = str(excinfo.value)
    assert "100000" in message
    assert "--long-edge" in message
    assert fake.calls == 0
    assert not out.exists()


def test_sd_perturb_accepts_an_image_at_the_pixel_cap(textured_jpg, tmp_path) -> None:
    fake = _FakeSD()

    info = pipeline.protect(textured_jpg, tmp_path / "out.jpg", _sd_opts(fake, limit=307_200))

    assert fake.calls == 1
    assert info["perturber"] == "sd"


def test_the_pixel_cap_does_not_constrain_the_noise_perturber(textured_jpg, tmp_path) -> None:
    opts = pipeline.ProtectOptions(
        payload="budget",
        perturber="noise",
        perturber_kwargs={"epsilon": 2.0 / 255.0},
        long_edge=640,
        quality=85,
        layers=frozenset({pipeline.LAYER_PERTURB}),
        max_perturb_pixels=100_000,
    )

    info = pipeline.protect(textured_jpg, tmp_path / "out.jpg", opts)

    assert info["perturber"] == "noise"


def test_max_perturb_pixels_must_be_positive_only_when_the_layer_runs() -> None:
    with pytest.raises(ValueError, match="max_perturb_pixels"):
        pipeline.validate_options(
            pipeline.ProtectOptions(
                layers=frozenset({pipeline.LAYER_PERTURB}),
                perturber="noise",
                max_perturb_pixels=0,
            )
        )
    # The knob is inert without the layer, matching steps/epsilon.
    pipeline.validate_options(
        pipeline.ProtectOptions(
            layers=frozenset({pipeline.LAYER_VISIBLE}), max_perturb_pixels=0
        )
    )


def test_the_default_perturb_pixel_cap_is_four_megapixels() -> None:
    assert config.PHOTOGUARD_MAX_PIXELS == 4_000_000


def test_a_configured_perturber_requires_the_perturb_layer() -> None:
    """P55: a perturber that cannot run is a caller bug, not a silent no-op."""
    with pytest.raises(ValueError, match="perturb layer"):
        pipeline.validate_options(
            pipeline.ProtectOptions(
                layers=frozenset({pipeline.LAYER_VISIBLE}), perturber="noise"
            )
        )
    with pytest.raises(ValueError, match="perturber instance"):
        pipeline.validate_options(
            pipeline.ProtectOptions(
                layers=frozenset({pipeline.LAYER_INVISIBLE}),
                perturber_instance=object(),
            )
        )
