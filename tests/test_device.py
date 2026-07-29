from __future__ import annotations

import pytest

from photo_guard import device


def test_device_info_key() -> None:
    assert device.DeviceInfo("cuda", "GPU", index=2).key == "cuda:2"
    assert device.DeviceInfo("cpu", "CPU").key == "cpu"


def test_discovery_always_has_cpu() -> None:
    assert any(item.backend == "cpu" for item in device.discover_devices(include_unsupported=False))


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        device.resolve_device("bogus")  # type: ignore[arg-type]
