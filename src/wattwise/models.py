"""Core domain data models for WattWise telemetry, pricing, and carbon tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class HardwareComponent:
    """Power telemetry for an individual hardware device or subsystem."""

    device_id: str
    name: str
    category: str  # cpu, gpu, display, memory, storage, network, ane, chassis, battery_charge
    watts: float
    sensor_source: str
    is_direct_sensor: bool = False
    utilization_pct: Optional[float] = None
    temperature_c: Optional[float] = None
    energy_wh: float = 0.0
    extra_info: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessPower:
    """Estimated active power & cumulative energy attributed to an application."""

    app_name: str
    primary_pid: int
    pid_count: int
    cpu_pct: float
    gpu_pct: float
    memory_mb: float
    io_mbps: float
    watts: float
    energy_wh: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatteryTelemetry:
    """Battery & AC power supply status across Linux, Windows, and macOS."""

    present: bool = False
    status: str = "Desktop / AC Only"
    ac_connected: bool = True
    percent: float = 100.0
    energy_now_wh: Optional[float] = None
    energy_full_wh: Optional[float] = None
    energy_design_wh: Optional[float] = None
    health_pct: Optional[float] = None
    voltage_v: Optional[float] = None
    power_watts: Optional[float] = None
    cycle_count: Optional[int] = None
    time_remaining_min: Optional[float] = None
    model_name: str = ""
    technology: str = ""
    adapter_watts: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PowerSnapshot:
    """Complete point-in-time system, per-device, and per-app power reading."""

    timestamp: float
    platform_name: str
    total_watts: float
    sensor_mode: str  # "direct", "hybrid", "estimated"
    primary_source: str
    components: list[HardwareComponent] = field(default_factory=list)
    processes: list[ProcessPower] = field(default_factory=list)
    battery: BatteryTelemetry = field(default_factory=BatteryTelemetry)
    session_energy_wh: float = 0.0
    session_duration_sec: float = 0.0
    diagnostics: list[str] = field(default_factory=list)

    @property
    def cpu_watts(self) -> float:
        return sum(c.watts for c in self.components if c.category == "cpu")

    @property
    def gpu_watts(self) -> float:
        return sum(c.watts for c in self.components if c.category == "gpu")

    @property
    def other_watts(self) -> float:
        return max(0.0, self.total_watts - self.cpu_watts - self.gpu_watts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "platform_name": self.platform_name,
            "total_watts": round(self.total_watts, 3),
            "sensor_mode": self.sensor_mode,
            "primary_source": self.primary_source,
            "session_energy_wh": round(self.session_energy_wh, 5),
            "session_duration_sec": round(self.session_duration_sec, 1),
            "components": [c.to_dict() for c in self.components],
            "processes": [p.to_dict() for p in self.processes],
            "battery": self.battery.to_dict(),
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class TariffProfile:
    """Electricity tariff and grid carbon intensity configuration."""

    region_key: str = "us_avg"
    region_label: str = "United States (Average)"
    currency_symbol: str = "$"
    currency_code: str = "USD"
    rate_per_kwh: float = 0.175
    carbon_g_per_kwh: float = 386.0
    daily_fixed_fee: float = 0.0
    daily_active_hours_est: float = 8.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TariffProfile":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class ImpactMetrics:
    """Computed electricity cost and carbon footprint metrics for a given energy/power."""

    energy_kwh: float
    energy_wh: float
    cost: float
    carbon_grams: float
    carbon_kg: float
    burn_rate_per_hour: float
    projected_daily_kwh: float
    projected_daily_cost: float
    projected_monthly_kwh: float
    projected_monthly_cost: float
    projected_yearly_cost: float
    projected_monthly_co2_kg: float
    # Intuitive real-world equivalents for projected monthly (or accumulated) CO2/energy
    equiv_phone_charges: float
    equiv_car_km: float
    equiv_tree_days: float
    equiv_led_bulb_hours: float


@dataclass
class HistoricalBucket:
    """Aggregated historical power/energy bucket (hourly or daily) from SQLite."""

    bucket_label: str
    bucket_start_ts: float
    avg_watts: float
    peak_watts: float
    energy_wh: float
    cpu_wh: float
    gpu_wh: float
    sample_count: int

    @property
    def energy_kwh(self) -> float:
        return self.energy_wh / 1000.0
