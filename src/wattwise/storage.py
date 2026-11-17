"""Cross-platform SQLite persistence, settings store, and CSV/JSON export."""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import platform
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from wattwise.models import HistoricalBucket, PowerSnapshot, TariffProfile
from wattwise.pricing import REGIONAL_PRESETS, energy_carbon_grams, energy_cost


def default_data_dir() -> Path:
    """Resolve OS-native application data directory (Linux, Windows, macOS)."""
    env_override = os.environ.get("WATTWISE_DATA_DIR")
    if env_override:
        p = Path(env_override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    sys_name = platform.system().lower()
    if sys_name == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        target = base / "WattWise"
    elif sys_name == "darwin":
        target = Path.home() / "Library" / "Application Support" / "WattWise"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
        target = base / "wattwise"

    target.mkdir(parents=True, exist_ok=True)
    return target


class WattWiseStorage:
    """Thread-safe local SQLite3 database for telemetry history and preferences."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else (default_data_dir() / "wattwise.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS power_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    total_watts REAL NOT NULL,
                    cpu_watts REAL NOT NULL,
                    gpu_watts REAL NOT NULL,
                    other_watts REAL NOT NULL,
                    delta_wh REAL NOT NULL,
                    cpu_wh REAL NOT NULL,
                    gpu_wh REAL NOT NULL,
                    ac_connected INTEGER NOT NULL,
                    battery_pct REAL,
                    sensor_mode TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_power_samples_ts ON power_samples(ts);

                CREATE TABLE IF NOT EXISTS daily_device_totals (
                    day_key TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    energy_wh REAL NOT NULL DEFAULT 0.0,
                    peak_watts REAL NOT NULL DEFAULT 0.0,
                    last_watts REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (day_key, device_id)
                );
                """
            )
            # Prune raw high-frequency samples older than 30 days to keep DB lightweight
            cutoff = time.time() - (30 * 86400)
            self._conn.execute("DELETE FROM power_samples WHERE ts < ?", (cutoff,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_pref(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO settings (key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, payload),
            )

    def load_pref(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except Exception:
            return default

    def save_tariff(self, profile: TariffProfile) -> None:
        self.save_pref("tariff_profile", profile.to_dict())

    def load_tariff(self) -> TariffProfile:
        raw = self.load_pref("tariff_profile")
        if isinstance(raw, dict):
            try:
                return TariffProfile.from_dict(raw)
            except Exception:
                pass
        return TariffProfile(**REGIONAL_PRESETS["us_avg"].to_dict())

    def record_snapshot(
        self,
        snapshot: PowerSnapshot,
        delta_wh: float,
        cpu_wh: float,
        gpu_wh: float,
        device_deltas: dict[str, float],
    ) -> None:
        day_key = dt.datetime.fromtimestamp(snapshot.timestamp).strftime("%Y-%m-%d")
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO power_samples (
                    ts, total_watts, cpu_watts, gpu_watts, other_watts,
                    delta_wh, cpu_wh, gpu_wh, ac_connected, battery_pct, sensor_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.timestamp,
                    snapshot.total_watts,
                    snapshot.cpu_watts,
                    snapshot.gpu_watts,
                    snapshot.other_watts,
                    max(0.0, delta_wh),
                    max(0.0, cpu_wh),
                    max(0.0, gpu_wh),
                    1 if snapshot.battery.ac_connected else 0,
                    snapshot.battery.percent if snapshot.battery.present else None,
                    snapshot.sensor_mode,
                ),
            )
            for comp in snapshot.components:
                d_wh = max(0.0, device_deltas.get(comp.device_id, 0.0))
                self._conn.execute(
                    """
                    INSERT INTO daily_device_totals (
                        day_key, device_id, device_name, category,
                        energy_wh, peak_watts, last_watts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(day_key, device_id) DO UPDATE SET
                        device_name = excluded.device_name,
                        category = excluded.category,
                        energy_wh = daily_device_totals.energy_wh + excluded.energy_wh,
                        peak_watts = MAX(daily_device_totals.peak_watts, excluded.peak_watts),
                        last_watts = excluded.last_watts
                    """,
                    (
                        day_key,
                        comp.device_id,
                        comp.name,
                        comp.category,
                        d_wh,
                        comp.watts,
                        comp.watts,
                    ),
                )

    def get_today_totals(self) -> dict[str, float]:
        now = dt.datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(delta_wh), 0.0) AS energy_wh,
                    COALESCE(SUM(cpu_wh), 0.0) AS cpu_wh,
                    COALESCE(SUM(gpu_wh), 0.0) AS gpu_wh,
                    COALESCE(AVG(total_watts), 0.0) AS avg_watts,
                    COALESCE(MAX(total_watts), 0.0) AS peak_watts,
                    COUNT(*) AS samples
                FROM power_samples
                WHERE ts >= ?
                """,
                (midnight,),
            ).fetchone()
        return {
            "energy_wh": float(row["energy_wh"]),
            "cpu_wh": float(row["cpu_wh"]),
            "gpu_wh": float(row["gpu_wh"]),
            "avg_watts": float(row["avg_watts"]),
            "peak_watts": float(row["peak_watts"]),
            "samples": float(row["samples"]),
        }

    def get_all_time_totals(self) -> dict[str, float]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(delta_wh), 0.0) AS energy_wh,
                    COALESCE(AVG(total_watts), 0.0) AS avg_watts,
                    COALESCE(MAX(total_watts), 0.0) AS peak_watts,
                    COUNT(*) AS samples
                FROM power_samples
                """
            ).fetchone()
        return {
            "energy_wh": float(row["energy_wh"]),
            "avg_watts": float(row["avg_watts"]),
            "peak_watts": float(row["peak_watts"]),
            "samples": float(row["samples"]),
        }

    def get_hourly_buckets(self, hours: int = 24) -> list[HistoricalBucket]:
        """Return contiguous hourly buckets ending at the current hour."""
        hours = max(1, min(168, hours))
        now_dt = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
        start_dt = now_dt - dt.timedelta(hours=hours - 1)
        start_ts = start_dt.timestamp()

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    CAST((ts - ?) / 3600 AS INT) AS idx,
                    AVG(total_watts) AS avg_w,
                    MAX(total_watts) AS peak_w,
                    SUM(delta_wh) AS e_wh,
                    SUM(cpu_wh) AS c_wh,
                    SUM(gpu_wh) AS g_wh,
                    COUNT(*) AS cnt
                FROM power_samples
                WHERE ts >= ?
                GROUP BY idx
                """,
                (start_ts, start_ts),
            ).fetchall()

        by_idx = {int(r["idx"]): r for r in rows if r["idx"] is not None}
        buckets: list[HistoricalBucket] = []
        for i in range(hours):
            b_dt = start_dt + dt.timedelta(hours=i)
            r = by_idx.get(i)
            buckets.append(
                HistoricalBucket(
                    bucket_label=b_dt.strftime("%H:00"),
                    bucket_start_ts=b_dt.timestamp(),
                    avg_watts=float(r["avg_w"]) if r else 0.0,
                    peak_watts=float(r["peak_w"]) if r else 0.0,
                    energy_wh=float(r["e_wh"]) if r else 0.0,
                    cpu_wh=float(r["c_wh"]) if r else 0.0,
                    gpu_wh=float(r["g_wh"]) if r else 0.0,
                    sample_count=int(r["cnt"]) if r else 0,
                )
            )
        return buckets

    def get_daily_buckets(self, days: int = 14) -> list[HistoricalBucket]:
        """Return contiguous daily buckets ending today."""
        days = max(1, min(90, days))
        today_dt = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = today_dt - dt.timedelta(days=days - 1)
        start_ts = start_dt.timestamp()

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') AS dkey,
                    AVG(total_watts) AS avg_w,
                    MAX(total_watts) AS peak_w,
                    SUM(delta_wh) AS e_wh,
                    SUM(cpu_wh) AS c_wh,
                    SUM(gpu_wh) AS g_wh,
                    COUNT(*) AS cnt
                FROM power_samples
                WHERE ts >= ?
                GROUP BY dkey
                """,
                (start_ts,),
            ).fetchall()

        by_day = {str(r["dkey"]): r for r in rows if r["dkey"]}
        buckets: list[HistoricalBucket] = []
        for i in range(days):
            d_dt = start_dt + dt.timedelta(days=i)
            dkey = d_dt.strftime("%Y-%m-%d")
            r = by_day.get(dkey)
            buckets.append(
                HistoricalBucket(
                    bucket_label=d_dt.strftime("%b %d"),
                    bucket_start_ts=d_dt.timestamp(),
                    avg_watts=float(r["avg_w"]) if r else 0.0,
                    peak_watts=float(r["peak_w"]) if r else 0.0,
                    energy_wh=float(r["e_wh"]) if r else 0.0,
                    cpu_wh=float(r["c_wh"]) if r else 0.0,
                    gpu_wh=float(r["g_wh"]) if r else 0.0,
                    sample_count=int(r["cnt"]) if r else 0,
                )
            )
        return buckets

    def export_csv(self, dest_path: Path | str, profile: TariffProfile, days: int = 30) -> int:
        """Export recorded samples with computed Cost and CO2e to CSV."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - (max(1, days) * 86400)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT ts, total_watts, cpu_watts, gpu_watts, other_watts,
                       delta_wh, ac_connected, battery_pct, sensor_mode
                FROM power_samples
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (cutoff,),
            ).fetchall()

        with dest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "iso_timestamp",
                    "total_watts",
                    "cpu_watts",
                    "gpu_watts",
                    "other_watts",
                    "energy_delta_wh",
                    f"cost_{profile.currency_code}",
                    "carbon_grams_co2e",
                    "ac_connected",
                    "battery_pct",
                    "sensor_mode",
                ]
            )
            for r in rows:
                iso = dt.datetime.fromtimestamp(float(r["ts"])).isoformat(timespec="seconds")
                d_wh = float(r["delta_wh"])
                c_val = energy_cost(d_wh, profile)
                co2_val = energy_carbon_grams(d_wh, profile)
                writer.writerow(
                    [
                        iso,
                        f"{float(r['total_watts']):.2f}",
                        f"{float(r['cpu_watts']):.2f}",
                        f"{float(r['gpu_watts']):.2f}",
                        f"{float(r['other_watts']):.2f}",
                        f"{d_wh:.6f}",
                        f"{c_val:.6f}",
                        f"{co2_val:.4f}",
                        bool(r["ac_connected"]),
                        f"{float(r['battery_pct']):.1f}" if r["battery_pct"] is not None else "",
                        r["sensor_mode"],
                    ]
                )
        return len(rows)

    def export_json(
        self,
        dest_path: Path | str,
        latest_snapshot: Optional[PowerSnapshot],
        profile: TariffProfile,
        days: int = 30,
    ) -> None:
        """Export structured summary, tariff profile, daily buckets, and current snapshot to JSON."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        daily = self.get_daily_buckets(days=days)
        hourly = self.get_hourly_buckets(hours=24)
        today = self.get_today_totals()
        payload = {
            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
            "tariff_profile": profile.to_dict(),
            "today_summary": {
                **today,
                "cost": round(energy_cost(today["energy_wh"], profile), 6),
                "carbon_grams_co2e": round(energy_carbon_grams(today["energy_wh"], profile), 4),
            },
            "latest_snapshot": latest_snapshot.to_dict() if latest_snapshot else None,
            "hourly_last_24h": [
                {
                    "hour": b.bucket_label,
                    "avg_watts": round(b.avg_watts, 2),
                    "peak_watts": round(b.peak_watts, 2),
                    "energy_wh": round(b.energy_wh, 4),
                    "cost": round(energy_cost(b.energy_wh, profile), 6),
                    "carbon_grams_co2e": round(energy_carbon_grams(b.energy_wh, profile), 4),
                }
                for b in hourly
            ],
            "daily_history": [
                {
                    "day": b.bucket_label,
                    "avg_watts": round(b.avg_watts, 2),
                    "peak_watts": round(b.peak_watts, 2),
                    "energy_wh": round(b.energy_wh, 4),
                    "cost": round(energy_cost(b.energy_wh, profile), 6),
                    "carbon_grams_co2e": round(energy_carbon_grams(b.energy_wh, profile), 4),
                }
                for b in daily
            ],
        }
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
