"""Cross-platform collector tests covering Linux sysfs/RAPL, macOS Apple Silicon & Intel, and Windows WMI/EMI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import time

from wattwise.collectors import PowerEngine
from wattwise.collectors.linux import LinuxPowerCollector
from wattwise.collectors.macos import MacOSPowerCollector
from wattwise.collectors.windows import WindowsPowerCollector


def test_macos_apple_silicon_telemetry_parsing() -> None:
    """Verify Apple Silicon M-series AppleSmartBattery TelemetryData direct wall power parsing."""
    sample_plist = [
        {
            "BatteryInstalled": True,
            "ExternalConnected": True,
            "IsCharging": False,
            "FullyCharged": True,
            "CurrentCapacity": 100,
            "MaxCapacity": 100,
            "AppleRawCurrentCapacity": 4520,
            "AppleRawMaxCapacity": 4550,
            "DesignCapacity": 4600,
            "Voltage": 12450,
            "InstantAmperage": 0,
            "CycleCount": 58,
            "DeviceName": "bq40z651",
            "AdapterDetails": {"Watts": 67},
            "TelemetryData": {"SystemLoad": 18650, "SystemPowerIn": 18900},
        }
    ]
    raw = plistlib.dumps(sample_plist)
    bat, sys_watts, notes = MacOSPowerCollector.parse_ioreg_smart_battery(raw)

    assert bat.present is True
    assert bat.ac_connected is True
    assert bat.percent == 100.0
    assert bat.cycle_count == 58
    assert bat.adapter_watts == 67.0
    assert sys_watts == 18.65
    assert any("TelemetryData" in n for n in notes)


def test_macos_intel_discharging_twos_complement() -> None:
    """Verify Intel Mac unsigned 64-bit negative InstantAmperage discharging calculation."""
    neg_1500_ma = (1 << 64) - 1500
    sample_plist = [
        {
            "BatteryInstalled": True,
            "ExternalConnected": False,
            "IsCharging": False,
            "FullyCharged": False,
            "CurrentCapacity": 64,
            "MaxCapacity": 100,
            "Voltage": 11400,
            "InstantAmperage": neg_1500_ma,
            "TimeRemaining": 195,
            "CycleCount": 210,
        }
    ]
    raw = plistlib.dumps(sample_plist)
    bat, sys_watts, _ = MacOSPowerCollector.parse_ioreg_smart_battery(raw)

    assert bat.present is True
    assert bat.ac_connected is False
    assert bat.status == "Discharging"
    # 1.5 A * 11.4 V = 17.1 W
    assert sys_watts == 17.1
    assert bat.power_watts == 17.1
    assert bat.time_remaining_min == 195.0


def test_windows_cim_wmi_and_emi_parsing() -> None:
    """Verify Windows WMI BatteryStatus, EMI PowerMeter, Brightness, and LibreHardwareMonitor parsing."""
    payload = {
        "bat": {
            "PowerOnline": False,
            "Discharging": True,
            "Charging": False,
            "Voltage": 15200,
            "RemainingCapacity": 42000,
            "DischargeRate": 24800,
            "ChargeRate": 0,
        },
        "full": {"FullChargedCapacity": 56000},
        "mon": {"CurrentBrightness": 70},
        "emi": {"Power": 25100},
        "lhm": [{"Name": "CPU Package", "Value": 13.4}, {"Name": "GPU Power", "Value": 6.2}],
    }
    res = WindowsPowerCollector.parse_windows_cim_payload(json.dumps(payload))

    assert res["emi_watts"] == 25.1
    assert res["brightness_pct"] == 70.0
    assert res["lhm_cpu_watts"] == 13.4
    assert res["lhm_gpu_watts"] == 6.2
    bat = res["battery"]
    assert bat is not None
    assert bat.status == "Discharging"
    assert bat.percent == 75.0
    assert bat.power_watts == 24.8


def test_linux_synthetic_sysfs_rapl_and_battery(tmp_path: Path) -> None:
    """Verify Linux collector reading synthetic sysfs RAPL energy_uj deltas and battery discharge."""
    sysfs = tmp_path / "sys"
    procfs = tmp_path / "proc"
    procfs.mkdir(parents=True)
    (procfs / "cpuinfo").write_text("model name\t: AMD Ryzen 7 7840HS\n", encoding="utf-8")

    bat0 = sysfs / "class" / "power_supply" / "BAT0"
    bat0.mkdir(parents=True)
    (bat0 / "type").write_text("Battery\n")
    (bat0 / "status").write_text("Discharging\n")
    (bat0 / "capacity").write_text("80\n")
    (bat0 / "energy_now").write_text("48000000\n")
    (bat0 / "energy_full").write_text("60000000\n")
    (bat0 / "energy_full_design").write_text("60000000\n")
    (bat0 / "power_now").write_text("22500000\n")  # 22.5 W total battery discharge
    (bat0 / "voltage_now").write_text("15400000\n")

    ac0 = sysfs / "class" / "power_supply" / "AC0"
    ac0.mkdir(parents=True)
    (ac0 / "type").write_text("Mains\n")
    (ac0 / "online").write_text("0\n")

    # Windows NTFS forbids ':' in directory names; use '_' on Windows hosts
    rapl_dirname = "intel-rapl_0" if os.name == "nt" else "intel-rapl:0"
    rapl = sysfs / "class" / "powercap" / rapl_dirname
    rapl.mkdir(parents=True)
    (rapl / "name").write_text("package-0\n")
    (rapl / "energy_uj").write_text("10000000\n")
    (rapl / "max_energy_range_uj").write_text("262143328850\n")

    bl = sysfs / "class" / "backlight" / "amdgpu_bl0"
    bl.mkdir(parents=True)
    (bl / "brightness").write_text("128\n")
    (bl / "max_brightness").write_text("255\n")

    col = LinuxPowerCollector(sysfs_root=sysfs, proc_root=procfs)
    _first = col.collect()
    time.sleep(0.12)
    # Add 1.2 Joules (1,200,000 uJ) over ~0.12s -> ~10W CPU direct RAPL
    (rapl / "energy_uj").write_text("11200000\n")
    second = col.collect()

    assert second.sensor_mode == "direct"
    assert second.total_watts == 22.5
    cpu_c = next(c for c in second.components if c.category == "cpu")
    assert cpu_c.is_direct_sensor is True
    assert cpu_c.watts > 2.0


def test_live_host_power_engine_integration() -> None:
    """Verify live host telemetry collection and Wh integration."""
    engine = PowerEngine()
    s1 = engine.sample()
    time.sleep(0.25)
    s2 = engine.sample()

    assert s1.total_watts > 0.5
    assert s2.total_watts > 0.5
    assert len(s2.components) >= 4
    assert s2.session_energy_wh > 0.0
