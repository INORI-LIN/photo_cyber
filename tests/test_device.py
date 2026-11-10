from __future__ import annotations

import sys
import types

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


def _stub_torch(monkeypatch, *, cuda=False, cuda_names=(), mps=False, memory=4 * 2**30):
    cuda_module = types.SimpleNamespace(
        is_available=lambda: cuda,
        device_count=lambda: len(cuda_names),
        get_device_properties=lambda index: types.SimpleNamespace(total_memory=memory),
        get_device_name=lambda index: cuda_names[index],
    )
    backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps))
    torch = types.SimpleNamespace(
        cuda=cuda_module,
        backends=backends,
        device=lambda spec: f"device:{spec}",
        float16="float16",
        float32="float32",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


@pytest.mark.parametrize("backend", ["auto", "cpu"])
def test_resolve_without_torch_requires_extra(monkeypatch, backend) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(RuntimeError, match="photoguard extra"):
        device.resolve_device(backend)


@pytest.mark.parametrize(
    ("backend", "pattern"), [("cuda", "CUDA requires"), ("mps", "MPS requires")]
)
def test_resolve_without_torch_names_backend(monkeypatch, backend, pattern) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(RuntimeError, match=pattern):
        device.resolve_device(backend)


@pytest.mark.parametrize(
    ("cuda", "mps", "expected_backend", "dtype"),
    [
        (True, True, "cuda", "float16"),
        (False, True, "mps", "float16"),
        (False, False, "cpu", "float32"),
    ],
)
def test_auto_prefers_cuda_then_mps_then_cpu(
    monkeypatch, cuda, mps, expected_backend, dtype
) -> None:
    _stub_torch(
        monkeypatch,
        cuda=cuda,
        cuda_names=("GPU0", "GPU1") if cuda else (),
        mps=mps,
    )
    torch_device, torch_dtype, info = device.resolve_device("auto")

    assert info.backend == expected_backend
    assert info.index == (0 if expected_backend == "cuda" else None)
    assert torch_dtype == dtype
    expected_spec = f"device:{expected_backend}" + (":0" if expected_backend == "cuda" else "")
    assert str(torch_device) == expected_spec
    if expected_backend == "cuda":
        assert info.memory_bytes == 4 * 2**30


def test_explicit_cuda_index_and_out_of_range(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, cuda_names=("GPU0", "GPU1"))
    torch_device, dtype, info = device.resolve_device("cuda", index=1)
    assert info.index == 1 and str(torch_device) == "device:cuda:1" and dtype == "float16"

    with pytest.raises(RuntimeError, match="index 2"):
        device.resolve_device("cuda", index=2)


def test_explicit_cuda_unavailable(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=False)
    with pytest.raises(RuntimeError, match="no compatible NVIDIA GPU"):
        device.resolve_device("cuda")


@pytest.mark.parametrize("available", [True, False])
def test_explicit_mps_available_and_unavailable(monkeypatch, available) -> None:
    _stub_torch(monkeypatch, mps=available)
    if available:
        torch_device, dtype, info = device.resolve_device("mps")
        assert info.backend == "mps" and str(torch_device) == "device:mps" and dtype == "float16"
    else:
        with pytest.raises(RuntimeError, match="Apple Metal"):
            device.resolve_device("mps")


def test_explicit_cpu_wins(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, cuda_names=("GPU0",), mps=True)
    torch_device, dtype, info = device.resolve_device("cpu")
    assert info.backend == "cpu" and str(torch_device) == "device:cpu" and dtype == "float32"


def test_other_adapters_swallows_oserror_and_bad_json(monkeypatch) -> None:
    _stub_torch(monkeypatch)
    monkeypatch.setattr(device.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        device.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )
    assert device._other_adapters() == []

    monkeypatch.setattr(
        device.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="not json")
    )
    assert device._other_adapters() == []


@pytest.mark.parametrize(
    ("system", "stdout", "supported_name", "expected"),
    [
        (
            "Darwin",
            '{"SPDisplaysDataType": [{"sppci_model": "NVIDIA RTX"}, '
            '{"sppci_model": "Intel UHD"}]}',
            "NVIDIA RTX",
            ["Intel UHD"],
        ),
        (
            "Linux",
            "00:02.0 VGA compatible controller: Intel UHD\n"
            "00:03.0 Ethernet controller: Not a GPU\n",
            None,
            ["Intel UHD"],
        ),
        ("Windows", "NVIDIA RTX\nIntel UHD\nIntel UHD\n", "NVIDIA RTX", ["Intel UHD"]),
    ],
)
def test_other_adapters_parses_and_filters_supported_names(
    monkeypatch, system, stdout, supported_name, expected
) -> None:
    _stub_torch(
        monkeypatch,
        cuda=bool(supported_name),
        cuda_names=(supported_name,) if supported_name else (),
    )
    monkeypatch.setattr(device.platform, "system", lambda: system)
    monkeypatch.setattr(
        device.shutil, "which", lambda name: "/usr/bin/lspci" if name == "lspci" else None
    )
    monkeypatch.setattr(
        device.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=stdout)
    )

    adapters = device._other_adapters()
    assert [item.name for item in adapters] == expected
    assert all(item.supported is False for item in adapters)


def test_other_adapters_skips_lspci_when_absent(monkeypatch) -> None:
    _stub_torch(monkeypatch)
    monkeypatch.setattr(device.platform, "system", lambda: "Linux")
    monkeypatch.setattr(device.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        device.subprocess, "run", lambda *a, **k: pytest.fail("must not run a command")
    )
    assert device._other_adapters() == []


def test_discover_devices_include_unsupported_flag(monkeypatch) -> None:
    monkeypatch.setattr(device, "_torch_devices", lambda: [device.DeviceInfo("cpu", "CPU")])
    monkeypatch.setattr(
        device,
        "_other_adapters",
        lambda devices=None: [device.DeviceInfo("unsupported", "GPU", supported=False)],
    )

    assert [item.backend for item in device.discover_devices(include_unsupported=False)] == ["cpu"]
    assert [item.backend for item in device.discover_devices()] == ["cpu", "unsupported"]


def test_discover_devices_probes_the_ml_backend_once(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_torch_devices():
        calls["count"] += 1
        return [device.DeviceInfo("cpu", "CPU")]

    monkeypatch.setattr(device, "_torch_devices", fake_torch_devices)
    monkeypatch.setattr(device.platform, "system", lambda: "Linux")
    monkeypatch.setattr(device.shutil, "which", lambda name: None)

    discovered = device.discover_devices()

    assert calls["count"] == 1
    assert [item.backend for item in discovered] == ["cpu"]


def test_other_adapters_reuses_a_supplied_list(monkeypatch) -> None:
    monkeypatch.setattr(
        device, "_torch_devices", lambda: pytest.fail("must reuse the supplied device list")
    )
    monkeypatch.setattr(device.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        device.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="NVIDIA RTX\nIntel UHD\n"),
    )

    adapters = device._other_adapters([device.DeviceInfo("cuda", "NVIDIA RTX")])

    assert [item.name for item in adapters] == ["Intel UHD"]
