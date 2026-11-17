"""Cross-platform collector factory and stateful energy-integrating PowerEngine."""

from __future__ import annotations

import platform
import time
from typing import Optional

from wattwise.collectors.base import BasePlatformCollector
from wattwise.collectors.linux import LinuxPowerCollector
from wattwise.collectors.macos import MacOSPowerCollector
from wattwise.collectors.windows import WindowsPowerCollector
from wattwise.models import PowerSnapshot
from wattwise.storage import WattWiseStorage


def create_platform_collector() -> BasePlatformCollector:
    """Instantiate the native collector matching the current operating system."""
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return WindowsPowerCollector()
    if sys_name == "darwin":
        return MacOSPowerCollector()
    return LinuxPowerCollector()


class PowerEngine:
    """Orchestrates periodic telemetry sampling, Wh energy integration, and SQLite persistence."""

    def __init__(
        self,
        collector: Optional[BasePlatformCollector] = None,
        storage: Optional[WattWiseStorage] = None,
    ) -> None:
        self.collector = collector or create_platform_collector()
        self.storage = storage
        self.session_start_ts = time.time()
        self._last_sample_ts: Optional[float] = None
        self.session_energy_wh: float = 0.0
        self.peak_watts: float = 0.0
        self._device_energy_wh: dict[str, float] = {}

    def reset_session(self) -> None:
        self.session_start_ts = time.time()
        self._last_sample_ts = None
        self.session_energy_wh = 0.0
        self.peak_watts = 0.0
        self._device_energy_wh.clear()

    def sample(self) -> PowerSnapshot:
        snap = self.collector.collect()
        now = snap.timestamp

        delta_wh = 0.0
        cpu_wh = 0.0
        gpu_wh = 0.0
        device_deltas: dict[str, float] = {}

        if self._last_sample_ts is not None:
            dt_sec = now - self._last_sample_ts
            # Ignore sleep/hibernate gaps (> 20s) so suspended state isn't integrated at active watts
            if 0.05 <= dt_sec <= 20.0:
                hr_frac = dt_sec / 3600.0
                delta_wh = max(0.0, snap.total_watts * hr_frac)
                cpu_wh = max(0.0, snap.cpu_watts * hr_frac)
                gpu_wh = max(0.0, snap.gpu_watts * hr_frac)
                self.session_energy_wh += delta_wh
                for comp in snap.components:
                    c_delta = max(0.0, comp.watts * hr_frac)
                    device_deltas[comp.device_id] = c_delta
                    self._device_energy_wh[comp.device_id] = (
                        self._device_energy_wh.get(comp.device_id, 0.0) + c_delta
                    )

        self._last_sample_ts = now
        self.peak_watts = max(self.peak_watts, snap.total_watts)

        for comp in snap.components:
            comp.energy_wh = round(self._device_energy_wh.get(comp.device_id, 0.0), 5)

        snap.session_energy_wh = round(self.session_energy_wh, 5)
        snap.session_duration_sec = max(0.0, now - self.session_start_ts)

        if self.storage is not None:
            self.storage.record_snapshot(
                snapshot=snap,
                delta_wh=delta_wh,
                cpu_wh=cpu_wh,
                gpu_wh=gpu_wh,
                device_deltas=device_deltas,
            )

        return snap


__all__ = [
    "BasePlatformCollector",
    "LinuxPowerCollector",
    "MacOSPowerCollector",
    "WindowsPowerCollector",
    "PowerEngine",
    "create_platform_collector",
]
