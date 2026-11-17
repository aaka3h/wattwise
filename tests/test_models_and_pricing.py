"""Unit tests for electricity cost, tariff presets, and carbon footprint calculations."""

from __future__ import annotations

import math

from wattwise.models import TariffProfile
from wattwise.pricing import (
    REGIONAL_PRESETS,
    calculate_impact,
    energy_carbon_grams,
    energy_cost,
    format_carbon,
    format_currency,
    format_energy,
    monthly_projection_for_watts,
)


def test_regional_presets_valid() -> None:
    assert "us_avg" in REGIONAL_PRESETS
    assert "eu_avg" in REGIONAL_PRESETS
    assert "india" in REGIONAL_PRESETS
    for key, prof in REGIONAL_PRESETS.items():
        assert prof.region_key == key
        assert prof.rate_per_kwh > 0
        assert prof.carbon_g_per_kwh >= 0
        assert prof.currency_symbol


def test_cost_and_carbon_math() -> None:
    prof = TariffProfile(
        region_key="test",
        region_label="Test Grid",
        currency_symbol="$",
        currency_code="USD",
        rate_per_kwh=0.20,
        carbon_g_per_kwh=400.0,
        daily_active_hours_est=10.0,
    )
    # 500 Wh = 0.5 kWh -> $0.10 and 200 g CO2e
    assert math.isclose(energy_cost(500.0, prof), 0.10, rel_tol=1e-6)
    assert math.isclose(energy_carbon_grams(500.0, prof), 200.0, rel_tol=1e-6)

    # 50W @ 10 hrs/day * 30 days = 15 kWh/mo -> $3.00/mo, 6.0 kg CO2e/mo
    m_kwh, m_cost, m_co2 = monthly_projection_for_watts(50.0, prof)
    assert math.isclose(m_kwh, 15.0, rel_tol=1e-6)
    assert math.isclose(m_cost, 3.00, rel_tol=1e-6)
    assert math.isclose(m_co2, 6.0, rel_tol=1e-6)

    imp = calculate_impact(500.0, 50.0, prof, use_monthly_for_equivalents=True)
    assert math.isclose(imp.burn_rate_per_hour, 0.01, rel_tol=1e-6)
    assert math.isclose(imp.projected_monthly_cost, 3.00, rel_tol=1e-6)
    assert imp.equiv_phone_charges > 100
    assert imp.equiv_car_km > 10
    assert imp.equiv_tree_days > 10
    assert imp.equiv_led_bulb_hours > 1000


def test_formatting_helpers() -> None:
    assert format_currency(0.0, "$") == "$0.00"
    assert format_currency(0.0042, "$") == "$0.0042"
    assert format_currency(14.5, "€") == "€14.50"
    assert format_energy(8.5) == "8.500 Wh"
    assert format_energy(1500.0) == "1.500 kWh"
    assert format_carbon(42.3) == "42.30 g CO₂e"
    assert format_carbon(2500.0) == "2.50 kg CO₂e"
