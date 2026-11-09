"""G7 — the setup subcommands (``devices`` / ``download-models``) without hardware or network.

``download_sd_vae`` is always stubbed; no HuggingFace request and no real model
directory is involved.  ``devices`` is fed a fixed discovery result so the
formatting contract is checked exactly.
"""
from __future__ import annotations

import pytest

from photo_guard import config, device
from photo_guard.cli import main


def test_devices_prints_exact_rows(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        device,
        "discover_devices",
        lambda: [
            device.DeviceInfo("cpu", "CPU"),
            device.DeviceInfo("cuda", "GPU", index=0, memory_bytes=4 * 2**30),
            device.DeviceInfo("unsupported", "Intel", supported=False),
        ],
    )

    assert main(["devices"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "cpu: CPU [supported]",
        "cuda:0: GPU 4.0 GiB [supported]",
        "unsupported: Intel [unsupported (CPU fallback)]",
    ]


@pytest.mark.parametrize("command", ["devices", "download-models"])
def test_setup_help_exits_zero(command, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main([command, "--help"])
    assert raised.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_download_models_success(monkeypatch, tmp_path, capsys) -> None:
    import photo_guard.download as download

    monkeypatch.setattr(download, "download_sd_vae", lambda **kwargs: tmp_path / "model")

    assert main(["download-models"]) == 0
    out = capsys.readouterr().out
    assert f"{config.PHOTOGUARD_REMOTE_REPO}@{config.PHOTOGUARD_REVISION}" in out
    assert f"-> {tmp_path / 'model'}" in out
    assert "(json + safetensors only)" in out


def test_download_models_failure_exits_two(monkeypatch, capsys) -> None:
    import photo_guard.download as download

    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(download, "download_sd_vae", boom)

    assert main(["download-models"]) == 2
    assert "download-models failed: boom" in capsys.readouterr().err
