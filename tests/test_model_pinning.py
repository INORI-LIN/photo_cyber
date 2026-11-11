"""P15 — the model path is pinned on both sides.

The loader must refuse pickle weights (``use_safetensors=True``) and the download must be
reproducible (immutable ``revision``, safetensors-only). Both contracts are pinned here with
stubbed ``torch``/``diffusers``/``huggingface_hub`` modules, so the tests run in the core-only
environment — the real stack is exercised by ``docker.yml``'s offline SD smoke instead.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from photo_guard import config, download, photoguard


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


def _complete_model(path: Path) -> Path:
    """The minimum a loader/build/smoke gate now accepts (Q2/N5)."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "diffusion_pytorch_model.safetensors").write_bytes(b"")
    return path


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

    model = _complete_model(tmp_path / "model")
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


def test_the_download_pins_the_revision_and_filters_formats(monkeypatch, tmp_path) -> None:
    captured: list[dict] = []

    def fake_snapshot_download(**kwargs):
        captured.append(kwargs)
        _complete_model(Path(kwargs["local_dir"]))
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
        _complete_model(Path(kwargs["local_dir"]))
        return str(kwargs["local_dir"])

    _stub(monkeypatch, "huggingface_hub", snapshot_download=fake_snapshot_download)
    models_dir = tmp_path / "models"
    monkeypatch.setattr(config, "PHOTOGUARD_MODELS_DIR", models_dir)
    monkeypatch.setattr(config, "PHOTOGUARD_MODEL_NAME", "sd-vae-ft-mse")

    dest = download.download_sd_vae()

    assert dest == models_dir / "sd-vae-ft-mse"
    assert dest.parent.is_dir()
    assert captured[0]["local_dir"] == str(dest)
