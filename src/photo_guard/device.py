"""Compute-device discovery and selection for PhotoGuard.

Heavy ML imports stay lazy so the watermark-only CLI remains lightweight.
Supported acceleration backends are NVIDIA CUDA on Windows/Linux and Apple
Metal (MPS) on Apple Silicon. Other adapters are reported for diagnostics but
fall back to CPU.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import platform
import subprocess
import shutil
from typing import Literal

Backend = Literal["auto", "cpu", "cuda", "mps"]


@dataclass(frozen=True)
class DeviceInfo:
    backend: str
    name: str
    index: int | None = None
    available: bool = True
    supported: bool = True
    memory_bytes: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def key(self) -> str:
        return self.backend if self.index is None else f"{self.backend}:{self.index}"


def _torch_devices() -> list[DeviceInfo]:
    try:
        import torch
    except ImportError:
        return [DeviceInfo("cpu", platform.processor() or "CPU")]

    devices = [DeviceInfo("cpu", platform.processor() or "CPU")]
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            devices.append(
                DeviceInfo(
                    "cuda",
                    torch.cuda.get_device_name(index),
                    index=index,
                    memory_bytes=int(props.total_memory),
                )
            )
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        devices.append(DeviceInfo("mps", "Apple Metal GPU"))
    return devices


def _other_adapters() -> list[DeviceInfo]:
    """Best-effort display of adapters not supported by the ML backend."""
    system = platform.system()
    commands: list[list[str]] = []
    if system == "Windows":
        commands.append([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ])
    elif system == "Darwin":
        commands.append(["system_profiler", "SPDisplaysDataType", "-json"])
    elif system == "Linux" and shutil.which("lspci"):
        commands.append(["lspci"])

    names: list[str] = []
    for command in commands:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if system == "Darwin":
            try:
                payload = json.loads(result.stdout)
                for item in payload.get("SPDisplaysDataType", []):
                    name = item.get("sppci_model") or item.get("_name")
                    if name:
                        names.append(str(name))
            except (ValueError, TypeError):
                pass
        elif system == "Linux":
            for line in result.stdout.splitlines():
                if "VGA compatible controller" in line or "3D controller" in line:
                    names.append(line.split(": ", 1)[-1].strip())
        else:
            names.extend(x.strip() for x in result.stdout.splitlines() if x.strip())

    supported_names = {d.name.lower() for d in _torch_devices() if d.backend != "cpu"}
    return [
        DeviceInfo("unsupported", name, available=True, supported=False)
        for name in dict.fromkeys(names)
        if not any(s in name.lower() or name.lower() in s for s in supported_names)
    ]


def discover_devices(*, include_unsupported: bool = True) -> list[DeviceInfo]:
    devices = _torch_devices()
    if include_unsupported:
        devices.extend(_other_adapters())
    return devices


def resolve_device(backend: Backend = "auto", index: int | None = None):
    """Return ``(torch.device, dtype, DeviceInfo)`` or raise a clear error."""
    if backend not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError(f"unknown device backend {backend!r}")
    try:
        import torch
    except ImportError as exc:
        if backend in {"cuda", "mps"}:
            raise RuntimeError(f"{backend.upper()} requires the photoguard extra") from exc
        raise RuntimeError("PhotoGuard requires the photoguard extra") from exc

    available = discover_devices(include_unsupported=False)
    if backend == "auto":
        cuda = next((d for d in available if d.backend == "cuda"), None)
        mps = next((d for d in available if d.backend == "mps"), None)
        chosen = cuda or mps or available[0]
    elif backend == "cuda":
        candidates = [d for d in available if d.backend == "cuda"]
        if not candidates:
            raise RuntimeError("CUDA was selected, but no compatible NVIDIA GPU is available")
        chosen = next((d for d in candidates if d.index == (index or 0)), None)
        if chosen is None:
            raise RuntimeError(f"CUDA device index {index} is not available")
    elif backend == "mps":
        chosen = next((d for d in available if d.backend == "mps"), None)
        if chosen is None:
            raise RuntimeError("MPS was selected, but Apple Metal acceleration is unavailable")
    elif backend == "cpu":
        chosen = available[0]
    spec = f"cuda:{chosen.index}" if chosen.backend == "cuda" else chosen.backend
    torch_device = torch.device(spec)
    dtype = torch.float16 if chosen.backend in {"cuda", "mps"} else torch.float32
    return torch_device, dtype, chosen
