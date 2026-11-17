"""Main entrypoint for WattWise standalone desktop GUI and optional CLI mode."""

from __future__ import annotations

import argparse
import json
import sys
import time

from wattwise import __app_name__, __version__
from wattwise.collectors import PowerEngine
from wattwise.pricing import (
    calculate_impact,
    format_carbon,
    format_currency,
    format_energy,
)
from wattwise.storage import WattWiseStorage


def run_cli_report(samples: int = 2, interval: float = 0.8, as_json: bool = False) -> int:
    """Collect live telemetry and print a formatted per-device & cost/CO2 summary."""
    storage = WattWiseStorage()
    try:
        tariff = storage.load_tariff()
        engine = PowerEngine(storage=storage)

        snap = engine.sample()
        for _ in range(max(0, samples - 1)):
            time.sleep(max(0.2, interval))
            snap = engine.sample()

        impact = calculate_impact(
            energy_wh=snap.session_energy_wh,
            live_watts=snap.total_watts,
            profile=tariff,
            use_monthly_for_equivalents=True,
        )

        if as_json:
            out = {
                "snapshot": snap.to_dict(),
                "tariff": tariff.to_dict(),
                "projected_monthly_kwh": round(impact.projected_monthly_kwh, 3),
                "projected_monthly_cost": round(impact.projected_monthly_cost, 3),
                "projected_monthly_co2_kg": round(impact.projected_monthly_co2_kg, 3),
            }
            print(json.dumps(out, indent=2))
            return 0

        sym = tariff.currency_symbol
        co2_hr = (snap.total_watts / 1000.0) * tariff.carbon_g_per_kwh
        print(f"⚡ {__app_name__} v{__version__} — {snap.platform_name}")
        print("=" * 72)
        print(
            f"Total System Power : {snap.total_watts:.2f} W  [{snap.sensor_mode.upper()} — {snap.primary_source}]"
        )
        print(
            f"Burn Rate          : {format_currency(impact.burn_rate_per_hour, sym)}/hr  |  {co2_hr:.1f} g CO2e/hr"
        )
        print(
            f"Monthly Estimate   : {format_currency(impact.projected_monthly_cost, sym)}/mo  "
            f"({impact.projected_monthly_kwh:.2f} kWh, {impact.projected_monthly_co2_kg:.2f} kg CO2e @ {tariff.daily_active_hours_est:.0f}h/day)"
        )
        if snap.battery.present:
            print(
                f"Battery            : {snap.battery.status} ({snap.battery.percent:.0f}%)"
                + (
                    f" — {snap.battery.energy_now_wh:.1f}/{snap.battery.energy_full_wh:.1f} Wh"
                    if snap.battery.energy_now_wh and snap.battery.energy_full_wh
                    else ""
                )
            )
        print("-" * 72)
        print("Hardware Devices:")
        for c in sorted(snap.components, key=lambda x: x.watts, reverse=True):
            share = (c.watts / max(0.1, snap.total_watts)) * 100.0
            print(
                f"  • {c.name:<40} {c.watts:>6.2f} W ({share:>4.0f}%)  [{c.sensor_source}]"
            )
        print("-" * 72)
        print("Top Active Applications:")
        for p in snap.processes[:8]:
            print(
                f"  • {p.app_name:<28} {p.watts:>6.2f} W  "
                f"(CPU {p.cpu_pct:>5.1f}%, GPU {p.gpu_pct:>4.1f}%, RAM {p.memory_mb:>5.0f} MB)"
            )
        print("=" * 72)
        return 0
    finally:
        storage.close()


def launch_gui() -> int:
    """Launch the standalone native Qt6 desktop window."""
    from wattwise.ui.main_window import WattWiseMainWindow
    from wattwise.ui.qt_compat import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    # Enable crisp fractional high-DPI rendering across Windows, macOS Retina, and Linux
    win = WattWiseMainWindow()
    win.show()
    return app.exec()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wattwise",
        description=(
            "WattWise — Cross-platform native desktop power consumption, electricity cost, "
            "and carbon footprint tracker for Linux, Windows, Apple Silicon (M-series), and Intel macOS."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Print a live hardware & application power report in the terminal instead of opening the desktop GUI.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output live power telemetry and cost/carbon projections as JSON.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=2,
        help="Number of samples to collect in --cli/--json mode (default: 2).",
    )
    return parser


def cli_main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return run_cli_report(samples=args.samples, as_json=args.json)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.cli or args.json:
        return run_cli_report(samples=args.samples, as_json=args.json)
    return launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
