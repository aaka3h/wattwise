"""Electricity tariff calculation, regional grid presets, and CO2 footprint engine."""

from __future__ import annotations

from wattwise.models import ImpactMetrics, TariffProfile

# Regional electricity retail tariff & grid carbon intensity presets (Ember / IEA reference values)
REGIONAL_PRESETS: dict[str, TariffProfile] = {
    "us_avg": TariffProfile(
        region_key="us_avg",
        region_label="United States (National Avg)",
        currency_symbol="$",
        currency_code="USD",
        rate_per_kwh=0.175,
        carbon_g_per_kwh=386.0,
    ),
    "us_ca": TariffProfile(
        region_key="us_ca",
        region_label="United States (California)",
        currency_symbol="$",
        currency_code="USD",
        rate_per_kwh=0.320,
        carbon_g_per_kwh=210.0,
    ),
    "global_avg": TariffProfile(
        region_key="global_avg",
        region_label="Global Average",
        currency_symbol="$",
        currency_code="USD",
        rate_per_kwh=0.160,
        carbon_g_per_kwh=475.0,
    ),
    "eu_avg": TariffProfile(
        region_key="eu_avg",
        region_label="European Union (Average)",
        currency_symbol="€",
        currency_code="EUR",
        rate_per_kwh=0.285,
        carbon_g_per_kwh=242.0,
    ),
    "uk": TariffProfile(
        region_key="uk",
        region_label="United Kingdom",
        currency_symbol="£",
        currency_code="GBP",
        rate_per_kwh=0.245,
        carbon_g_per_kwh=205.0,
    ),
    "germany": TariffProfile(
        region_key="germany",
        region_label="Germany",
        currency_symbol="€",
        currency_code="EUR",
        rate_per_kwh=0.370,
        carbon_g_per_kwh=350.0,
    ),
    "france": TariffProfile(
        region_key="france",
        region_label="France (Low-Carbon Grid)",
        currency_symbol="€",
        currency_code="EUR",
        rate_per_kwh=0.252,
        carbon_g_per_kwh=56.0,
    ),
    "nordic": TariffProfile(
        region_key="nordic",
        region_label="Nordic Hydro / Wind (SE/NO)",
        currency_symbol="€",
        currency_code="EUR",
        rate_per_kwh=0.190,
        carbon_g_per_kwh=28.0,
    ),
    "india": TariffProfile(
        region_key="india",
        region_label="India",
        currency_symbol="₹",
        currency_code="INR",
        rate_per_kwh=7.50,
        carbon_g_per_kwh=708.0,
    ),
    "singapore": TariffProfile(
        region_key="singapore",
        region_label="Singapore",
        currency_symbol="S$",
        currency_code="SGD",
        rate_per_kwh=0.298,
        carbon_g_per_kwh=408.0,
    ),
    "malaysia": TariffProfile(
        region_key="malaysia",
        region_label="Malaysia",
        currency_symbol="RM",
        currency_code="MYR",
        rate_per_kwh=0.450,
        carbon_g_per_kwh=565.0,
    ),
    "china": TariffProfile(
        region_key="china",
        region_label="China",
        currency_symbol="¥",
        currency_code="CNY",
        rate_per_kwh=0.580,
        carbon_g_per_kwh=555.0,
    ),
    "japan": TariffProfile(
        region_key="japan",
        region_label="Japan",
        currency_symbol="¥",
        currency_code="JPY",
        rate_per_kwh=31.0,
        carbon_g_per_kwh=462.0,
    ),
    "australia": TariffProfile(
        region_key="australia",
        region_label="Australia",
        currency_symbol="A$",
        currency_code="AUD",
        rate_per_kwh=0.330,
        carbon_g_per_kwh=510.0,
    ),
    "canada": TariffProfile(
        region_key="canada",
        region_label="Canada",
        currency_symbol="C$",
        currency_code="CAD",
        rate_per_kwh=0.155,
        carbon_g_per_kwh=120.0,
    ),
    "custom": TariffProfile(
        region_key="custom",
        region_label="Custom Tariff & Grid",
        currency_symbol="$",
        currency_code="USD",
        rate_per_kwh=0.175,
        carbon_g_per_kwh=386.0,
    ),
}

