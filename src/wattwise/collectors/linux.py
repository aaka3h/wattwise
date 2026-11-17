"""Linux hardware power collector (RAPL, sysfs power_supply, hwmon, backlight, NVIDIA/AMD/Intel GPU)."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

import psutil

from wattwise.collectors.base import (
    BasePlatformCollector,
    infer_cpu_tdp_watts,
    model_cpu_watts,
    query_nvidia_gpus,
)
from wattwise.models import BatteryTelemetry, HardwareComponent, PowerSnapshot


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_int(path: Path) -> Optional[int]:
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        return int(txt)
    except ValueError:
        return None


class LinuxPowerCollector(BasePlatformCollector):
    """Collects power telemetry on Linux x86_64 and ARM64 (including Asahi Linux)."""

    def __init__(self, sysfs_root: Path | str = "/sys", proc_root: Path | str = "/proc") -> None:
        super().__init__()
        self.sysfs = Path(sysfs_root)
        self.procfs = Path(proc_root)
        self._rapl_prev: dict[str, tuple[int, float]] = {}
        self._cpu_brand = self._detect_cpu_brand()

    def _detect_cpu_brand(self) -> str:
        cpuinfo = _read_text(self.procfs / "cpuinfo") or ""
        for line in cpuinfo.splitlines():
            if line.lower().startswith("model name") or line.lower().startswith("hardware"):
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    return parts[1].strip()
        return "Linux CPU"

    def _read_temperatures(self) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            temps = {}
        for chip, entries in (temps or {}).items():
            if not entries:
                continue
            valid = [float(e.current) for e in entries if e.current and e.current > 0]
            if not valid:
                continue
            if chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                out["cpu"] = max(valid)
            elif chip == "nvme":
                out["nvme"] = max(out.get("nvme", 0.0), max(valid))
            elif chip.startswith("spd") or "dimm" in chip:
                out["memory"] = max(valid)
            elif "wifi" in chip or "iwlwifi" in chip or "mt79" in chip:
                out["wifi"] = max(valid)
            elif chip == "amdgpu":
                out["amdgpu"] = max(valid)
        return out

    def _read_battery_and_ac(self) -> tuple[BatteryTelemetry, list[str]]:
        ps_dir = self.sysfs / "class" / "power_supply"
        notes: list[str] = []
        if not ps_dir.is_dir():
            return BatteryTelemetry(present=False, status="Desktop / AC Only", ac_connected=True), notes

        ac_online: Optional[bool] = None
        adapter_watts: Optional[float] = None
        bat_dirs: list[Path] = []

        for entry in sorted(ps_dir.iterdir()):
            ptype = (_read_text(entry / "type") or "").lower()
            if ptype in ("mains", "usb"):
                online = _read_int(entry / "online")
                if online == 1:
                    ac_online = True
                    v_now = _read_int(entry / "voltage_now")
                    i_max = _read_int(entry / "current_max")
                    p_max = _read_int(entry / "power_max")
                    if p_max and p_max > 0:
                        adapter_watts = p_max / 1_000_000.0
                    elif v_now and i_max and v_now > 0 and i_max > 0:
                        w = (v_now / 1_000_000.0) * (i_max / 1_000_000.0)
                        if w >= 5.0:
                            adapter_watts = round(w, 1)
                elif ac_online is None and online == 0 and ptype == "mains":
                    ac_online = False
            elif ptype == "battery":
                scope = (_read_text(entry / "scope") or "").lower()
                if scope == "device":
                    # Peripheral battery (mouse/keyboard/headset), skip as main system battery
                    continue
                bat_dirs.append(entry)

        if not bat_dirs:
            return (
                BatteryTelemetry(
                    present=False,
                    status="Desktop / AC Mains",
                    ac_connected=True,
                    percent=100.0,
                    adapter_watts=adapter_watts,
                ),
                notes,
            )

        b = bat_dirs[0]
        raw_status = _read_text(b / "status") or "Unknown"
        cap = _read_int(b / "capacity")
        cycles = _read_int(b / "cycle_count")
        v_uv = _read_int(b / "voltage_now")
        voltage_v = round(v_uv / 1_000_000.0, 2) if v_uv and v_uv > 0 else None

        # Energy in uWh (or convert uAh * uV)
        e_now_uwh = _read_int(b / "energy_now")
        e_full_uwh = _read_int(b / "energy_full")
        e_design_uwh = _read_int(b / "energy_full_design")

        if e_now_uwh is None and voltage_v:
            c_now = _read_int(b / "charge_now")
            c_full = _read_int(b / "charge_full")
            c_design = _read_int(b / "charge_full_design")
            if c_now is not None:
                e_now_uwh = int(c_now * voltage_v)
            if c_full is not None:
                e_full_uwh = int(c_full * voltage_v)
            if c_design is not None:
                e_design_uwh = int(c_design * voltage_v)

        e_now_wh = round(e_now_uwh / 1_000_000.0, 2) if e_now_uwh is not None else None
        e_full_wh = round(e_full_uwh / 1_000_000.0, 2) if e_full_uwh is not None else None
        e_design_wh = round(e_design_uwh / 1_000_000.0, 2) if e_design_uwh is not None else None

        pct = float(cap) if cap is not None else (
            round((e_now_wh / e_full_wh) * 100.0, 1) if (e_now_wh and e_full_wh and e_full_wh > 0) else 0.0
        )
        health_pct = (
            round(min(105.0, (e_full_wh / e_design_wh) * 100.0), 1)
            if (e_full_wh and e_design_wh and e_design_wh > 0)
            else None
        )

        p_uw = _read_int(b / "power_now")
        if p_uw is None and v_uv:
            i_ua = _read_int(b / "current_now")
            if i_ua is not None:
                p_uw = int((abs(i_ua) / 1_000_000.0) * v_uv)
        bat_watts = round(abs(p_uw) / 1_000_000.0, 2) if p_uw is not None else None

        if ac_online is None:
            ac_online = raw_status.lower() in ("charging", "full", "not charging")

        display_status = raw_status
        if raw_status.lower() == "not charging" and ac_online:
            display_status = "AC Pass-Through (Conservation)"

        rem_min: Optional[float] = None
        if bat_watts and bat_watts > 0.5:
            if raw_status.lower() == "discharging" and e_now_wh:
                rem_min = round((e_now_wh / bat_watts) * 60.0, 0)
            elif raw_status.lower() == "charging" and e_now_wh is not None and e_full_wh is not None:
                rem_min = round((max(0.0, e_full_wh - e_now_wh) / bat_watts) * 60.0, 0)

        mfr = _read_text(b / "manufacturer") or ""
        mdl = _read_text(b / "model_name") or b.name
        tech = _read_text(b / "technology") or ""
        full_model = f"{mfr} {mdl}".strip()

        notes.append(f"Battery sysfs: {b.name} ({display_status}, {pct:.0f}%)")
        return (
            BatteryTelemetry(
                present=True,
                status=display_status,
                ac_connected=bool(ac_online),
                percent=pct,
                energy_now_wh=e_now_wh,
                energy_full_wh=e_full_wh,
                energy_design_wh=e_design_wh,
                health_pct=health_pct,
                voltage_v=voltage_v,
                power_watts=bat_watts,
                cycle_count=cycles,
                time_remaining_min=rem_min,
                model_name=full_model,
                technology=tech,
                adapter_watts=adapter_watts,
            ),
            notes,
        )

    def _read_rapl_domain(self, domain_dir: Path, now_ts: float) -> tuple[Optional[float], Optional[float], bool]:
        """Return (live_watts, max_tdp_watts, permission_denied) for a RAPL powercap directory."""
        tdp_uw = _read_int(domain_dir / "constraint_0_max_power_uw")
        if not tdp_uw or tdp_uw <= 0:
            tdp_uw = _read_int(domain_dir / "constraint_0_power_limit_uw")
        tdp_w = (tdp_uw / 1_000_000.0) if (tdp_uw and tdp_uw > 0) else None

        e_path = domain_dir / "energy_uj"
        if not e_path.exists():
            return None, tdp_w, False

        try:
            cur_uj = int(e_path.read_text(encoding="utf-8").strip())
        except PermissionError:
            return None, tdp_w, True
        except (OSError, ValueError):
            return None, tdp_w, False

        key = str(domain_dir)
        prev = self._rapl_prev.get(key)
        self._rapl_prev[key] = (cur_uj, now_ts)
        if prev is None:
            return None, tdp_w, False

        prev_uj, prev_ts = prev
        dt_sec = now_ts - prev_ts
        if dt_sec < 0.05 or dt_sec > 30.0:
            return None, tdp_w, False

        delta_uj = cur_uj - prev_uj
        if delta_uj < 0:
            max_range = _read_int(domain_dir / "max_energy_range_uj") or 262143328850
            delta_uj += max_range

        watts = (delta_uj / 1_000_000.0) / dt_sec
        if 0.0 <= watts <= 600.0:
            return round(watts, 2), tdp_w, False
        return None, tdp_w, False

    def _read_cpu_component(
        self, now_ts: float, is_laptop: bool, cpu_temp: Optional[float], notes: list[str]
    ) -> tuple[HardwareComponent, Optional[float]]:
        """Return (cpu_component, optional_psys_platform_watts)."""
        cpu_util = psutil.cpu_percent(interval=None)
        freq = None
        try:
            freq = psutil.cpu_freq()
        except Exception:
            pass

        rapl_root = self.sysfs / "class" / "powercap"
        pkg_watts: Optional[float] = None
        psys_watts: Optional[float] = None
        rapl_tdp: Optional[float] = None
        perm_denied = False

        if rapl_root.is_dir():
            for entry in sorted(rapl_root.iterdir()):
                if not entry.name.startswith("intel-rapl:"):
                    continue
                dname = (_read_text(entry / "name") or "").lower()
                if dname.startswith("package"):
                    w, tdp, denied = self._read_rapl_domain(entry, now_ts)
                    if tdp and not rapl_tdp:
                        rapl_tdp = tdp
                    if denied:
                        perm_denied = True
                    if w is not None:
                        pkg_watts = (pkg_watts or 0.0) + w
                elif dname == "psys":
                    w, _, _ = self._read_rapl_domain(entry, now_ts)
                    if w is not None and w > 1.0:
                        psys_watts = w

        # Fallback check for AMD / hwmon CPU power1_input
        if pkg_watts is None:
            hwmon_root = self.sysfs / "class" / "hwmon"
            if hwmon_root.is_dir():
                for hw in hwmon_root.iterdir():
                    hname = (_read_text(hw / "name") or "").lower()
                    if hname in ("zenpower", "amd_energy", "k10temp"):
                        p_uw = _read_int(hw / "power1_input") or _read_int(hw / "power1_average")
                        if p_uw and p_uw > 0:
                            pkg_watts = round(p_uw / 1_000_000.0, 2)
                            notes.append(f"CPU sensor: hwmon/{hname} direct power")
                            break

        freq_str = f"{freq.current:.0f} MHz" if (freq and freq.current) else ""

        if pkg_watts is not None:
            notes.append("CPU power: Direct Linux RAPL energy counter")
            comp = HardwareComponent(
                device_id="cpu_pkg",
                name=self._cpu_brand,
                category="cpu",
                watts=pkg_watts,
                sensor_source="Linux RAPL (Direct)",
                is_direct_sensor=True,
                utilization_pct=round(cpu_util, 1),
                temperature_c=cpu_temp,
                extra_info=freq_str,
            )
            return comp, psys_watts

        logical_cores = psutil.cpu_count(logical=True) or 4
        tdp_w = rapl_tdp if (rapl_tdp and 5.0 <= rapl_tdp <= 250.0) else infer_cpu_tdp_watts(
            self._cpu_brand, logical_cores, is_laptop=is_laptop
        )
        est_w = model_cpu_watts(
            tdp_watts=tdp_w,
            util_pct=cpu_util,
            freq_cur_mhz=freq.current if freq else None,
            freq_min_mhz=freq.min if freq else None,
            freq_max_mhz=freq.max if freq else None,
        )
        if perm_denied:
            notes.append(
                f"RAPL energy_uj is root-restricted (0400); using RAPL TDP ({tdp_w:.0f}W) + DVFS model"
            )
            src = f"RAPL TDP ({tdp_w:.0f}W) + DVFS"
        else:
            src = f"Calibrated TDP ({tdp_w:.0f}W)"

        comp = HardwareComponent(
            device_id="cpu_pkg",
            name=self._cpu_brand,
            category="cpu",
            watts=est_w,
            sensor_source=src,
            is_direct_sensor=False,
            utilization_pct=round(cpu_util, 1),
            temperature_c=cpu_temp,
            extra_info=freq_str,
        )
        return comp, psys_watts

    def _read_drm_gpus(
        self, existing_names: list[str], temps: dict[str, float], notes: list[str]
    ) -> list[HardwareComponent]:
        """Read AMD (amdgpu) or Intel (i915/xe) GPU power via /sys/class/drm/card*/device/hwmon."""
        drm_root = self.sysfs / "class" / "drm"
        comps: list[HardwareComponent] = []
        if not drm_root.is_dir():
            return comps

        seen_hwmon: set[str] = set()
        for card in sorted(drm_root.glob("card[0-9]*")):
            if "-" in card.name:
                continue
            hw_root = card / "device" / "hwmon"
            if not hw_root.is_dir():
                continue
            for hw in hw_root.iterdir():
                real = str(hw.resolve())
                if real in seen_hwmon:
                    continue
                seen_hwmon.add(real)
                hname = (_read_text(hw / "name") or "").lower()
                p_uw = _read_int(hw / "power1_average") or _read_int(hw / "power1_input")
                if p_uw is not None and p_uw > 0:
                    watts = round(p_uw / 1_000_000.0, 2)
                    label = "AMD Radeon GPU" if "amdgpu" in hname else f"DRM GPU ({hname or card.name})"
                    if any(label.lower() in n.lower() for n in existing_names):
                        continue
                    t_mk = _read_int(hw / "temp1_input")
                    t_c = round(t_mk / 1000.0, 1) if t_mk and t_mk > 0 else temps.get("amdgpu")
                    notes.append(f"DRM GPU sensor: {card.name}/{hname} ({watts:.2f}W)")
                    comps.append(
                        HardwareComponent(
                            device_id=f"gpu_{card.name}",
                            name=label,
                            category="gpu",
                            watts=watts,
                            sensor_source=f"sysfs hwmon ({hname})",
                            is_direct_sensor=True,
                            temperature_c=t_c,
                        )
                    )
        return comps

    def _read_display_component(self, is_laptop: bool, notes: list[str]) -> HardwareComponent:
        bl_root = self.sysfs / "class" / "backlight"
        if bl_root.is_dir():
            for bl in sorted(bl_root.iterdir()):
                cur = _read_int(bl / "brightness")
                mx = _read_int(bl / "max_brightness")
                if cur is not None and mx and mx > 0:
                    ratio = max(0.0, min(1.0, cur / mx))
                    pct = round(ratio * 100.0, 0)
                    # Typical laptop IPS/OLED panel: ~1.1W panel controller + up to 5.2W at 100% brightness
                    watts = round(1.15 + 5.1 * (ratio ** 1.25), 2)
                    notes.append(f"Backlight sysfs: {bl.name} ({pct:.0f}%)")
                    return HardwareComponent(
                        device_id="display_panel",
                        name=f"Built-in Display ({pct:.0f}% Brightness)",
                        category="display",
                        watts=watts,
                        sensor_source=f"backlight/{bl.name}",
                        is_direct_sensor=False,
                        utilization_pct=pct,
                        extra_info=f"{cur}/{mx} level",
                    )

        if is_laptop:
            return HardwareComponent(
                device_id="display_panel",
                name="Integrated Display",
                category="display",
                watts=3.2,
                sensor_source="Panel Estimate",
                is_direct_sensor=False,
            )
        return HardwareComponent(
            device_id="display_if",
            name="Display Output Interface",
            category="display",
            watts=1.5,
            sensor_source="Display I/O Estimate",
            is_direct_sensor=False,
        )

    def collect(self) -> PowerSnapshot:
        now_ts = time.time()
        temps = self._read_temperatures()
        battery, notes = self._read_battery_and_ac()
        is_laptop = battery.present
        disk_mbps, net_mbps = self._sample_io_rates(now_ts)

        components: list[HardwareComponent] = []

        # 1. CPU
        cpu_comp, psys_watts = self._read_cpu_component(now_ts, is_laptop, temps.get("cpu"), notes)
        components.append(cpu_comp)

        # 2. GPUs (NVIDIA + DRM AMD/Intel)
        nv_gpus, gpu_pid_scores = query_nvidia_gpus()
        for g in nv_gpus:
            notes.append(f"NVIDIA GPU #{g.index}: {g.name} ({g.watts:.2f}W)")
            components.append(
                HardwareComponent(
                    device_id=f"gpu_nvidia_{g.index}",
                    name=g.name,
                    category="gpu",
                    watts=round(g.watts, 2),
                    sensor_source="NVIDIA NVML / SMI (Direct)",
                    is_direct_sensor=True,
                    utilization_pct=g.util_pct,
                    temperature_c=g.temp_c,
                )
            )
        drm_gpus = self._read_drm_gpus([c.name for c in components], temps, notes)
        components.extend(drm_gpus)

        # 3. Display
        disp_comp = self._read_display_component(is_laptop, notes)
        components.append(disp_comp)

        # 4. System Memory (DRAM)
        vm = psutil.virtual_memory()
        ram_gb = vm.total / (1024.0 ** 3)
        ram_watts = round(max(1.0, (ram_gb / 8.0) * (0.55 + 0.45 * (vm.percent / 100.0))), 2)
        components.append(
            HardwareComponent(
                device_id="dram_mem",
                name=f"System Memory ({ram_gb:.0f} GB RAM)",
                category="memory",
                watts=ram_watts,
                sensor_source="DDR Power Model",
                is_direct_sensor=False,
                utilization_pct=round(vm.percent, 1),
                temperature_c=temps.get("memory"),
                extra_info=f"{vm.used / (1024.0 ** 3):.1f}/{ram_gb:.0f} GB",
            )
        )

        # 5. NVMe / Disk Storage
        storage_idle = 0.75
        storage_active = min(4.8, (disk_mbps / 450.0) * 3.8)
        storage_watts = round(storage_idle + storage_active, 2)
        components.append(
            HardwareComponent(
                device_id="storage_nvme",
                name="NVMe / SSD Storage",
                category="storage",
                watts=storage_watts,
                sensor_source="Block I/O + Thermal",
                is_direct_sensor=False,
                utilization_pct=round(min(100.0, (disk_mbps / 1500.0) * 100.0), 1),
                temperature_c=temps.get("nvme"),
                extra_info=f"{disk_mbps:.1f} MB/s",
            )
        )

        # 6. Network & Motherboard / VRM / Fans
        net_watts = round(0.85 + min(2.4, (net_mbps / 25.0) * 1.8) + (1.4 if is_laptop else 4.5), 2)
        components.append(
            HardwareComponent(
                device_id="net_chassis",
                name="Wi-Fi, USB & System Board",
                category="network",
                watts=net_watts,
                sensor_source="NIC Throughput + Board",
                is_direct_sensor=False,
                temperature_c=temps.get("wifi"),
                extra_info=f"{net_mbps:.2f} MB/s",
            )
        )

        sum_sub = sum(c.watts for c in components)

        # Reconcile total system power
        if psys_watts is not None and psys_watts >= 2.0:
            total_watts = psys_watts
            sensor_mode = "direct"
            primary_source = "Intel RAPL Platform (psys)"
            if total_watts > sum_sub + 0.3:
                components[-1].watts = round(components[-1].watts + (total_watts - sum_sub), 2)
        elif (
            battery.present
            and not battery.ac_connected
            and battery.power_watts is not None
            and battery.power_watts >= 1.5
        ):
            total_watts = battery.power_watts
            sensor_mode = "direct"
            primary_source = f"Battery Discharge ({battery.model_name or 'ACPI'})"
            # Adjust non-direct subcomponents so component sum equals measured battery discharge
            direct_sum = sum(c.watts for c in components if c.is_direct_sensor)
            modeled = [c for c in components if not c.is_direct_sensor]
            modeled_sum = sum(c.watts for c in modeled)
            remaining = max(0.5, total_watts - direct_sum)
            if modeled_sum > 0:
                scale = remaining / modeled_sum
                for c in modeled:
                    c.watts = round(c.watts * scale, 2)
        else:
            # On AC power (or battery sensor unavailable)
            if (
                battery.present
                and battery.ac_connected
                and "charging" in battery.status.lower()
                and "not charging" not in battery.status.lower()
                and battery.power_watts
                and battery.power_watts > 0.5
            ):
                components.append(
                    HardwareComponent(
                        device_id="battery_charge",
                        name="Battery Charging Draw",
                        category="battery_charge",
                        watts=round(battery.power_watts, 2),
                        sensor_source="ACPI Battery Charge",
                        is_direct_sensor=True,
                        utilization_pct=battery.percent,
                    )
                )
            total_watts = round(sum(c.watts for c in components), 2)
            any_direct = any(c.is_direct_sensor for c in components)
            sensor_mode = "hybrid" if any_direct else "estimated"
            primary_source = (
                "Direct GPU/RAPL + Calibrated Host"
                if any_direct
                else "Calibrated Hardware Physics Model"
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
