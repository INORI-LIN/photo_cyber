"""P15 — the model path is pinned on both sides.

The loader must refuse pickle weights (``use_safetensors=True``) and the download must be
reproducible (immutable ``revision``, safetensors-only). Both contracts are pinned here with
stubbed ``torch``/``diffusers``/``huggingface_hub`` modules, so the tests run in the core-only
environment — the real stack is exercised by ``docker.yml``'s offline SD smoke instead.
"""
from __future__ import annotations

import importlib.metadata
import re
import sys
import types
from pathlib import Path

import pytest

from photo_guard import config, download, photoguard
from tests.support import complete_model


class _FakeVAE:
    def to(self, device):
        return self

    def eval(self):
        return self

    def parameters(self):
        return iter(())


def _stub(monkeypatch, name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_model_dir_completeness_requires_config_and_a_safetensors_file(tmp_path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert config.model_dir_is_complete(bare) is False

    (bare / "config.json").write_text("{}", encoding="utf-8")
    assert config.model_dir_is_complete(bare) is False  # config only

    (bare / "weights.safetensors").write_bytes(b"")
    assert config.model_dir_is_complete(bare) is True

    (bare / "config.json").unlink()
    assert config.model_dir_is_complete(bare) is False  # weights only

    pickled = tmp_path / "pickled"
    pickled.mkdir()
    (pickled / "config.json").write_text("{}", encoding="utf-8")
    (pickled / "diffusion_pytorch_model.bin").write_bytes(b"")
    assert config.model_dir_is_complete(pickled) is False


def test_the_loader_pins_safetensors_and_the_revision(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    def fake_from_pretrained(path, **kwargs):
        calls.append({"path": path, **kwargs})
        return _FakeVAE()

    _stub(monkeypatch, "torch", float32="float32-stub")
    _stub(monkeypatch, "diffusers", AutoencoderKL=types.SimpleNamespace(
        from_pretrained=fake_from_pretrained
    ))
    monkeypatch.setattr(photoguard.device_mod, "resolve_device", lambda *a, **k: ("cpu", None, None))

    model = complete_model(tmp_path / "model")
    attack = photoguard._SDEncoderAttack(photoguard.PGDConfig(model_id=str(model)))
    attack._load()

    assert len(calls) == 1, calls
    kwargs = calls[0]
    assert kwargs.get("use_safetensors") is True, kwargs
    assert kwargs.get("revision") == config.PHOTOGUARD_REVISION, kwargs
    assert kwargs.get("local_files_only") is True, kwargs
    assert config.PHOTOGUARD_REVISION and len(config.PHOTOGUARD_REVISION) == 40


def test_the_loader_refuses_a_directory_that_does_not_exist(monkeypatch, tmp_path) -> None:
    _stub(monkeypatch, "torch", float32="float32-stub")
    _stub(
        monkeypatch, "diffusers",
        AutoencoderKL=types.SimpleNamespace(from_pretrained=lambda *a, **k: _FakeVAE()),
    )
    monkeypatch.setattr(photoguard.device_mod, "resolve_device", lambda *a, **k: ("cpu", None, None))

    attack = photoguard._SDEncoderAttack(
        photoguard.PGDConfig(model_id=str(tmp_path / "missing"))
    )
    with pytest.raises(RuntimeError, match="download-models"):
        attack._load()


def test_the_loader_refuses_an_incomplete_directory(monkeypatch, tmp_path) -> None:
    """Q2/N5: config.json alone is not a model — the smoke used to accept it."""
    _stub(monkeypatch, "torch", float32="float32-stub")
    _stub(
        monkeypatch, "diffusers",
        AutoencoderKL=types.SimpleNamespace(from_pretrained=lambda *a, **k: _FakeVAE()),
    )
    monkeypatch.setattr(photoguard.device_mod, "resolve_device", lambda *a, **k: ("cpu", None, None))

    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    attack = photoguard._SDEncoderAttack(photoguard.PGDConfig(model_id=str(model)))

    with pytest.raises(RuntimeError, match="incomplete"):
        attack._load()


# --- P76: a failed runtime import must carry its root cause ----------------------------


def _diffusers_without_metadata(monkeypatch) -> importlib.metadata.PackageNotFoundError:
    """``diffusers`` as the P74 bundle saw it: its import-time version check could not find
    the ``requests`` distribution metadata.

    The real module raises while being imported; a PEP 562 ``__getattr__`` raising the same
    exception type on first access is that failure as ``from diffusers import AutoencoderKL``
    sees it. The message is the stdlib's, not diffusers' (whose hint the compliance scan
    forbids in repository files).
    """
    root = importlib.metadata.PackageNotFoundError("requests")

    def __getattr__(name):
        raise root

    _stub(monkeypatch, "diffusers", __getattr__=__getattr__)
    return root


def test_a_failed_runtime_import_keeps_the_uv_hint_and_adds_the_root_cause(
    monkeypatch, tmp_path
) -> None:
    """Source tree: the extra is the usual fix (AGENTS §8.4 keeps the hint), but the fixed
    wording alone hid what actually failed."""
    _stub(monkeypatch, "torch", float32="float32-stub")
    root = _diffusers_without_metadata(monkeypatch)
    monkeypatch.delattr(sys, "frozen", raising=False)

    attack = photoguard._SDEncoderAttack(
        photoguard.PGDConfig(model_id=str(complete_model(tmp_path / "model")))
    )
    with pytest.raises(RuntimeError) as excinfo:
        attack._load()

    message = str(excinfo.value)
    assert "uv sync --extra photoguard" in message
    assert "No package metadata" in message and str(root) in message
    assert "PackageNotFoundError: " in message  # the cause names its type
    assert excinfo.value.__cause__ is root


def test_a_failed_runtime_import_inside_a_bundle_names_the_root_cause_without_uv(
    monkeypatch, tmp_path
) -> None:
    """Inside the installed application there is no uv: P74's release log showed the user a
    command they cannot run instead of the missing metadata."""
    _stub(monkeypatch, "torch", float32="float32-stub")
    root = _diffusers_without_metadata(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    attack = photoguard._SDEncoderAttack(
        photoguard.PGDConfig(model_id=str(complete_model(tmp_path / "model")))
    )
    with pytest.raises(RuntimeError) as excinfo:
        attack._load()

    message = str(excinfo.value)
    assert "No package metadata" in message and str(root) in message
    assert "PackageNotFoundError: " in message  # the cause names its type
    assert re.search(r"\buv\b", message) is None, message
    assert "reinstall" in message
    assert excinfo.value.__cause__ is root


def test_a_dummy_autoencoder_is_reported_as_a_runtime_import_failure(
    monkeypatch, tmp_path
) -> None:
    """Without torch's metadata diffusers still imports but hands out a dummy AutoencoderKL;
    only its ``from_pretrained`` raises ImportError, which used to escape ``_load`` bare."""
    root = ImportError("x1 stub: AutoencoderKL placeholder without its torch backend")

    class _DummyAutoencoderKL:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            raise root

    _stub(monkeypatch, "torch", float32="float32-stub")
    _stub(monkeypatch, "diffusers", AutoencoderKL=_DummyAutoencoderKL)
    monkeypatch.setattr(photoguard.device_mod, "resolve_device", lambda *a, **k: ("cpu", None, None))
    monkeypatch.delattr(sys, "frozen", raising=False)
    # _load sets these with setdefault; pinning them here lets monkeypatch restore the env.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    attack = photoguard._SDEncoderAttack(
        photoguard.PGDConfig(model_id=str(complete_model(tmp_path / "model")))
    )
    with pytest.raises(RuntimeError) as excinfo:
        attack._load()

    message = str(excinfo.value)
    assert str(root) in message
    assert "uv sync --extra photoguard" in message
    assert excinfo.value.__cause__ is root
    assert attack._vae is None


def test_a_diffusers_without_autoencoderkl_is_a_runtime_import_failure(
    monkeypatch, tmp_path
) -> None:
    """``from diffusers import AutoencoderKL`` on a diffusers without the class raises a plain
    ``ImportError`` ("cannot import name"), not ``ModuleNotFoundError``: the guard must catch
    the base class."""
    _stub(monkeypatch, "torch", float32="float32-stub")
    _stub(monkeypatch, "diffusers")
    monkeypatch.delattr(sys, "frozen", raising=False)

    attack = photoguard._SDEncoderAttack(
        photoguard.PGDConfig(model_id=str(complete_model(tmp_path / "model")))
    )
    with pytest.raises(RuntimeError) as excinfo:
        attack._load()

    message = str(excinfo.value)
    assert "uv sync --extra photoguard" in message
    assert "(import failed: ImportError: cannot import name 'AutoencoderKL'" in message
    assert type(excinfo.value.__cause__) is ImportError


# The shape of diffusers' version-check failure (P74), not its text: the real hint after
# " \nTry:" recommends another package manager, which repository files must not quote.
_VERSION_CHECK_SHAPE = (
    "The 'requests' distribution was not found and is required by this application. "
    "\nTry: x1-stub-installer requests -U"
)


@pytest.mark.parametrize("bundled", [False, True], ids=["source-tree", "bundle"])
def test_the_cause_drops_the_package_manager_hint(monkeypatch, bundled) -> None:
    """diffusers appends a hint for another package manager after `` \\nTry:``. A user of
    the installed application cannot act on it, and in a source tree it contradicts the uv
    hint beside it. The chained original (``__cause__``) still carries it."""
    if bundled:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    root = importlib.metadata.PackageNotFoundError(_VERSION_CHECK_SHAPE)

    message = str(photoguard._runtime_import_error(root))

    assert (
        "PackageNotFoundError: No package metadata was found for The 'requests' distribution "
        "was not found and is required by this application." in message
    )
    assert "Try:" not in message and "x1-stub-installer" not in message
    assert "\n" not in message
    assert ("uv sync --extra photoguard" in message) is not bundled
    if bundled:
        assert re.search(r"\buv\b", message) is None, message


@pytest.mark.parametrize("bundled", [False, True], ids=["source-tree", "bundle"])
def test_the_cause_is_one_line(monkeypatch, bundled) -> None:
    """The dummy class's message starts with a newline and spans lines; the smoke prints the
    cause inside a single log line."""
    if bundled:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    root = ImportError("\nx1 stub: AutoencoderKL needs its torch\nbackend.\n")

    message = str(photoguard._runtime_import_error(root))

    assert "\n" not in message
    cause = "ImportError: x1 stub: AutoencoderKL needs its torch backend."
    if bundled:
        assert f"failed to import ({cause}). The installation is incomplete" in message
    else:
        assert message.endswith(f"(import failed: {cause})")


def test_only_the_literal_try_hint_is_cut(monkeypatch) -> None:
    """The cut is the case-sensitive literal `` Try:``; other uses of the word stay."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    text = "x1 stub: try: the other build. Try again later"

    message = str(photoguard._runtime_import_error(ImportError(text)))

    assert message.endswith(f"(import failed: ImportError: {text})")


@pytest.mark.parametrize(("length", "capped"), [(300, False), (301, True)])
def test_the_cause_is_capped_at_300_characters(monkeypatch, length, capped) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    text = ("x1 stub " + "y" * length)[:length]

    message = str(photoguard._runtime_import_error(ImportError(text)))

    shown = text[:297] + "..." if capped else text
    assert message.endswith(f"(import failed: ImportError: {shown})")


def test_the_download_pins_the_revision_and_filters_formats(monkeypatch, tmp_path) -> None:
    captured: list[dict] = []

    def fake_snapshot_download(**kwargs):
        captured.append(kwargs)
        complete_model(Path(kwargs["local_dir"]))
        return str(kwargs["local_dir"])

    _stub(monkeypatch, "huggingface_hub", snapshot_download=fake_snapshot_download)

    dest = download.download_sd_vae(dest=tmp_path / "model")

    assert dest == tmp_path / "model"
    assert len(captured) == 1, captured
    kwargs = captured[0]
    assert kwargs["revision"] == config.PHOTOGUARD_REVISION, kwargs
    assert kwargs["repo_id"] == config.PHOTOGUARD_REMOTE_REPO, kwargs
    assert tuple(kwargs["allow_patterns"]) == ("*.json", "*.safetensors"), kwargs
    # Removed in P15: huggingface_hub 1.19 no longer has this parameter at all.
    assert "local_dir_use_symlinks" not in kwargs, kwargs


def test_download_refuses_an_incomplete_snapshot(monkeypatch, tmp_path) -> None:
    """Q2/N5: a "successful" snapshot_download with no weights must not exit 0."""
    _stub(
        monkeypatch,
        "huggingface_hub",
        snapshot_download=lambda **kwargs: str(kwargs["local_dir"]),
    )

    with pytest.raises(RuntimeError, match="incomplete"):
        download.download_sd_vae(dest=tmp_path / "model")


def test_download_without_huggingface_hub_is_actionable(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with pytest.raises(RuntimeError, match="uv sync --extra photoguard"):
        download.download_sd_vae(dest=tmp_path / "model")


def test_download_defaults_to_models_dir_and_creates_parent(monkeypatch, tmp_path) -> None:
    captured: list[dict] = []

    def fake_snapshot_download(**kwargs):
        captured.append(kwargs)
        complete_model(Path(kwargs["local_dir"]))
        return str(kwargs["local_dir"])

    _stub(monkeypatch, "huggingface_hub", snapshot_download=fake_snapshot_download)
    models_dir = tmp_path / "models"
    monkeypatch.setattr(config, "PHOTOGUARD_MODELS_DIR", models_dir)
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_NAME", "sd-vae-ft-mse")

    dest = download.download_sd_vae()

    assert dest == models_dir / "sd-vae-ft-mse"
    assert dest.parent.is_dir()
    assert captured[0]["local_dir"] == str(dest)