CURRENCY_CHOICES: list[tuple[str, str]] = [
    ("$", "USD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("₹", "INR"),
    ("S$", "SGD"),
    ("RM", "MYR"),
    ("¥", "JPY/CNY"),
    ("A$", "AUD"),
    ("C$", "CAD"),
]

# Physical conversion benchmarks (EPA Greenhouse Gas Equivalencies & standard device specs)
WH_PER_SMARTPHONE_CHARGE = 14.5       # Typical 3800mAh smartphone full charge incl. charger loss
CO2_GRAMS_PER_CAR_KM = 170.0          # Avg passenger vehicle tailpipe g CO2 / km
CO2_GRAMS_PER_TREE_DAY = 59.6         # Mature tree absorbs ~21.77 kg CO2/year (~59.6 g/day)
WATTS_STANDARD_LED_BULB = 9.0         # 9W 800-lumen A19 LED bulb


def energy_cost(energy_wh: float, profile: TariffProfile) -> float:
    """Compute variable electricity cost for a given energy amount in Wh."""
    kwh = max(0.0, energy_wh) / 1000.0
    return kwh * max(0.0, profile.rate_per_kwh)


def energy_carbon_grams(energy_wh: float, profile: TariffProfile) -> float:
    """Compute carbon dioxide equivalent emissions (g CO2e) for energy in Wh."""
    kwh = max(0.0, energy_wh) / 1000.0
    return kwh * max(0.0, profile.carbon_g_per_kwh)


def monthly_projection_for_watts(watts: float, profile: TariffProfile) -> tuple[float, float, float]:
    """Project 30-day (kWh, variable_cost, co2_kg) assuming daily_active_hours_est/day."""
    active_hours_month = max(0.25, min(24.0, profile.daily_active_hours_est)) * 30.0
    kwh = (max(0.0, watts) * active_hours_month) / 1000.0
    cost = kwh * max(0.0, profile.rate_per_kwh) + (max(0.0, profile.daily_fixed_fee) * 30.0)
    co2_kg = (kwh * max(0.0, profile.carbon_g_per_kwh)) / 1000.0
    return kwh, cost, co2_kg


def calculate_impact(
    energy_wh: float,
    live_watts: float,
    profile: TariffProfile,
    use_monthly_for_equivalents: bool = False,
) -> ImpactMetrics:
    """Compute comprehensive cost, burn-rate, projections, and environmental equivalents."""
    ewh = max(0.0, energy_wh)
    ekwh = ewh / 1000.0
    cost = energy_cost(ewh, profile)
    co2_g = energy_carbon_grams(ewh, profile)
    co2_kg = co2_g / 1000.0

    # Live hourly burn rate at current wattage
    burn_per_hr = (max(0.0, live_watts) / 1000.0) * max(0.0, profile.rate_per_kwh)

    # Projections based on active hours per day configured by the user
    daily_hrs = max(0.25, min(24.0, profile.daily_active_hours_est))
    daily_kwh = (max(0.0, live_watts) * daily_hrs) / 1000.0
    daily_cost = daily_kwh * max(0.0, profile.rate_per_kwh) + max(0.0, profile.daily_fixed_fee)

    monthly_kwh = daily_kwh * 30.0
    monthly_cost = daily_cost * 30.0
    yearly_cost = daily_cost * 365.0
    monthly_co2_g = monthly_kwh * max(0.0, profile.carbon_g_per_kwh)
    monthly_co2_kg = monthly_co2_g / 1000.0

    ref_wh = (monthly_kwh * 1000.0) if use_monthly_for_equivalents else ewh
    ref_co2_g = monthly_co2_g if use_monthly_for_equivalents else co2_g

    return ImpactMetrics(
        energy_kwh=ekwh,
        energy_wh=ewh,
        cost=cost,
        carbon_grams=co2_g,
        carbon_kg=co2_kg,
        burn_rate_per_hour=burn_per_hr,
        projected_daily_kwh=daily_kwh,
        projected_daily_cost=daily_cost,
        projected_monthly_kwh=monthly_kwh,
        projected_monthly_cost=monthly_cost,
        projected_yearly_cost=yearly_cost,
        projected_monthly_co2_kg=monthly_co2_kg,
        equiv_phone_charges=ref_wh / WH_PER_SMARTPHONE_CHARGE,
        equiv_car_km=ref_co2_g / CO2_GRAMS_PER_CAR_KM,
        equiv_tree_days=ref_co2_g / CO2_GRAMS_PER_TREE_DAY,
        equiv_led_bulb_hours=ref_wh / WATTS_STANDARD_LED_BULB,
    )


def format_currency(amount: float, symbol: str = "$") -> str:
    """Format currency values cleanly across micro-session amounts and full bills."""
    val = max(0.0, amount)
    if val == 0.0:
        return f"{symbol}0.00"
    if val < 0.01:
        return f"{symbol}{val:.4f}"
    if val < 1.0:
        return f"{symbol}{val:.3f}"
    if val >= 1000.0:
        return f"{symbol}{val:,.2f}"
    return f"{symbol}{val:.2f}"


def format_energy(wh: float) -> str:
    """Format Watt-hours into Wh or kWh automatically."""
    val = max(0.0, wh)
    if val >= 1000.0:
        return f"{val / 1000.0:.3f} kWh"
    if val >= 10.0:
        return f"{val:.2f} Wh"
    return f"{val:.3f} Wh"


def format_carbon(grams: float) -> str:
    """Format grams of CO2e into mg, g, or kg CO2e cleanly."""
    val = max(0.0, grams)
    if val >= 1000.0:
        return f"{val / 1000.0:.2f} kg CO₂e"
    if val >= 1.0:
        return f"{val:.2f} g CO₂e"
    return f"{val:.3f} g CO₂e"
