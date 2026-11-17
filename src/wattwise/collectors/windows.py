"""Windows 10/11 (x64 & ARM64) hardware power collector (WMI BatteryStatus, EMI PowerMeter, LHM, NVML)."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import time
from typing import Any, Optional

import psutil

from wattwise.collectors.base import (
    BasePlatformCollector,
    infer_cpu_tdp_watts,
    model_cpu_watts,
    query_nvidia_gpus,
    run_cmd_quiet,
)
from wattwise.models import BatteryTelemetry, HardwareComponent, PowerSnapshot


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


class WindowsPowerCollector(BasePlatformCollector):
    """Collects power telemetry on Windows 10/11 (Intel, AMD, and Snapdragon ARM64)."""

    _PS_PROBE_SCRIPT = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$b=Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus | Select-Object -First 1 "
        "PowerOnline,Discharging,Charging,Voltage,RemainingCapacity,DischargeRate,ChargeRate;"
        "$f=Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity | Select-Object -First 1 FullChargedCapacity;"
        "$m=Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness | Select-Object -First 1 CurrentBrightness;"
        "$emi=Get-CimInstance -ClassName Win32_PerfFormattedData_Counters_PowerMeter | "
        "Where-Object {$_.Name -eq '_Total'} | Select-Object -First 1 Power;"
        "$lhm=Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor | "
        "Where-Object {$_.SensorType -eq 'Power'} | Select-Object Name,Value;"
        "@{bat=$b;full=$f;mon=$m;emi=$emi;lhm=$lhm} | ConvertTo-Json -Compress -Depth 3"
    )

    def __init__(self) -> None:
        super().__init__()
        self._cpu_brand = self._detect_cpu_brand()

    def _detect_cpu_brand(self) -> str:
        if os.name == "nt":
            out = run_cmd_quiet(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
                ],
                timeout=2.5,
            )
            if out:
                return out.strip()
        return platform.processor() or "Windows Processor"

    def _win32_fallback_battery(self) -> BatteryTelemetry:
        if os.name == "nt":
            try:
                sps = _SYSTEM_POWER_STATUS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                    no_bat = bool(sps.BatteryFlag & 128)
                    if no_bat:
                        return BatteryTelemetry(present=False, status="Desktop / AC Mains", ac_connected=True)
                    ac = sps.ACLineStatus == 1
                    pct = float(sps.BatteryLifePercent) if 0 <= sps.BatteryLifePercent <= 100 else 100.0
                    charging = bool(sps.BatteryFlag & 8)
                    status = "Charging" if charging else ("AC Connected" if ac else "Discharging")
                    rem_min = (
                        round(sps.BatteryLifeTime / 60.0, 0)
                        if sps.BatteryLifeTime != 0xFFFFFFFF and sps.BatteryLifeTime > 0
                        else None
                    )
                    return BatteryTelemetry(
                        present=True,
                        status=status,
                        ac_connected=ac,
                        percent=pct,
                        time_remaining_min=rem_min,
                        model_name="Windows ACPI Battery",
                    )
            except Exception:
                pass

        sb = psutil.sensors_battery()
        if not sb:
            return BatteryTelemetry(present=False, status="Desktop / AC Mains", ac_connected=True)
        return BatteryTelemetry(
            present=True,
            status="AC Connected" if sb.power_plugged else "Discharging",
            ac_connected=bool(sb.power_plugged),
            percent=round(float(sb.percent), 1),
            time_remaining_min=round(sb.secsleft / 60.0, 0) if sb.secsleft and sb.secsleft > 0 else None,
            model_name="Windows Battery",
        )

    @staticmethod
    def parse_windows_cim_payload(raw_json: str) -> dict[str, Any]:
        """Parse JSON output from PowerShell CIM telemetry probe into normalized sensor dict."""
        res: dict[str, Any] = {
            "battery": None,
            "emi_watts": None,
            "brightness_pct": None,
            "lhm_cpu_watts": None,
            "lhm_gpu_watts": None,
            "notes": [],
        }
        try:
            data = json.loads(raw_json)
        except Exception:
            return res

        if not isinstance(data, dict):
            return res

        # Brightness
        mon = data.get("mon")
        if isinstance(mon, dict) and mon.get("CurrentBrightness") is not None:
            try:
                res["brightness_pct"] = float(mon["CurrentBrightness"])
            except (TypeError, ValueError):
                pass

        # Windows EMI (Energy Meter Interface)
        emi = data.get("emi")
        if isinstance(emi, dict) and emi.get("Power") is not None:
            try:
                emi_mw = float(emi["Power"])
                if 500 <= emi_mw <= 1_500_000:
                    res["emi_watts"] = round(emi_mw / 1000.0, 2)
                    res["notes"].append(f"Windows EMI PowerMeter: {res['emi_watts']:.2f}W")
            except (TypeError, ValueError):
                pass

        # LibreHardwareMonitor Power sensors (if user runs LHM)
        lhm = data.get("lhm")
        if isinstance(lhm, dict):
            lhm = [lhm]
        if isinstance(lhm, list):
            for item in lhm:
                if not isinstance(item, dict):
                    continue
                sname = str(item.get("Name") or "").lower()
                val = item.get("Value")
                if val is None:
                    continue
                try:
                    w = float(val)
                except (TypeError, ValueError):
                    continue
                if w <= 0:
                    continue
                if "cpu package" in sname or "package" in sname:
                    res["lhm_cpu_watts"] = round(w, 2)
                    res["notes"].append(f"LibreHardwareMonitor CPU Package: {w:.2f}W")
                elif "gpu" in sname and ("package" in sname or "total" in sname or "power" in sname):
                    res["lhm_gpu_watts"] = round(w, 2)

        # WMI BatteryStatus
        bat = data.get("bat")
        if isinstance(bat, dict) and bat:
            ac = bool(bat.get("PowerOnline", False))
            discharging = bool(bat.get("Discharging", False))
            charging = bool(bat.get("Charging", False))
            rem_mwh = float(bat.get("RemainingCapacity") or 0.0)
            full_obj = data.get("full")
            full_mwh = (
                float(full_obj.get("FullChargedCapacity") or 0.0)
                if isinstance(full_obj, dict)
                else 0.0
            )
            volt_mv = float(bat.get("Voltage") or 0.0)
            dis_mw = float(bat.get("DischargeRate") or 0.0)
            chg_mw = float(bat.get("ChargeRate") or 0.0)

            rate_w: Optional[float] = None
            if discharging and 200 <= dis_mw <= 350_000:
                rate_w = round(dis_mw / 1000.0, 2)
            elif charging and 200 <= chg_mw <= 350_000:
                rate_w = round(chg_mw / 1000.0, 2)

            pct = round((rem_mwh / full_mwh) * 100.0, 1) if full_mwh > 0 else 100.0
            status = "Charging" if charging else ("Discharging" if discharging else ("AC Pass-Through" if ac else "Unknown"))

            rem_min: Optional[float] = None
            if rate_w and rate_w > 0.5:
                if discharging and rem_mwh > 0:
                    rem_min = round(((rem_mwh / 1000.0) / rate_w) * 60.0, 0)
                elif charging and full_mwh > rem_mwh:
                    rem_min = round((((full_mwh - rem_mwh) / 1000.0) / rate_w) * 60.0, 0)

            res["battery"] = BatteryTelemetry(
                present=True,
                status=status,
                ac_connected=ac,
                percent=min(100.0, max(0.0, pct)),
                energy_now_wh=round(rem_mwh / 1000.0, 2) if rem_mwh > 0 else None,
                energy_full_wh=round(full_mwh / 1000.0, 2) if full_mwh > 0 else None,
                voltage_v=round(volt_mv / 1000.0, 2) if volt_mv > 0 else None,
                power_watts=rate_w,
                time_remaining_min=rem_min,
                model_name="Windows WMI Battery",
            )
        return res

    def collect(self) -> PowerSnapshot:
        now_ts = time.time()
        disk_mbps, net_mbps = self._sample_io_rates(now_ts)

        raw_cim = (
            run_cmd_quiet(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", self._PS_PROBE_SCRIPT],
                timeout=2.2,
            )
            if os.name == "nt"
            else None
        )
        parsed = self.parse_windows_cim_payload(raw_cim) if raw_cim else {
            "battery": None,
            "emi_watts": None,
            "brightness_pct": None,
            "lhm_cpu_watts": None,
            "lhm_gpu_watts": None,
            "notes": [],
        }

        battery: BatteryTelemetry = parsed["battery"] or self._win32_fallback_battery()
        notes: list[str] = list(parsed["notes"])
        is_laptop = battery.present

        cpu_util = psutil.cpu_percent(interval=None)
        freq = None
        try:
            freq = psutil.cpu_freq()
        except Exception:
            pass
        logical_cores = psutil.cpu_count(logical=True) or 8
        tdp_w = infer_cpu_tdp_watts(self._cpu_brand, logical_cores, is_laptop=is_laptop)

        components: list[HardwareComponent] = []

        # 1. CPU
        if parsed["lhm_cpu_watts"] is not None:
            cpu_w = float(parsed["lhm_cpu_watts"])
            cpu_direct = True
            cpu_src = "LibreHardwareMonitor WMI"
        else:
            cpu_w = model_cpu_watts(
                tdp_watts=tdp_w,
                util_pct=cpu_util,
                freq_cur_mhz=freq.current if freq else None,
                freq_min_mhz=freq.min if freq else None,
                freq_max_mhz=freq.max if freq else None,
            )
            cpu_direct = False
            cpu_src = f"Windows DVFS + TDP ({tdp_w:.0f}W)"

        cpu_comp = HardwareComponent(
            device_id="win_cpu",
            name=self._cpu_brand,
            category="cpu",
            watts=cpu_w,
            sensor_source=cpu_src,
            is_direct_sensor=cpu_direct,
            utilization_pct=round(cpu_util, 1),
            extra_info=f"{freq.current:.0f} MHz" if (freq and freq.current) else "",
        )
        components.append(cpu_comp)

        # 2. GPU
        nv_gpus, gpu_pid_scores = query_nvidia_gpus()
        if nv_gpus:
            for g in nv_gpus:
                components.append(
                    HardwareComponent(
                        device_id=f"win_gpu_{g.index}",
                        name=g.name,
                        category="gpu",
                        watts=round(g.watts, 2),
                        sensor_source="NVIDIA NVML / SMI (Direct)",
                        is_direct_sensor=True,
                        utilization_pct=g.util_pct,
                        temperature_c=g.temp_c,
                    )
                )
        elif parsed["lhm_gpu_watts"] is not None:
            components.append(
                HardwareComponent(
                    device_id="win_gpu_lhm",
                    name="Windows Graphics Processor",
                    category="gpu",
                    watts=float(parsed["lhm_gpu_watts"]),
                    sensor_source="LibreHardwareMonitor WMI",
                    is_direct_sensor=True,
                )
            )
        else:
            igpu_w = round(0.8 + (tdp_w * 0.16) * ((cpu_util / 100.0) ** 0.9), 2)
            components.append(
                HardwareComponent(
                    device_id="win_igpu",
                    name="Integrated Graphics",
                    category="gpu",
                    watts=igpu_w,
                    sensor_source="iGPU Estimate",
                    is_direct_sensor=False,
                )
            )

        # 3. Display
        bpct = parsed["brightness_pct"]
        if bpct is not None:
            ratio = max(0.0, min(1.0, bpct / 100.0))
            disp_w = round(1.2 + 5.0 * (ratio ** 1.25), 2)
            disp_name = f"Built-in Display ({bpct:.0f}% Brightness)"
            disp_src = "WmiMonitorBrightness"
        else:
            disp_w = 3.2 if is_laptop else 1.5
            disp_name = "Integrated Display" if is_laptop else "Display Output"
            disp_src = "Display Estimate"
        components.append(
            HardwareComponent(
                device_id="win_display",
                name=disp_name,
                category="display",
                watts=disp_w,
                sensor_source=disp_src,
                is_direct_sensor=False,
                utilization_pct=bpct,
            )
        )

        # 4. RAM, Storage, Network
        vm = psutil.virtual_memory()
        ram_gb = vm.total / (1024.0 ** 3)
        ram_w = round(max(1.0, (ram_gb / 8.0) * (0.55 + 0.45 * (vm.percent / 100.0))), 2)
        components.append(
            HardwareComponent(
                device_id="win_ram",
                name=f"System Memory ({ram_gb:.0f} GB RAM)",
                category="memory",
                watts=ram_w,
                sensor_source="DDR Power Model",
                is_direct_sensor=False,
                utilization_pct=round(vm.percent, 1),
            )
        )

        storage_active = min(4.8, (disk_mbps / 450.0) * 3.8)
        storage_w = round(0.75 + storage_active, 2)
        components.append(
            HardwareComponent(
                device_id="win_storage",
                name="NVMe / Disk Storage",
                category="storage",
                watts=storage_w,
                sensor_source="Disk I/O Model",
                is_direct_sensor=False,
                extra_info=f"{disk_mbps:.1f} MB/s",
            )
        )

        net_w = round(0.9 + min(2.4, (net_mbps / 25.0) * 1.8) + (1.5 if is_laptop else 4.8), 2)
        components.append(
            HardwareComponent(
                device_id="win_net",
                name="Network, USB & Motherboard",
                category="network",
                watts=net_w,
                sensor_source="NIC + Board Model",
                is_direct_sensor=False,
                extra_info=f"{net_mbps:.2f} MB/s",
            )
        )

        # Total power reconciliation
        emi_w = parsed["emi_watts"]
        if emi_w is not None and emi_w >= 2.0:
            total_watts = float(emi_w)
            sensor_mode = "direct"
            primary_source = "Windows Energy Meter Interface (EMI)"
        elif (
            battery.present
            and not battery.ac_connected
            and battery.power_watts is not None
            and battery.power_watts >= 1.5
        ):
            total_watts = battery.power_watts
            sensor_mode = "direct"
            primary_source = "WMI BatteryStatus DischargeRate"
            direct_sum = sum(c.watts for c in components if c.is_direct_sensor)
            modeled = [c for c in components if not c.is_direct_sensor]
            modeled_sum = sum(c.watts for c in modeled)
            remaining = max(0.5, total_watts - direct_sum)
            if modeled_sum > 0:
                scale = remaining / modeled_sum
                for c in modeled:
                    c.watts = round(c.watts * scale, 2)
        else:
            total_watts = round(sum(c.watts for c in components), 2)
            any_direct = any(c.is_direct_sensor for c in components)
            sensor_mode = "hybrid" if any_direct else "estimated"
            primary_source = (
                "Direct GPU/WMI + Calibrated Host"
                if any_direct
                else "Calibrated Windows Physics Model"
            )

        gpu_total_w = sum(c.watts for c in components if c.category == "gpu")
        processes = self._proc_tracker.sample_processes(
            now_ts=now_ts,
            cpu_total_watts=cpu_comp.watts,
            gpu_total_watts=gpu_total_w,
            storage_active_watts=storage_active,
            gpu_pid_scores=gpu_pid_scores,
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
