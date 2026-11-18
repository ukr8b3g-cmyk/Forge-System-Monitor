"""Collect one cached snapshot for all of the open WebUI tabs."""

import csv
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import psutil

from .windows_gpu import Adapter, WindowsGpu

NVIDIA_VENDOR = 0x10DE
GPU_FIELDS = {"gpu": "usage", "vram": "vram", "temp": "temperature"}
MIB = 1024 * 1024


def japanese_locale(locale):
    return re.match(r"^(ja(?:$|[-_ (])|japanese(?:$|[-_ (])|日本語)", str(locale).strip(), re.I) is not None


def nvidia_number(value):
    try:
        result = float(value)
        return result if 0 <= result < float("inf") else None
    except ValueError:
        return None


def nvidia_snapshot(command):
    if not command:
        return []
    try:
        result = subprocess.run(
            [command, "--query-gpu=uuid,pci.bus_id,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=2, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    rows = []
    for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
        if len(row) != 7:
            continue
        uuid, bus, name, usage, used, total, temperature = (item.strip() for item in row)
        address = re.fullmatch(r"(?:[0-9a-f]+:)?([0-9a-f]+):([0-9a-f]+)\.([0-7])", bus, re.I)
        pci = tuple(int(part, 16) for part in address.groups()) if address else None
        if not name or not uuid.startswith("GPU-"):
            continue
        adapter = Adapter(name, "PCI " + bus.lower(), pci=pci, uuid=uuid, vendor=NVIDIA_VENDOR)
        used, total = nvidia_number(used), nvidia_number(total)
        memory = {"used": int(used * MIB), "total": int(total * MIB)} if used is not None and total else None
        rows.append((adapter, {"usage": nvidia_number(usage), "vram": memory, "temperature": nvidia_number(temperature)}))
    return rows


def active_compute_devices():
    """Get the already initialized device. Don't start a CUDA or XPU context."""
    torch = sys.modules.get("torch")
    for backend in ("cuda", "xpu"):
        module = getattr(torch, backend, None)
        try:
            if module is not None and module.is_initialized():
                properties = module.get_device_properties(module.current_device())
                name = str(properties.name).casefold().strip()
                uuid = str(getattr(properties, "uuid", "")).lower().removeprefix("gpu-")
                yield name, uuid
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue


def gpu_labels(devices):
    return {f"GPU {i} · {a.name} [{a.location}]": a for i, a in enumerate(devices)}


def selected_adapter(selection, labels):
    if selection != "Auto":
        if selection in labels:
            return labels[selection]
        # The number is for display; the name and PCI address identify the adapter.
        identity = selection.partition(" · ")[2]
        matches = [adapter for label, adapter in labels.items() if identity and label.partition(" · ")[2] == identity]
        return matches[0] if len(matches) == 1 else None
    if len(labels) == 1:
        return next(iter(labels.values()))
    for name, uuid in active_compute_devices():
        matches = [a for a in labels.values() if uuid and a.uuid.lower().removeprefix("gpu-") == uuid]
        if not matches:
            matches = [a for a in labels.values() if a.name.casefold() == name]
        if len(matches) == 1:
            return matches[0]
    return None


class Sampler:
    def __init__(self):
        self.lock = threading.RLock()
        self.windows = None
        self.windows_probed = False
        self.nvidia_command = shutil.which("nvidia-smi")
        self.devices = []
        self.devices_at = -float("inf")
        self.cached_key = None
        self.cached = None
        self.cached_at = -float("inf")
        self.previous_cpu = None

    def adapters(self):
        with self.lock:
            if time.monotonic() - self.devices_at >= 30:
                if os.name == "nt" and not self.windows_probed:
                    self.windows_probed = True
                    try:
                        self.windows = WindowsGpu()
                    except (AttributeError, OSError):
                        pass
                try:
                    devices = self.windows.adapters() if self.windows else []
                except Exception:
                    # The inventory could not be refreshed; retry on the next request.
                    return {}
                self.devices = devices or [a for a, _ in nvidia_snapshot(self.nvidia_command)]
                self.devices_at = time.monotonic()
                self.cached_key = None
            return gpu_labels(self.devices)

    def cpu_usage(self):
        times = psutil.cpu_times()
        # Match psutil's global busy-time definition, including Linux's guest-time overlap.
        total = sum(times) - getattr(times, "guest", 0) - getattr(times, "guest_nice", 0)
        idle = times.idle + getattr(times, "iowait", 0)
        previous = self.previous_cpu
        self.previous_cpu = (total, idle)
        if previous is None:
            return None
        elapsed = total - previous[0]
        busy = elapsed - (idle - previous[1])
        return max(0.0, min(100.0, 100 * busy / elapsed)) if elapsed > 0 else None

    def gpu_readings(self, adapter, metrics):
        if adapter.luid is None:
            nvidia = nvidia_snapshot(self.nvidia_command)
            return next((values for a, values in nvidia if a.uuid == adapter.uuid), {})

        try:
            readings = self.windows.sample(adapter, metrics)
        except Exception:
            readings = {}
        if adapter.vendor != NVIDIA_VENDOR or adapter.pci is None or not self.nvidia_command:
            return readings

        missing = [field for metric, field in GPU_FIELDS.items() if metric in metrics and readings.get(field) is None]
        # Windows supplies bus/device/function without the domain. Reject ambiguous addresses on either side.
        if not missing or sum(device.pci == adapter.pci for device in self.devices) != 1:
            return readings
        matches = [values for device, values in nvidia_snapshot(self.nvidia_command) if device.pci == adapter.pci]
        if len(matches) == 1:
            fallback = matches[0]
            readings.update({field: fallback[field] for field in missing if fallback.get(field) is not None})
        return readings

    def gpu_snapshot(self, metrics, selection, reset_counters):
        try:
            if reset_counters and self.windows is not None:
                self.windows.close()
            if not metrics:
                return {}
            devices = self.adapters()
            adapter = selected_adapter(selection, devices)
            if adapter is not None:
                return {"gpu": {"name": adapter.name, **self.gpu_readings(adapter, metrics)}}
            return {"gpu_status": "select" if devices and selection == "Auto" else "unavailable"}
        except Exception:
            # GPU errors must not discard the CPU and RAM readings.
            return {"gpu_status": "unavailable"} if metrics else {}

    def snapshot(self, metrics, selection, period):
        key = (metrics, selection, period)
        with self.lock:
            elapsed = time.monotonic() - self.cached_at
            if key == self.cached_key and elapsed < period:
                return self.cached
            reset_counters = elapsed > period * 3
            if reset_counters:
                # After a paused browser tab, start a fresh utilization interval.
                self.previous_cpu = None
            result = {}
            if "cpu" in metrics:
                result["cpu"] = self.cpu_usage()
            if "ram" in metrics:
                memory = psutil.virtual_memory()
                result["ram"] = {"used": memory.total - memory.available, "total": memory.total}
            result.update(self.gpu_snapshot(metrics & GPU_FIELDS.keys(), selection, reset_counters))
            self.cached_key = key
            self.cached = result
            self.cached_at = time.monotonic()
            return result

    def close(self):
        with self.lock:
            if self.windows is not None:
                self.windows.close()
            self.cached_key = None
            self.previous_cpu = None
