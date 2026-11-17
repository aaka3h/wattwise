"""Unit tests for SQLite persistence, bucket aggregation, and CSV/JSON exports."""

from __future__ import annotations

import json
from pathlib import Path
import time

from wattwise.models import BatteryTelemetry, HardwareComponent, PowerSnapshot, TariffProfile
from wattwise.storage import WattWiseStorage


def _make_snapshot(ts: float, total_w: float = 40.0) -> PowerSnapshot:
    return PowerSnapshot(
        timestamp=ts,
        platform_name="TestOS (x86_64)",
        total_watts=total_w,
        sensor_mode="direct",
        primary_source="TestSensor",
        components=[
            HardwareComponent(
                device_id="cpu0",
                name="Test CPU",
                category="cpu",
                watts=22.0,
                sensor_source="RAPL",
                is_direct_sensor=True,
            ),
            HardwareComponent(
                device_id="gpu0",
                name="Test GPU",
                category="gpu",
                watts=18.0,
                sensor_source="NVML",
                is_direct_sensor=True,
            ),
        ],
        battery=BatteryTelemetry(present=True, status="Discharging", ac_connected=False, percent=82.0),
    )


def test_storage_roundtrip_and_exports(tmp_path: Path) -> None:
    db_file = tmp_path / "test_wattwise.db"
    store = WattWiseStorage(db_path=db_file)
    try:
        custom = TariffProfile(
            region_key="germany",
            region_label="Germany",
            currency_symbol="€",
            currency_code="EUR",
            rate_per_kwh=0.37,
            carbon_g_per_kwh=350.0,
        )
        store.save_tariff(custom)
        loaded = store.load_tariff()
        assert loaded.region_key == "germany"
        assert loaded.currency_symbol == "€"
        assert loaded.rate_per_kwh == 0.37

        now = time.time()
        s1 = _make_snapshot(now - 2.0, 36.0)
        s2 = _make_snapshot(now, 44.0)

        store.record_snapshot(s1, delta_wh=0.02, cpu_wh=0.011, gpu_wh=0.009, device_deltas={"cpu0": 0.011, "gpu0": 0.009})
        store.record_snapshot(s2, delta_wh=0.025, cpu_wh=0.014, gpu_wh=0.011, device_deltas={"cpu0": 0.014, "gpu0": 0.011})

        today = store.get_today_totals()
        assert today["samples"] == 2.0
        assert abs(today["energy_wh"] - 0.045) < 1e-6
        assert today["peak_watts"] == 44.0

        hourly = store.get_hourly_buckets(hours=24)
        assert len(hourly) == 24
        assert sum(b.energy_wh for b in hourly) >= 0.044

        daily = store.get_daily_buckets(days=7)
        assert len(daily) == 7
        assert abs(daily[-1].energy_wh - 0.045) < 1e-6

        csv_path = tmp_path / "export.csv"
        rows_written = store.export_csv(csv_path, loaded, days=7)
        assert rows_written == 2
        csv_text = csv_path.read_text(encoding="utf-8")
        assert "cost_EUR" in csv_text
        assert "carbon_grams_co2e" in csv_text

        json_path = tmp_path / "export.json"
        store.export_json(json_path, s2, loaded, days=7)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["tariff_profile"]["currency_code"] == "EUR"
        assert payload["today_summary"]["samples"] == 2.0
        assert payload["latest_snapshot"]["total_watts"] == 44.0
    finally:
        store.close()
