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

    attack = photoguard._SDEncoderAttack(photoguard.PGDConfig(model_id=str(tmp_path)))
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


def test_the_download_pins_the_revision_and_filters_formats(monkeypatch, tmp_path) -> None:
    captured: list[dict] = []

    def fake_snapshot_download(**kwargs):
        captured.append(kwargs)
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
