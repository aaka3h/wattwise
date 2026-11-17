"""macOS hardware power collector supporting both Apple Silicon (M1/M2/M3/M4+) and Intel Macs."""

from __future__ import annotations

import os
import platform
import plistlib
import time
from typing import Any, Optional

import psutil

from wattwise.collectors.base import (
    BasePlatformCollector,
    infer_cpu_tdp_watts,
    model_cpu_watts,
    run_cmd_quiet,
)
from wattwise.models import BatteryTelemetry, HardwareComponent, PowerSnapshot


def _signed_64(val: int) -> int:
    """Convert unsigned 64-bit IOKit integer to signed int (handles negative InstantAmperage)."""
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


class MacOSPowerCollector(BasePlatformCollector):
    """Collects power telemetry on macOS Apple Silicon (M-Series arm64) and Intel (x86_64)."""

    def __init__(self) -> None:
        super().__init__()
        self._is_apple_silicon = platform.machine().lower() in ("arm64", "aarch64")
        self._cpu_brand = self._detect_cpu_brand()
        self._p_cores, self._e_cores = self._detect_perf_levels()

    def _detect_cpu_brand(self) -> str:
        brand = run_cmd_quiet(["sysctl", "-n", "machdep.cpu.brand_string"])
        if brand:
            return brand
        return "Apple Silicon M-Series SoC" if self._is_apple_silicon else "Intel Mac CPU"

    def _detect_perf_levels(self) -> tuple[int, int]:
        if not self._is_apple_silicon:
            return (psutil.cpu_count(logical=False) or 4, 0)
        p_str = run_cmd_quiet(["sysctl", "-n", "hw.perflevel0.physicalcpu"])
        e_str = run_cmd_quiet(["sysctl", "-n", "hw.perflevel1.physicalcpu"])
        try:
            p = int(p_str) if p_str else 4
            e = int(e_str) if e_str else 4
            return p, e
        except ValueError:
            return 4, 4

    @staticmethod
    def parse_ioreg_smart_battery(plist_bytes: bytes) -> tuple[BatteryTelemetry, Optional[float], list[str]]:
        """Parse `ioreg -rw0 -c AppleSmartBattery -a` XML plist into BatteryTelemetry & system_watts."""
        notes: list[str] = []
        try:
            items = plistlib.loads(plist_bytes)
        except Exception:
            return BatteryTelemetry(present=False, status="Mac Desktop / AC", ac_connected=True), None, notes

        if not isinstance(items, list) or not items:
            return BatteryTelemetry(present=False, status="Mac Desktop / AC", ac_connected=True), None, notes

        entry: dict[str, Any] = items[0]
        installed = bool(entry.get("BatteryInstalled", True))
        if not installed:
            return BatteryTelemetry(present=False, status="Mac Desktop / AC", ac_connected=True), None, notes

        ext_connected = bool(entry.get("ExternalConnected", False))
        is_charging = bool(entry.get("IsCharging", False))
        fully_charged = bool(entry.get("FullyCharged", False))

        voltage_mv = int(entry.get("Voltage", 0) or 0)
        voltage_v = round(voltage_mv / 1000.0, 2) if voltage_mv > 0 else None

        raw_cur_mah = entry.get("AppleRawCurrentCapacity")
        raw_max_mah = entry.get("AppleRawMaxCapacity")
        design_mah = entry.get("DesignCapacity")
        cur_cap = entry.get("CurrentCapacity", 100)
        max_cap = entry.get("MaxCapacity", 100)

        if isinstance(max_cap, int) and max_cap == 100 and isinstance(cur_cap, (int, float)):
            pct = float(cur_cap)
        elif raw_cur_mah and raw_max_mah and raw_max_mah > 0:
            pct = round((float(raw_cur_mah) / float(raw_max_mah)) * 100.0, 1)
        elif max_cap and max_cap > 0:
            pct = round((float(cur_cap) / float(max_cap)) * 100.0, 1)
        else:
            pct = 100.0

        nom_v = voltage_v or 11.4
        e_now_wh = round((float(raw_cur_mah) * nom_v) / 1000.0, 2) if raw_cur_mah else None
        e_full_wh = round((float(raw_max_mah) * nom_v) / 1000.0, 2) if raw_max_mah else None
        e_design_wh = round((float(design_mah) * nom_v) / 1000.0, 2) if design_mah else None

        health_pct = None
        if raw_max_mah and design_mah and design_mah > 0:
            health_pct = round(min(105.0, (float(raw_max_mah) / float(design_mah)) * 100.0), 1)

        amp_raw = entry.get("InstantAmperage")
        if amp_raw is None:
            amp_raw = entry.get("Amperage", 0)
        amp_ma = _signed_64(int(amp_raw or 0))
        bat_watts = round((abs(amp_ma) * (voltage_mv / 1000.0)) / 1000.0, 2) if voltage_mv > 0 else None

        adapter_details = entry.get("AdapterDetails") or {}
        adapter_watts = (
            float(adapter_details["Watts"])
            if isinstance(adapter_details, dict) and adapter_details.get("Watts")
            else None
        )

        # Apple Silicon & modern Intel Mac TelemetryData exposes direct system load (mW) even on AC!
        system_watts: Optional[float] = None
        telemetry = entry.get("TelemetryData")
        if isinstance(telemetry, dict):
            sys_load_mw = telemetry.get("SystemLoad") or telemetry.get("SystemPowerIn")
            if isinstance(sys_load_mw, (int, float)) and 500 <= sys_load_mw <= 350_000:
                system_watts = round(float(sys_load_mw) / 1000.0, 2)
                notes.append(f"AppleSmartBattery TelemetryData direct load: {system_watts:.2f}W")

        if system_watts is None and not ext_connected and bat_watts and bat_watts > 0.5:
            system_watts = bat_watts
            notes.append(f"AppleSmartBattery discharge rate: {system_watts:.2f}W")

        if is_charging:
            status = "Charging"
        elif fully_charged and ext_connected:
            status = "Full (AC Connected)"
        elif ext_connected:
            status = "AC Pass-Through"
        else:
            status = "Discharging"

        time_rem = entry.get("TimeRemaining")
        rem_min = (
            float(time_rem)
            if isinstance(time_rem, (int, float)) and 0 < time_rem < 6000
            else None
        )

        cycles = int(entry["CycleCount"]) if "CycleCount" in entry else None
        model_name = str(entry.get("DeviceName") or "AppleSmartBattery")

        return (
            BatteryTelemetry(
                present=True,
                status=status,
                ac_connected=ext_connected,
                percent=pct,
                energy_now_wh=e_now_wh,
                energy_full_wh=e_full_wh,
                energy_design_wh=e_design_wh,
                health_pct=health_pct,
                voltage_v=voltage_v,
                power_watts=bat_watts,
                cycle_count=cycles,
                time_remaining_min=rem_min,
                model_name=model_name,
                technology="Li-Ion",
                adapter_watts=adapter_watts,
            ),
            system_watts,
            notes,
        )

    def _try_powermetrics(self) -> Optional[dict[str, float]]:
        """Read exact CPU/GPU/ANE mW via `powermetrics` when running as root (e.g. sudo)."""
        if os.geteuid() != 0:
            return None
        samplers = "cpu_power,gpu_power,ane_power" if self._is_apple_silicon else "cpu_power,gpu_power"
        out = run_cmd_quiet(
            ["powermetrics", "--samplers", samplers, "-n", "1", "-i", "250", "-f", "plist"],
            timeout=1.5,
        )
        if not out:
            return None
        try:
            pl = plistlib.loads(out.encode("utf-8"))
            proc = pl.get("processor", {})
            res: dict[str, float] = {}
            if "cpu_power" in proc:
                res["cpu"] = round(float(proc["cpu_power"]) / 1000.0, 2)
            elif "package_watts" in proc:
                res["cpu"] = round(float(proc["package_watts"]), 2)
            if "gpu_power" in proc:
                res["gpu"] = round(float(proc["gpu_power"]) / 1000.0, 2)
            if "ane_power" in proc:
                res["ane"] = round(float(proc["ane_power"]) / 1000.0, 2)
            if "combined_power" in proc:
                res["combined"] = round(float(proc["combined_power"]) / 1000.0, 2)
            return res if res else None
        except Exception:
            return None

    def collect(self) -> PowerSnapshot:
        now_ts = time.time()
        disk_mbps, net_mbps = self._sample_io_rates(now_ts)

        ioreg_raw = run_cmd_quiet(["ioreg", "-rw0", "-c", "AppleSmartBattery", "-a"], timeout=1.8)
        if ioreg_raw:
            battery, direct_sys_w, notes = self.parse_ioreg_smart_battery(ioreg_raw.encode("utf-8"))
        else:
            battery = BatteryTelemetry(present=False, status="Mac Desktop / AC", ac_connected=True)
            direct_sys_w = None
            notes = []

        pm = self._try_powermetrics()
        cpu_util = psutil.cpu_percent(interval=None)
        logical_cores = psutil.cpu_count(logical=True) or 8
        tdp_w = infer_cpu_tdp_watts(self._cpu_brand, logical_cores, is_laptop=battery.present)

        components: list[HardwareComponent] = []

        # 1. CPU (Apple Silicon P+E Cores or Intel Mac Package)
        if pm and "cpu" in pm:
            cpu_w = pm["cpu"]
            cpu_direct = True
            cpu_src = "macOS powermetrics (Direct)"
        else:
            cpu_w = model_cpu_watts(tdp_watts=tdp_w, util_pct=cpu_util)
            if self._is_apple_silicon:
                # Apple Silicon idle efficiency is exceptional (~0.6-1.5W on E-cores)
                cpu_w = round(max(0.65, cpu_w * 0.72), 2)
            cpu_direct = False
            cpu_src = (
                f"Apple Silicon ({self._p_cores}P+{self._e_cores}E) Model"
                if self._is_apple_silicon
                else f"Intel Mac TDP ({tdp_w:.0f}W) Model"
            )

        cpu_comp = HardwareComponent(
            device_id="cpu_soc",
            name=self._cpu_brand,
            category="cpu",
            watts=cpu_w,
            sensor_source=cpu_src,
            is_direct_sensor=cpu_direct,
            utilization_pct=round(cpu_util, 1),
            extra_info=f"{self._p_cores}P + {self._e_cores}E cores" if self._is_apple_silicon else f"{logical_cores} threads",
        )
        components.append(cpu_comp)

        # 2. GPU (Apple Silicon Integrated GPU or Intel/AMD Mac GPU)
        if pm and "gpu" in pm:
            gpu_w = pm["gpu"]
            gpu_direct = True
            gpu_src = "macOS powermetrics (Direct)"
        else:
            gpu_w = round(0.35 + (tdp_w * 0.22) * ((cpu_util / 100.0) ** 0.9), 2)
            gpu_direct = False
            gpu_src = "SoC GPU Activity Estimate"

        gpu_name = (
            f"{self._cpu_brand} Integrated GPU"
            if self._is_apple_silicon
            else "macOS Graphics Processor"
        )
        components.append(
            HardwareComponent(
                device_id="gpu_mac",
                name=gpu_name,
                category="gpu",
                watts=gpu_w,
                sensor_source=gpu_src,
                is_direct_sensor=gpu_direct,
            )
        )

        # 3. Apple Neural Engine (ANE) on Apple Silicon M-series
        if self._is_apple_silicon:
            ane_w = pm["ane"] if (pm and "ane" in pm) else 0.12
            components.append(
                HardwareComponent(
                    device_id="apple_ane",
                    name="Apple Neural Engine (ANE)",
                    category="ane",
                    watts=ane_w,
                    sensor_source="powermetrics" if (pm and "ane" in pm) else "Idle Baseline",
                    is_direct_sensor=bool(pm and "ane" in pm),
                )
            )

        # 4. Liquid Retina / External Display
        disp_w = 2.9 if battery.present else 1.4
        components.append(
            HardwareComponent(
                device_id="mac_display",
                name="Retina Display" if battery.present else "Display Engine",
                category="display",
                watts=disp_w,
                sensor_source="Display Estimate",
                is_direct_sensor=False,
            )
        )

        # 5. Unified Memory / RAM & NVMe SSD & Wireless
        vm = psutil.virtual_memory()
        ram_gb = vm.total / (1024.0 ** 3)
        mem_label = (
            f"Unified Memory ({ram_gb:.0f} GB LPDDR)"
            if self._is_apple_silicon
            else f"System Memory ({ram_gb:.0f} GB)"
        )
        mem_w = round(max(0.5, (ram_gb / 16.0) * (0.45 if self._is_apple_silicon else 0.9)), 2)
        components.append(
            HardwareComponent(
                device_id="mac_mem",
                name=mem_label,
                category="memory",
                watts=mem_w,
                sensor_source="Memory Model",
                is_direct_sensor=False,
                utilization_pct=round(vm.percent, 1),
            )
        )

        storage_active = min(4.0, (disk_mbps / 600.0) * 3.2)
        storage_w = round(0.45 + storage_active, 2)
        components.append(
            HardwareComponent(
                device_id="mac_ssd",
                name="Apple NVMe Storage",
                category="storage",
                watts=storage_w,
                sensor_source="Disk I/O Model",
                is_direct_sensor=False,
                extra_info=f"{disk_mbps:.1f} MB/s",
            )
        )

        net_w = round(0.75 + min(2.0, (net_mbps / 25.0) * 1.5), 2)
        components.append(
            HardwareComponent(
                device_id="mac_net",
                name="Wi-Fi, Thunderbolt & Logic Board",
                category="network",
                watts=net_w,
                sensor_source="I/O + Board Model",
                is_direct_sensor=False,
                extra_info=f"{net_mbps:.2f} MB/s",
            )
        )

        # Reconcile against direct AppleSmartBattery TelemetryData / discharge reading
        if direct_sys_w is not None and direct_sys_w >= 1.2:
            total_watts = direct_sys_w
            sensor_mode = "direct"
            primary_source = "AppleSmartBattery IOKit Telemetry"
            direct_sum = sum(c.watts for c in components if c.is_direct_sensor)
            modeled = [c for c in components if not c.is_direct_sensor]
            modeled_sum = sum(c.watts for c in modeled)
            remaining = max(0.4, total_watts - direct_sum)
            if modeled_sum > 0:
                scale = remaining / modeled_sum
                for c in modeled:
                    c.watts = round(c.watts * scale, 2)
        else:
            total_watts = round(sum(c.watts for c in components), 2)
            sensor_mode = "hybrid" if pm else "estimated"
            primary_source = (
                "macOS powermetrics + SoC Model" if pm else f"Calibrated {self._cpu_brand} Model"
            )

        processes = self._proc_tracker.sample_processes(
            now_ts=now_ts,
            cpu_total_watts=cpu_comp.watts,
            gpu_total_watts=gpu_w,
            storage_active_watts=storage_active,
        )

        return PowerSnapshot(
            timestamp=now_ts,
            platform_name=self.host_platform_banner(),
            total_watts=round(total_watts, 2),
            sensor_mode=sensor_mode,
            primary_source=primary_source,
            components=components,
            processes=processes,
            battery=battery,
            diagnostics=notes,
        )
