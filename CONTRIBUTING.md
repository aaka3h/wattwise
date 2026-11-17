# Contributing to WattWise ⚡

Thank you for your interest in contributing to **WattWise**! Everyone is welcome to contribute — whether you are fixing a typo, adding your country's electricity tariff & grid carbon preset, testing hardware sensors on a new laptop/desktop, or building new UI visualizations.

---

## Ways Anyone Can Contribute

You don't need rare hardware to make a meaningful contribution! Here are great ways to jump in:

1. **Add Regional Electricity Tariffs & Grid Carbon Factors (`Good First Issue`)**
   - Add your country, state, or utility provider preset to `REGIONAL_PRESETS` in [`src/wattwise/pricing.py`](src/wattwise/pricing.py) with retail rate per kWh and grid carbon intensity (`g CO₂e/kWh`).
2. **Expand Hardware Sensor Coverage**
   - **Linux**: Test or add support for additional `hwmon` drivers (e.g., Intel Arc `xe`, Qualcomm Snapdragon ARM64 laptops, Rockchip/Raspberry Pi SBC sensors, USB wattmeters) in [`src/wattwise/collectors/linux.py`](src/wattwise/collectors/linux.py).
   - **Windows**: Test or improve WMI/EMI/AMD ADL/Intel GPU telemetry on Intel, AMD Ryzen, and Snapdragon X Elite (`ARM64`) devices in [`src/wattwise/collectors/windows.py`](src/wattwise/collectors/windows.py).
   - **macOS (Apple Silicon M-series & Intel)**: Add chip TDP/core profiles for new Apple Silicon (`M1`–`M4+` Base/Pro/Max/Ultra) or Intel Mac models in [`src/wattwise/collectors/macos.py`](src/wattwise/collectors/macos.py).
3. **Desktop UI, Charts & Accessibility**
   - Enhance vector `QPainter` widgets in [`src/wattwise/ui/widgets.py`](src/wattwise/ui/widgets.py), add themes in [`src/wattwise/ui/theme.py`](src/wattwise/ui/theme.py), or add export/reporting formats in [`src/wattwise/storage.py`](src/wattwise/storage.py).
4. **Bug Reports & Hardware Diagnostics**
   - Run `wattwise --cli` or `wattwise --json` on your machine and share sanitized sensor output in a GitHub Issue if a device isn't detected yet!

---

## Development Setup

### Prerequisites
- **Python 3.10+**
- **Git**

### 1. Fork & Clone

Fork **[aaka3h/wattwise](https://github.com/aaka3h/wattwise)** on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-username>/wattwise.git
cd wattwise
git remote add upstream https://github.com/aaka3h/wattwise.git
```

### 2. Create a Virtual Environment & Install in Editable Mode

**Linux / macOS (Apple Silicon & Intel):**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

*(Alternatively, if you use [`uv`](https://docs.astral.sh/uv/), simply run `uv sync --all-extras` and `uv run wattwise`.)*

### 3. Run the App Locally

```bash
# Launch the standalone Qt6 desktop GUI
wattwise

# Run terminal CLI snapshot mode
wattwise --cli

# Inspect structured JSON telemetry
wattwise --json
```

---

## Project Architecture

```text
wattwise/
├── src/wattwise/
│   ├── __main__.py          # Desktop GUI & CLI/JSON entrypoints
│   ├── models.py            # Dataclasses (PowerSnapshot, HardwareComponent, TariffProfile, etc.)
│   ├── pricing.py           # Regional tariffs ($/kWh), currencies, CO2e math & equivalents
│   ├── storage.py           # Thread-safe SQLite history, rollups & CSV/JSON exporters
│   ├── collectors/
│   │   ├── base.py          # BasePlatformCollector, NVIDIA SMI/pmon bridge, per-app attribution
│   │   ├── linux.py         # Linux sysfs power_supply, RAPL, hwmon, DRM GPU & backlight
│   │   ├── windows.py       # Windows Win32, WMI BatteryStatus, EMI PowerMeter & LHM bridge
│   │   └── macos.py         # macOS Apple Silicon (M-series) & Intel IOKit + powermetrics
│   └── ui/
│       ├── qt_compat.py     # Unified PySide6 / PyQt6 compatibility & vector icon renderer
│       ├── theme.py         # Obsidian Dark & Daylight Frost QSS design tokens
│       ├── widgets.py       # Anti-aliased QPainter gauges, live hover charts & history bars
│       └── main_window.py   # Main desktop window, tabs, system tray & TelemetryWorker thread
├── scripts/
│   ├── build_desktop.py     # Cross-platform PyInstaller bundler (.exe / .app / binary)
│   └── install_linux_desktop.sh
└── tests/                   # Automated unit & headless GUI test suite
```

---

## Guide: Adding a New Regional Tariff & Grid Preset

Open [`src/wattwise/pricing.py`](src/wattwise/pricing.py) and add an entry to `REGIONAL_PRESETS`:

```python
"brazil": TariffProfile(
    region_key="brazil",
    region_label="Brazil",
    currency_symbol="R$",
    currency_code="BRL",
    rate_per_kwh=0.85,
    carbon_g_per_kwh=98.0,
),
```

If your currency symbol isn't listed in `CURRENCY_CHOICES`, add `("R$", "BRL")` there as well, then run `pytest`!

---

## Running Tests Before Submitting a PR

All collectors (including mocked Linux `sysfs`, Windows CIM/WMI, and macOS Apple Silicon/Intel `ioreg` plists) and the Qt6 UI run headless anywhere:

```bash
pytest -v
```

On headless Linux servers/containers, `tests/test_ui_smoke.py` automatically sets `QT_QPA_PLATFORM=offscreen` and verifies full widget rendering across every tab and theme.

---

## Submitting a Pull Request

1. Create a descriptive branch from `main`:
   ```bash
   git checkout -b feat/add-brazil-grid-preset
   ```
2. Keep changes focused, preserve existing docstrings/comments, and add or update unit tests in `tests/` when adding new sensor parsers or calculations.
3. Verify all tests pass locally (`pytest -v`).
4. Push your branch to your fork and open a **Pull Request** against `main` describing:
   - What changed and why
   - Which OS(es) you tested on (Linux / Windows / macOS Apple Silicon / macOS Intel)
   - Screenshots if you updated the desktop UI

Thank you for helping people everywhere understand and reduce their device energy use and carbon footprint!
