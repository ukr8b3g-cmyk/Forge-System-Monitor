from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from forge_system_monitor import sensors
from forge_system_monitor.windows_gpu import Adapter


PRIMARY = Adapter("NVIDIA test GPU", "PCI 06:00.0", luid=(0, 1), pci=(6, 0, 0), vendor=sensors.NVIDIA_VENDOR)
SECONDARY = replace(PRIMARY, location="PCI 07:00.0", luid=(0, 2), pci=(7, 0, 0))
PRIMARY_ROW = "GPU-primary, 00000000:06:00.0, NVIDIA test GPU, 83, 1024, 8192, 43"
SECONDARY_ROW = "GPU-secondary, 00000000:07:00.0, NVIDIA test GPU, 95, 4096, 16384, 56"
VRAM = {"used": 1024 * sensors.MIB, "total": 8192 * sensors.MIB}


class SamplerTests(unittest.TestCase):
    def setUp(self):
        subprocess = patch.object(sensors.subprocess, "run", return_value=SimpleNamespace(stdout=PRIMARY_ROW))
        self.run_nvidia = subprocess.start()
        self.addCleanup(subprocess.stop)

    def sampler(self, *devices):
        sampler = sensors.Sampler()
        sampler.windows = Mock()
        sampler.windows.adapters.return_value = list(devices)
        sampler.windows.sample.return_value = {}
        sampler.windows_probed = True
        sampler.nvidia_command = "nvidia-smi"
        return sampler

    def test_fills_only_missing_metrics_for_selected_pci_device(self):
        sampler = self.sampler(PRIMARY, SECONDARY)
        sampler.windows.sample.return_value = {"usage": 0.0, "temperature": None}
        self.run_nvidia.return_value.stdout = "\n".join([SECONDARY_ROW, PRIMARY_ROW])
        selection = next(iter(sensors.gpu_labels([PRIMARY, SECONDARY])))
        metrics = frozenset({"gpu", "vram", "temp"})

        result = sampler.snapshot(metrics, selection, 2)

        self.assertEqual(result["gpu"], {"name": PRIMARY.name, "usage": 0.0, "vram": VRAM, "temperature": 43.0})
        sampler.windows.sample.assert_called_once_with(PRIMARY, metrics)
        self.run_nvidia.assert_called_once()

    def test_skips_unverified_pci_matches(self):
        cases = [
            ("different address", [PRIMARY], SECONDARY_ROW),
            ("malformed address", [PRIMARY], PRIMARY_ROW.replace("00000000:", "invalid:")),
            ("missing Windows address", [replace(PRIMARY, pci=None)], PRIMARY_ROW),
            ("duplicate Windows address", [PRIMARY, replace(SECONDARY, pci=PRIMARY.pci)], PRIMARY_ROW),
            ("duplicate NVIDIA address", [PRIMARY], PRIMARY_ROW + "\n" + PRIMARY_ROW.replace(
                "GPU-primary, 00000000:", "GPU-other-domain, 00000001:"
            )),
            ("non-NVIDIA adapter", [replace(PRIMARY, vendor=0x1002)], PRIMARY_ROW),
        ]
        for description, devices, rows in cases:
            with self.subTest(description=description):
                sampler = self.sampler(*devices)
                self.run_nvidia.return_value.stdout = rows
                selection = next(iter(sensors.gpu_labels(devices)))

                result = sampler.snapshot(frozenset({"temp"}), selection, 2)

                self.assertEqual(result["gpu"], {"name": devices[0].name})

    def test_reuses_cache_until_requested_metrics_change(self):
        sampler = self.sampler(PRIMARY)
        sampler.windows.sample.return_value = {"usage": 0.0}
        metrics = frozenset({"gpu"})

        with patch.object(sensors.time, "monotonic", return_value=10.0):
            first = sampler.snapshot(metrics, "Auto", 2)
            self.assertIs(sampler.snapshot(metrics, "Auto", 2), first)
            self.run_nvidia.assert_not_called()
            updated = sampler.snapshot(metrics | {"temp"}, "Auto", 2)

        self.assertEqual(updated["gpu"], {"name": PRIMARY.name, "usage": 0.0, "temperature": 43.0})
        self.assertEqual(sampler.windows.sample.call_count, 2)
        self.run_nvidia.assert_called_once()

    def test_uses_matching_nvidia_readings_if_windows_sampling_raises(self):
        sampler = self.sampler(PRIMARY)
        sampler.windows.sample.side_effect = OSError("GPU counter failed")

        result = sampler.snapshot(frozenset({"gpu", "vram", "temp"}), "Auto", 2)

        self.assertEqual(result["gpu"], {"name": PRIMARY.name, "usage": 83.0, "vram": VRAM, "temperature": 43.0})

    def test_keeps_cpu_and_ram_when_gpu_is_unavailable(self):
        self.run_nvidia.side_effect = OSError("nvidia-smi unavailable")
        for operation in ("adapters", "sample", "close"):
            with self.subTest(operation=operation):
                sampler = self.sampler(PRIMARY)
                getattr(sampler.windows, operation).side_effect = RuntimeError("Windows GPU failure")
                sampler.cpu_usage = Mock(return_value=12.5)

                with patch.object(sensors.psutil, "virtual_memory", return_value=SimpleNamespace(total=16, available=10)):
                    result = sampler.snapshot(frozenset({"cpu", "ram", "temp"}), "Auto", 2)

                self.assertEqual(result["cpu"], 12.5)
                self.assertEqual(result["ram"], {"used": 6, "total": 16})
                if operation == "sample":
                    self.assertEqual(result["gpu"], {"name": PRIMARY.name})
                else:
                    self.assertEqual(result["gpu_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
