"""Main native desktop window and background telemetry worker for WattWise."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import threading
from typing import Optional

from wattwise import __app_name__, __version__
from wattwise.collectors import PowerEngine
from wattwise.models import PowerSnapshot, TariffProfile
from wattwise.pricing import (
    CURRENCY_CHOICES,
    REGIONAL_PRESETS,
    calculate_impact,
    energy_carbon_grams,
    energy_cost,
    format_carbon,
    format_currency,
    format_energy,
    monthly_projection_for_watts,
)
from wattwise.storage import WattWiseStorage
from wattwise.ui.qt_compat import (
    QT_BINDING,
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    Qt,
    QThread,
    QVBoxLayout,
    QWidget,
    Signal,
    create_app_icon,
)
from wattwise.ui.theme import build_stylesheet, get_palette
from wattwise.ui.widgets import (
    DeviceBreakdownWidget,
    HistoryBarChart,
    KpiCard,
    LivePowerChart,
    RadialPowerGauge,
)


class TelemetryWorker(QThread):
    """Dedicated background worker thread so hardware/CLI probes never block the GUI."""

    snapshot_ready = Signal(object)

    def __init__(self, engine: PowerEngine, interval_sec: float = 2.0) -> None:
        super().__init__()
        self.engine = engine
        self._interval_sec = max(0.5, float(interval_sec))
        self._paused = False
        self._stop_event = threading.Event()

    def set_interval(self, seconds: float) -> None:
        self._interval_sec = max(0.5, float(seconds))

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(3000)

    def run(self) -> None:
        # Take immediate initial sample
        try:
            snap = self.engine.sample()
            self.snapshot_ready.emit(snap)
        except Exception:
            pass

        while not self._stop_event.is_set():
            if self._stop_event.wait(self._interval_sec):
                break
            if self._paused:
                continue
            try:
                snap = self.engine.sample()
                self.snapshot_ready.emit(snap)
            except Exception:
                continue


def _format_duration(seconds: float) -> str:
    sec = int(max(0.0, seconds))
    hrs, rem = divmod(sec, 3600)
    mins, s = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {s:02d}s"
    return f"{mins}m {s:02d}s"


class WattWiseMainWindow(QMainWindow):
    """Cross-platform standalone native desktop window for WattWise."""

    def __init__(
        self,
        storage: Optional[WattWiseStorage] = None,
        engine: Optional[PowerEngine] = None,
        start_worker: bool = True,
    ) -> None:
        super().__init__()
        self.storage = storage or WattWiseStorage()
        self.engine = engine or PowerEngine(storage=self.storage)

        self.tariff: TariffProfile = self.storage.load_tariff()
        saved_theme = str(self.storage.load_pref("theme", "dark"))
        self.palette_theme = get_palette(saved_theme)
        self.sample_interval = float(self.storage.load_pref("sample_interval", 2.0))
        self.minimize_to_tray = bool(self.storage.load_pref("minimize_to_tray", False))
        self._force_quit = False

        self.latest_snapshot: Optional[PowerSnapshot] = None
        self._history_period = "24h"   # "24h", "7d", "30d"
        self._history_metric = "energy"  # "energy", "cost", "carbon"
        self._updating_tariff_ui = False

        self.app_icon = create_app_icon(128)
        self.setWindowTitle(f"{__app_name__} — Power, Cost & Carbon Tracker")
        self.setWindowIcon(self.app_icon)
        self.resize(1220, 800)
        self.setMinimumSize(980, 660)

        self._build_ui()
        self._setup_tray()
        self._apply_theme(self.palette_theme.name)

        self.worker = TelemetryWorker(self.engine, interval_sec=self.sample_interval)
        self.worker.snapshot_ready.connect(self._on_snapshot)
        if start_worker:
            self.worker.start()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("RootContainer")
        self.setCentralWidget(root)

        main_h = QHBoxLayout(root)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # Left Navigation Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        side_v = QVBoxLayout(sidebar)
        side_v.setContentsMargins(16, 20, 16, 16)
        side_v.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_badge = QLabel("⚡")
        brand_badge.setStyleSheet(
            "font-size: 20px; background-color: #059669; color: white; "
            "border-radius: 8px; padding: 4px 8px;"
        )
        brand_badge.setFixedSize(36, 36)
        brand_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        brand_txt_v = QVBoxLayout()
        brand_txt_v.setSpacing(1)
        title_lbl = QLabel(__app_name__)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.os_badge_lbl = QLabel(self.engine.collector.host_platform_banner())
        self.os_badge_lbl.setObjectName("MutedLabel")
        self.os_badge_lbl.setStyleSheet("font-size: 11px;")
        brand_txt_v.addWidget(title_lbl)
        brand_txt_v.addWidget(self.os_badge_lbl)

        brand_row.addWidget(brand_badge)
        brand_row.addSpacing(8)
        brand_row.addLayout(brand_txt_v)
        brand_row.addStretch()
        side_v.addLayout(brand_row)
        side_v.addSpacing(14)

        self.nav_buttons: list[QPushButton] = []
        nav_specs = [
            ("⚡  Live Dashboard", 0),
            ("🖥️  By Device && App", 1),
            ("🌱  Cost && Carbon", 2),
            ("⚙️  Platform && Export", 3),
        ]
        for label, idx in nav_specs:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self.switch_page(i))
            side_v.addWidget(btn)
            self.nav_buttons.append(btn)

        side_v.addStretch()

        # Quick live sidebar status card
        status_card = QFrame()
        status_card.setObjectName("SubCard")
        sc_v = QVBoxLayout(status_card)
        sc_v.setContentsMargins(12, 10, 12, 10)
        sc_v.setSpacing(6)

        self.sidebar_live_lbl = QLabel("● Sampling Live")
        self.sidebar_live_lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #10B981;")
        self.sidebar_session_lbl = QLabel("Session: 0m 00s")
        self.sidebar_session_lbl.setObjectName("MutedLabel")
        sc_v.addWidget(self.sidebar_live_lbl)
        sc_v.addWidget(self.sidebar_session_lbl)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("ActionButton")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self._toggle_pause)

        self.quick_theme_btn = QPushButton("Theme")
        self.quick_theme_btn.setObjectName("ActionButton")
        self.quick_theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_theme_btn.clicked.connect(self._toggle_theme)

        ctrl_row.addWidget(self.pause_btn)
        ctrl_row.addWidget(self.quick_theme_btn)
        sc_v.addLayout(ctrl_row)
        side_v.addWidget(status_card)

        main_h.addWidget(sidebar)

        # Stacked Right Content Pages
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_dashboard_page())
        self.pages.addWidget(self._build_devices_apps_page())
        self.pages.addWidget(self._build_cost_carbon_page())
        self.pages.addWidget(self._build_settings_page())
        main_h.addWidget(self.pages, stretch=1)

        self.switch_page(0)

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------
    # Page 0: Live Dashboard
    # ------------------------------------------------------------------

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        h_left = QVBoxLayout()
        h_left.setSpacing(2)
        t = QLabel("Real-Time Power Overview")
        t.setObjectName("PageTitle")
        self.dash_subtitle_lbl = QLabel("Initializing cross-platform hardware sensors…")
        self.dash_subtitle_lbl.setObjectName("MutedLabel")
        h_left.addWidget(t)
        h_left.addWidget(self.dash_subtitle_lbl)
        hdr.addLayout(h_left)
        hdr.addStretch()

        self.tariff_pill_btn = QPushButton()
        self.tariff_pill_btn.setObjectName("ActionButton")
        self.tariff_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tariff_pill_btn.clicked.connect(lambda: self.switch_page(2))
        hdr.addWidget(self.tariff_pill_btn)
        v.addLayout(hdr)

        # 4 Top KPI Cards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpi_power = KpiCard("LIVE SYSTEM DRAW", "#10B981")
        self.kpi_energy = KpiCard("TODAY'S ENERGY", "#06B6D4")
        self.kpi_cost = KpiCard("ELECTRICITY COST", "#8B5CF6")
        self.kpi_carbon = KpiCard("CARBON FOOTPRINT (CO₂e)", "#F59E0B")
        for card in (self.kpi_power, self.kpi_energy, self.kpi_cost, self.kpi_carbon):
            kpi_row.addWidget(card, stretch=1)
        v.addLayout(kpi_row)

        # Middle row: Gauge + Battery card on left | Live Chart on right
        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)

        left_card = QFrame()
        left_card.setObjectName("Card")
        left_card.setFixedWidth(315)
        lc_v = QVBoxLayout(left_card)
        lc_v.setContentsMargins(14, 14, 14, 14)
        lc_v.setSpacing(8)

        g_title = QLabel("Instantaneous Load")
        g_title.setObjectName("SectionTitle")
        lc_v.addWidget(g_title)

        self.radial_gauge = RadialPowerGauge(self.palette_theme)
        lc_v.addWidget(self.radial_gauge, stretch=1)

        bat_box = QFrame()
        bat_box.setObjectName("SubCard")
        bb_v = QVBoxLayout(bat_box)
        bb_v.setContentsMargins(12, 9, 12, 9)
        bb_v.setSpacing(3)
        self.bat_title_lbl = QLabel("Power Source: Detecting…")
        self.bat_title_lbl.setStyleSheet("font-weight: 700; font-size: 12px;")
        self.bat_detail_lbl = QLabel("—")
        self.bat_detail_lbl.setObjectName("MutedLabel")
        self.bat_detail_lbl.setWordWrap(True)
        bb_v.addWidget(self.bat_title_lbl)
        bb_v.addWidget(self.bat_detail_lbl)
        lc_v.addWidget(bat_box)

        mid_row.addWidget(left_card)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cc_v = QVBoxLayout(chart_card)
        cc_v.setContentsMargins(16, 14, 16, 14)
        cc_v.setSpacing(6)

        ch_top = QHBoxLayout()
        ch_lbl = QLabel("Live Power Timeline (Total vs CPU vs GPU)")
        ch_lbl.setObjectName("SectionTitle")
        ch_hint = QLabel("Hover chart to inspect point-in-time wattage")
        ch_hint.setObjectName("MutedLabel")
        ch_top.addWidget(ch_lbl)
        ch_top.addStretch()
        ch_top.addWidget(ch_hint)
        cc_v.addLayout(ch_top)

        self.live_chart = LivePowerChart(max_points=180, palette=self.palette_theme)
        cc_v.addWidget(self.live_chart, stretch=1)
        mid_row.addWidget(chart_card, stretch=1)

        v.addLayout(mid_row, stretch=1)

        # Bottom row: Hardware Device Breakdown
        dev_card = QFrame()
        dev_card.setObjectName("Card")
        dc_v = QVBoxLayout(dev_card)
        dc_v.setContentsMargins(16, 14, 16, 14)
        dc_v.setSpacing(8)

        dh_row = QHBoxLayout()
        dh_title = QLabel("Power Consumption by Hardware Device")
        dh_title.setObjectName("SectionTitle")
        dh_more = QPushButton("View Full Device && App Table →")
        dh_more.setObjectName("ActionButton")
        dh_more.setCursor(Qt.CursorShape.PointingHandCursor)
        dh_more.clicked.connect(lambda: self.switch_page(1))
        dh_row.addWidget(dh_title)
        dh_row.addStretch()
        dh_row.addWidget(dh_more)
        dc_v.addLayout(dh_row)

        self.device_bars = DeviceBreakdownWidget(palette=self.palette_theme)
        dc_v.addWidget(self.device_bars)
        v.addWidget(dev_card)

        return self._wrap_scroll(page)

    # ------------------------------------------------------------------
    # Page 1: By Device & App
    # ------------------------------------------------------------------

    def _build_devices_apps_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(16)

        t = QLabel("Hardware Devices & Applications")
        t.setObjectName("PageTitle")
        sub = QLabel(
            "Granular wattage, accumulated energy (Wh), and monthly electricity bill impact across hardware subsystems and running apps."
        )
        sub.setObjectName("MutedLabel")
        v.addWidget(t)
        v.addWidget(sub)

        # Hardware Subsystems Card
        hw_card = QFrame()
        hw_card.setObjectName("Card")
        hw_v = QVBoxLayout(hw_card)
        hw_v.setContentsMargins(16, 14, 16, 14)
        hw_v.setSpacing(10)

        hw_lbl = QLabel("Hardware Subsystems")
        hw_lbl.setObjectName("SectionTitle")
        hw_v.addWidget(hw_lbl)

        self.hw_table = QTableWidget(0, 8)
        self.hw_table.setHorizontalHeaderLabels(
            [
                "Device Name",
                "Type",
                "Sensor",
                "Load / Rate",
                "Temp",
                "Power",
                "Energy",
                "Monthly Est.",
            ]
        )
        self.hw_table.verticalHeader().setVisible(False)
        self.hw_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hw_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hw_table.setAlternatingRowColors(True)
        self.hw_table.setMinimumHeight(225)
        hh = self.hw_table.horizontalHeader()
        hh.setMinimumSectionSize(52)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 8):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hw_v.addWidget(self.hw_table)
        v.addWidget(hw_card)

        # Applications & Processes Card
        app_card = QFrame()
        app_card.setObjectName("Card")
        ap_v = QVBoxLayout(app_card)
        ap_v.setContentsMargins(16, 14, 16, 14)
        ap_v.setSpacing(10)

        ap_hdr = QHBoxLayout()
        ap_lbl = QLabel("Active Applications & Processes Attribution")
        ap_lbl.setObjectName("SectionTitle")
        self.app_search_edit = QLineEdit()
        self.app_search_edit.setPlaceholderText("Filter applications by name…")
        self.app_search_edit.setFixedWidth(250)
        self.app_search_edit.textChanged.connect(self._refresh_apps_table)
        ap_hdr.addWidget(ap_lbl)
        ap_hdr.addStretch()
        ap_hdr.addWidget(self.app_search_edit)
        ap_v.addLayout(ap_hdr)

        self.app_table = QTableWidget(0, 8)
        self.app_table.setHorizontalHeaderLabels(
            [
                "Application",
                "PIDs",
                "CPU %",
                "GPU %",
                "Memory",
                "Est. Power",
                "Session Energy",
                "If Sustained / Mo",
            ]
        )
        self.app_table.verticalHeader().setVisible(False)
        self.app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.app_table.setAlternatingRowColors(True)
        self.app_table.setMinimumHeight(260)
        ah = self.app_table.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 8):
            ah.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        ap_v.addWidget(self.app_table)
        v.addWidget(app_card, stretch=1)

        return self._wrap_scroll(page)

    # ------------------------------------------------------------------
    # Page 2: Cost & Carbon ($ / CO2e)
    # ------------------------------------------------------------------

    def _build_cost_carbon_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(16)

        t = QLabel("Electricity Cost & Carbon Footprint (CO₂e)")
        t.setObjectName("PageTitle")
        sub = QLabel(
            "Configure your electricity tariff ($/kWh) and local power-grid carbon intensity (g CO₂e/kWh) for real-time cost & climate impact analysis."
        )
        sub.setObjectName("MutedLabel")
        v.addWidget(t)
        v.addWidget(sub)

        # Tariff Configurator Card
        cfg_card = QFrame()
        cfg_card.setObjectName("Card")
        cfg_grid = QGridLayout(cfg_card)
        cfg_grid.setContentsMargins(16, 14, 16, 14)
        cfg_grid.setHorizontalSpacing(14)
        cfg_grid.setVerticalSpacing(8)

        cfg_grid.addWidget(QLabel("Regional Grid Preset"), 0, 0)
        cfg_grid.addWidget(QLabel("Currency"), 0, 1)
        cfg_grid.addWidget(QLabel("Tariff Rate (per kWh)"), 0, 2)
        cfg_grid.addWidget(QLabel("Grid Carbon (g CO₂e/kWh)"), 0, 3)
        cfg_grid.addWidget(QLabel("Active Usage (hrs/day)"), 0, 4)

        self.region_combo = QComboBox()
        for key, prof in REGIONAL_PRESETS.items():
            self.region_combo.addItem(prof.region_label, userData=key)
        self.region_combo.currentIndexChanged.connect(self._on_region_preset_changed)
        cfg_grid.addWidget(self.region_combo, 1, 0)

        self.currency_combo = QComboBox()
        for sym, code in CURRENCY_CHOICES:
            self.currency_combo.addItem(f"{sym} ({code})", userData=(sym, code))
        self.currency_combo.currentIndexChanged.connect(self._on_custom_tariff_edited)
        cfg_grid.addWidget(self.currency_combo, 1, 1)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.001, 5000.0)
        self.rate_spin.setDecimals(3)
        self.rate_spin.setSingleStep(0.01)
        self.rate_spin.valueChanged.connect(self._on_custom_tariff_edited)
        cfg_grid.addWidget(self.rate_spin, 1, 2)

        self.carbon_spin = QDoubleSpinBox()
        self.carbon_spin.setRange(0.0, 2000.0)
        self.carbon_spin.setDecimals(1)
        self.carbon_spin.setSuffix(" g/kWh")
        self.carbon_spin.setSingleStep(10.0)
        self.carbon_spin.valueChanged.connect(self._on_custom_tariff_edited)
        cfg_grid.addWidget(self.carbon_spin, 1, 3)

        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0.5, 24.0)
        self.hours_spin.setDecimals(1)
        self.hours_spin.setSuffix(" h/day")
        self.hours_spin.setSingleStep(0.5)
        self.hours_spin.valueChanged.connect(self._on_custom_tariff_edited)
        cfg_grid.addWidget(self.hours_spin, 1, 4)

        v.addWidget(cfg_card)
        self._sync_tariff_widgets_from_model()

        # 4 Financial & Carbon Projection Cards
        proj_row = QHBoxLayout()
        proj_row.setSpacing(12)
        self.proj_hourly = KpiCard("LIVE BURN RATE", "#10B981")
        self.proj_daily = KpiCard("PROJECTED DAILY", "#06B6D4")
        self.proj_monthly = KpiCard("PROJECTED MONTHLY BILL", "#8B5CF6")
        self.proj_yearly = KpiCard("PROJECTED ANNUAL BILL", "#F43F5E")
        for c in (self.proj_hourly, self.proj_daily, self.proj_monthly, self.proj_yearly):
            proj_row.addWidget(c, stretch=1)
        v.addLayout(proj_row)

        # 4 Real-World Environmental Equivalents Cards (Monthly Footprint)
        eq_card = QFrame()
        eq_card.setObjectName("Card")
        eq_v = QVBoxLayout(eq_card)
        eq_v.setContentsMargins(16, 14, 16, 14)
        eq_v.setSpacing(10)

        eq_title = QLabel("Monthly Environmental Impact Equivalents (at Current Load & Schedule)")
        eq_title.setObjectName("SectionTitle")
        eq_v.addWidget(eq_title)

        eq_row = QHBoxLayout()
        eq_row.setSpacing(12)
        self.eq_phones = KpiCard("📱 SMARTPHONE CHARGES", "#06B6D4")
        self.eq_car = KpiCard("🚗 PASSENGER CAR DRIVEN", "#F59E0B")
        self.eq_trees = KpiCard("🌳 TREE ABSORPTION EFFORT", "#10B981")
        self.eq_bulbs = KpiCard("💡 9W LED BULB RUNTIME", "#8B5CF6")
        for c in (self.eq_phones, self.eq_car, self.eq_trees, self.eq_bulbs):
            eq_row.addWidget(c, stretch=1)
        eq_v.addLayout(eq_row)
        v.addWidget(eq_card)

        # Historical Consumption Chart Card
        hist_card = QFrame()
        hist_card.setObjectName("Card")
        hv = QVBoxLayout(hist_card)
        hv.setContentsMargins(16, 14, 16, 14)
        hv.setSpacing(10)

        h_bar = QHBoxLayout()
        h_title = QLabel("Historical Consumption, Cost & CO₂e")
        h_title.setObjectName("SectionTitle")
        h_bar.addWidget(h_title)
        h_bar.addStretch()

        self.period_btns: dict[str, QPushButton] = {}
        for key, lbl in [("24h", "Last 24h"), ("7d", "7 Days"), ("30d", "30 Days")]:
            b = QPushButton(lbl)
            b.setObjectName("SegmentButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._set_history_period(k))
            h_bar.addWidget(b)
            self.period_btns[key] = b

        h_bar.addSpacing(12)

        self.metric_btns: dict[str, QPushButton] = {}
        for key, lbl in [("energy", "Energy (Wh)"), ("cost", "Cost"), ("carbon", "CO₂e")]:
            b = QPushButton(lbl)
            b.setObjectName("SegmentButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._set_history_metric(k))
            h_bar.addWidget(b)
            self.metric_btns[key] = b

        hv.addLayout(h_bar)
        self.history_chart = HistoryBarChart(palette=self.palette_theme)
        hv.addWidget(self.history_chart, stretch=1)
        v.addWidget(hist_card, stretch=1)

        self._update_segment_styles()
        self._refresh_history_chart()

        return self._wrap_scroll(page)

    # ------------------------------------------------------------------
    # Page 3: Platform & Export
    # ------------------------------------------------------------------

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(16)

        t = QLabel("Platform Diagnostics, Preferences & Export")
        t.setObjectName("PageTitle")
        sub = QLabel(
            "Manage sampling cadence, visual theme, CSV/JSON reporting, and inspect native hardware telemetry drivers."
        )
        sub.setObjectName("MutedLabel")
        v.addWidget(t)
        v.addWidget(sub)

        # Preferences & Export Row
        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        pref_card = QFrame()
        pref_card.setObjectName("Card")
        pv = QVBoxLayout(pref_card)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(12)

        p_title = QLabel("Application Preferences")
        p_title.setObjectName("SectionTitle")
        pv.addWidget(p_title)

        iv_row = QHBoxLayout()
        iv_row.addWidget(QLabel("Telemetry Sampling Interval:"))
        self.interval_combo = QComboBox()
        for sec, label in [
            (1.0, "1.0 second (High Resolution)"),
            (2.0, "2.0 seconds (Balanced — Recommended)"),
            (5.0, "5.0 seconds (Ultra-Low Overhead)"),
        ]:
            self.interval_combo.addItem(label, userData=sec)
            if abs(sec - self.sample_interval) < 0.2:
                self.interval_combo.setCurrentIndex(self.interval_combo.count() - 1)
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        iv_row.addWidget(self.interval_combo)
        pv.addLayout(iv_row)

        th_row = QHBoxLayout()
        th_row.addWidget(QLabel("Interface Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Obsidian Dark", userData="dark")
        self.theme_combo.addItem("Daylight Frost", userData="light")
        self.theme_combo.setCurrentIndex(1 if not self.palette_theme.is_dark else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        th_row.addWidget(self.theme_combo)
        pv.addLayout(th_row)

        self.tray_checkbox = QCheckBox("Keep running in system tray when closing window")
        self.tray_checkbox.setChecked(self.minimize_to_tray)
        self.tray_checkbox.toggled.connect(self._on_tray_toggled)
        pv.addWidget(self.tray_checkbox)

        reset_btn = QPushButton("Reset Current Session Energy Counter")
        reset_btn.setObjectName("ActionButton")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_session)
        pv.addWidget(reset_btn)
        pv.addStretch()
        top_row.addWidget(pref_card, stretch=1)

        exp_card = QFrame()
        exp_card.setObjectName("Card")
        ev = QVBoxLayout(exp_card)
        ev.setContentsMargins(16, 14, 16, 14)
        ev.setSpacing(12)

        e_title = QLabel("Export Telemetry & Cost Reports")
        e_title.setObjectName("SectionTitle")
        ev.addWidget(e_title)

        e_desc = QLabel(
            "Export timestamped wattage, energy (Wh), electricity cost, and carbon emissions (g CO₂e) for spreadsheets or sustainability reporting."
        )
        e_desc.setObjectName("MutedLabel")
        e_desc.setWordWrap(True)
        ev.addWidget(e_desc)

        btn_csv = QPushButton("📄  Export CSV Telemetry Log (30 Days)")
        btn_csv.setObjectName("PrimaryButton")
        btn_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_csv.clicked.connect(self._export_csv_dialog)
        ev.addWidget(btn_csv)

        btn_json = QPushButton("📦  Export JSON Summary && Device Snapshot")
        btn_json.setObjectName("ActionButton")
        btn_json.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_json.clicked.connect(self._export_json_dialog)
        ev.addWidget(btn_json)

        self.export_status_lbl = QLabel("")
        self.export_status_lbl.setObjectName("MutedLabel")
        self.export_status_lbl.setWordWrap(True)
        ev.addWidget(self.export_status_lbl)
        ev.addStretch()
        top_row.addWidget(exp_card, stretch=1)

        v.addLayout(top_row)

        # Platform Sensor Diagnostics Card
        diag_card = QFrame()
        diag_card.setObjectName("Card")
        dv = QVBoxLayout(diag_card)
        dv.setContentsMargins(16, 14, 16, 14)
        dv.setSpacing(8)

        d_title = QLabel("Cross-Platform Hardware Sensor Diagnostics")
        d_title.setObjectName("SectionTitle")
        dv.addWidget(d_title)

        self.diag_info_lbl = QLabel("Collecting sensor diagnostics…")
        self.diag_info_lbl.setWordWrap(True)
        self.diag_info_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dv.addWidget(self.diag_info_lbl)

        tips = QLabel(
            "Supported Native Hardware Backends:\n"
            "• Linux (x86_64 & ARM64 / Asahi): /sys/class/power_supply (BAT*, Mains, USB-C PD), Intel/AMD RAPL powercap, "
            "NVIDIA NVML/SMI + pmon, DRM amdgpu/i915 hwmon, backlight. (Tip: To unlock direct unprivileged CPU RAPL counters on Linux, "
            "run: sudo chmod o+r /sys/class/powercap/intel-rapl*/energy_uj)\n"
            "• Windows 10/11 (x64 & ARM64): Win32 GetSystemPowerStatus, WMI BatteryStatus (DischargeRate/ChargeRate), "
            "Windows Energy Meter Interface (EMI), NVIDIA NVML/SMI, WmiMonitorBrightness, and LibreHardwareMonitor WMI.\n"
            "• macOS Apple Silicon (M1/M2/M3/M4+) & Intel Mac: Unprivileged IOKit AppleSmartBattery TelemetryData "
            "(direct wall & battery SystemLoad), P/E-core + GPU + ANE SoC modeling, plus automatic upgrade to powermetrics when run as root."
        )
        tips.setObjectName("MutedLabel")
        tips.setWordWrap(True)
        dv.addWidget(tips)
        dv.addStretch()

        v.addWidget(diag_card, stretch=1)
        return self._wrap_scroll(page)

    # ------------------------------------------------------------------
    # System Tray
    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        self.tray_icon: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.app_icon, self)
        menu = QMenu()
        act_show = QAction("Open WattWise", self)
        act_show.triggered.connect(self._restore_from_tray)
        act_quit = QAction("Quit WattWise", self)
        act_quit.triggered.connect(self.quit_application)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.setToolTip(f"{__app_name__} v{__version__}")
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self.tray_icon = tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    # ------------------------------------------------------------------
    # Navigation, Theme & Controls
    # ------------------------------------------------------------------

    def switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 2:
            self._refresh_history_chart()

    def _apply_theme(self, theme_name: str) -> None:
        self.palette_theme = get_palette(theme_name)
        self.setStyleSheet(build_stylesheet(self.palette_theme))
        self.radial_gauge.set_palette_theme(self.palette_theme)
        self.live_chart.set_palette_theme(self.palette_theme)
        self.device_bars.set_palette_theme(self.palette_theme)
        self.history_chart.set_palette_theme(self.palette_theme)
        self.storage.save_pref("theme", self.palette_theme.name)

    def _toggle_theme(self) -> None:
        nxt = "light" if self.palette_theme.is_dark else "dark"
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(1 if nxt == "light" else 0)
        self.theme_combo.blockSignals(False)
        self._apply_theme(nxt)

    def _on_theme_combo_changed(self) -> None:
        theme_key = str(self.theme_combo.currentData() or "dark")
        self._apply_theme(theme_key)

    def _toggle_pause(self) -> None:
        paused = not self.worker.is_paused
        self.worker.set_paused(paused)
        self.pause_btn.setText("Resume" if paused else "Pause")
        if paused:
            self.sidebar_live_lbl.setText("⏸ Paused")
            self.sidebar_live_lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #F59E0B;")
        else:
            self.sidebar_live_lbl.setText("● Sampling Live")
            self.sidebar_live_lbl.setStyleSheet("font-weight: 700; font-size: 12px; color: #10B981;")

    def _on_interval_changed(self) -> None:
        sec = float(self.interval_combo.currentData() or 2.0)
        self.sample_interval = sec
        self.worker.set_interval(sec)
        self.storage.save_pref("sample_interval", sec)

    def _on_tray_toggled(self, checked: bool) -> None:
        self.minimize_to_tray = bool(checked)
        self.storage.save_pref("minimize_to_tray", self.minimize_to_tray)

    def _reset_session(self) -> None:
        self.engine.reset_session()
        self.live_chart.clear_samples()
        self.radial_gauge.peak_watts = 0.0

    # ------------------------------------------------------------------
    # Tariff & History Controls
    # ------------------------------------------------------------------

    def _sync_tariff_widgets_from_model(self) -> None:
        self._updating_tariff_ui = True
        try:
            # Region combo
            r_idx = self.region_combo.findData(self.tariff.region_key)
            if r_idx >= 0:
                self.region_combo.setCurrentIndex(r_idx)
            # Currency combo
            for i in range(self.currency_combo.count()):
                sym, _code = self.currency_combo.itemData(i)
                if sym == self.tariff.currency_symbol:
                    self.currency_combo.setCurrentIndex(i)
                    break
            self.rate_spin.setValue(self.tariff.rate_per_kwh)
            self.carbon_spin.setValue(self.tariff.carbon_g_per_kwh)
            self.hours_spin.setValue(self.tariff.daily_active_hours_est)
        finally:
            self._updating_tariff_ui = False
        self._update_tariff_pill()

    def _update_tariff_pill(self) -> None:
        sym = self.tariff.currency_symbol
        self.tariff_pill_btn.setText(
            f"⚡ {sym}{self.tariff.rate_per_kwh:.3f}/kWh  •  {self.tariff.carbon_g_per_kwh:.0f} g CO₂/kWh"
        )

    def _on_region_preset_changed(self) -> None:
        if self._updating_tariff_ui:
            return
        key = str(self.region_combo.currentData() or "us_avg")
        preset = REGIONAL_PRESETS.get(key)
        if preset and key != "custom":
            keep_hrs = self.tariff.daily_active_hours_est
            self.tariff = TariffProfile(**preset.to_dict())
            self.tariff.daily_active_hours_est = keep_hrs
            self._sync_tariff_widgets_from_model()
            self.storage.save_tariff(self.tariff)
            self._refresh_all_views()

    def _on_custom_tariff_edited(self) -> None:
        if self._updating_tariff_ui:
            return
        sym, code = self.currency_combo.currentData() or ("$", "USD")
        self.tariff.currency_symbol = sym
        self.tariff.currency_code = code
        self.tariff.rate_per_kwh = float(self.rate_spin.value())
        self.tariff.carbon_g_per_kwh = float(self.carbon_spin.value())
        self.tariff.daily_active_hours_est = float(self.hours_spin.value())
        self.storage.save_tariff(self.tariff)
        self._update_tariff_pill()
        self._refresh_all_views()

    def _set_history_period(self, period: str) -> None:
        self._history_period = period
        self._update_segment_styles()
        self._refresh_history_chart()

    def _set_history_metric(self, metric: str) -> None:
        self._history_metric = metric
        self._update_segment_styles()
        self._refresh_history_chart()

    def _update_segment_styles(self) -> None:
        for k, btn in self.period_btns.items():
            btn.setProperty("active", "true" if k == self._history_period else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        for k, btn in self.metric_btns.items():
            btn.setProperty("active", "true" if k == self._history_metric else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_history_chart(self) -> None:
        if self._history_period == "24h":
            buckets = self.storage.get_hourly_buckets(hours=24)
        elif self._history_period == "7d":
            buckets = self.storage.get_daily_buckets(days=7)
        else:
            buckets = self.storage.get_daily_buckets(days=30)
        self.history_chart.set_data(buckets, self._history_metric, self.tariff)

    # ------------------------------------------------------------------
    # Live Snapshot Updates
    # ------------------------------------------------------------------

    def _on_snapshot(self, snap: PowerSnapshot) -> None:
        self.latest_snapshot = snap
        self.live_chart.append_sample(snap.timestamp, snap.total_watts, snap.cpu_watts, snap.gpu_watts)
        self._refresh_all_views()

    def _refresh_all_views(self) -> None:
        snap = self.latest_snapshot
        if snap is None:
            return

        sym = self.tariff.currency_symbol
        today = self.storage.get_today_totals()
        today_wh = max(today["energy_wh"], snap.session_energy_wh)

        impact = calculate_impact(
            energy_wh=today_wh,
            live_watts=snap.total_watts,
            profile=self.tariff,
            use_monthly_for_equivalents=True,
        )

        # Sidebar & Header
        self.sidebar_session_lbl.setText(
            f"Session: {_format_duration(snap.session_duration_sec)} ({format_energy(snap.session_energy_wh)})"
        )
        self.dash_subtitle_lbl.setText(
            f"{snap.platform_name}  •  Source: {snap.primary_source}  •  Updated {dt.datetime.fromtimestamp(snap.timestamp).strftime('%H:%M:%S')}"
        )

        # Top 4 KPI Cards
        self.kpi_power.set_metrics(
            f"{snap.total_watts:.1f} W",
            f"Peak {max(self.engine.peak_watts, today['peak_watts']):.1f} W  •  CPU {snap.cpu_watts:.1f}W / GPU {snap.gpu_watts:.1f}W",
        )
        self.kpi_energy.set_metrics(
            format_energy(today_wh),
            f"Session {format_energy(snap.session_energy_wh)}  •  Avg {today['avg_watts'] or snap.total_watts:.1f} W",
        )
        self.kpi_cost.set_metrics(
            format_currency(impact.cost, sym),
            f"Est. {format_currency(impact.projected_monthly_cost, sym)}/mo ({self.tariff.daily_active_hours_est:.0f}h/d)",
        )
        self.kpi_carbon.set_metrics(
            format_carbon(impact.carbon_grams),
            f"Est. {impact.projected_monthly_co2_kg:.2f} kg CO₂e / mo",
        )

        # Radial Gauge & Battery Card
        co2_hr = (snap.total_watts / 1000.0) * self.tariff.carbon_g_per_kwh
        self.radial_gauge.update_reading(
            watts=snap.total_watts,
            peak_watts=self.engine.peak_watts,
            sensor_mode=snap.sensor_mode,
            burn_text=f"{format_currency(impact.burn_rate_per_hour, sym)} / hr",
            co2_rate_text=f"{co2_hr:.1f} g CO₂e / hr",
        )

        bat = snap.battery
        if bat.present:
            icon = "🔌" if bat.ac_connected else "🔋"
            self.bat_title_lbl.setText(f"{icon} {bat.status} — {bat.percent:.0f}%")
            bits: list[str] = []
            if bat.energy_now_wh is not None and bat.energy_full_wh is not None:
                bits.append(f"{bat.energy_now_wh:.1f}/{bat.energy_full_wh:.1f} Wh")
            if bat.health_pct is not None:
                bits.append(f"Health {min(100.0, bat.health_pct):.0f}%")
            if bat.voltage_v is not None:
                bits.append(f"{bat.voltage_v:.2f}V")
            if bat.cycle_count is not None:
                bits.append(f"{bat.cycle_count} cycles")
            if bat.time_remaining_min is not None:
                hrs, mins = divmod(int(bat.time_remaining_min), 60)
                bits.append(f"~{hrs}h {mins:02d}m left")
            if bat.model_name:
                bits.append(bat.model_name)
            self.bat_detail_lbl.setText("  •  ".join(bits))
        else:
            self.bat_title_lbl.setText("🔌 AC Mains Power (Desktop)")
            self.bat_detail_lbl.setText("Direct wall/PSU operation • No internal battery pack")

        # Device Breakdown Bars
        self.device_bars.update_devices(snap.components, snap.total_watts)

        # Page 1: Hardware Table & Apps Table
        self._refresh_hw_table(snap)
        self._refresh_apps_table()

        # Page 2: Cost & Carbon Projections + Equivalents
        self.proj_hourly.set_metrics(
            f"{format_currency(impact.burn_rate_per_hour, sym)} / hr",
            f"{co2_hr:.1f} g CO₂e / hr at {snap.total_watts:.1f} W",
        )
        self.proj_daily.set_metrics(
            format_currency(impact.projected_daily_cost, sym),
            f"{impact.projected_daily_kwh * 1000.0:.0f} Wh  •  {impact.projected_daily_kwh * self.tariff.carbon_g_per_kwh:.0f} g CO₂e",
        )
        self.proj_monthly.set_metrics(
            format_currency(impact.projected_monthly_cost, sym),
            f"{impact.projected_monthly_kwh:.2f} kWh  •  {impact.projected_monthly_co2_kg:.2f} kg CO₂e",
        )
        self.proj_yearly.set_metrics(
            format_currency(impact.projected_yearly_cost, sym),
            f"{impact.projected_monthly_kwh * 12.17:.1f} kWh  •  {impact.projected_monthly_co2_kg * 12.17:.1f} kg CO₂e",
        )

        self.eq_phones.set_metrics(
            f"{impact.equiv_phone_charges:.0f} charges",
            "Full smartphone charges / mo",
        )
        self.eq_car.set_metrics(
            f"{impact.equiv_car_km:.1f} km",
            "Avg passenger car tailpipe CO₂ / mo",
        )
        self.eq_trees.set_metrics(
            f"{impact.equiv_tree_days:.1f} tree-days",
            "Mature tree CO₂ absorption / mo",
        )
        self.eq_bulbs.set_metrics(
            f"{impact.equiv_led_bulb_hours:.0f} hrs",
            "9W LED bulb runtime / mo",
        )

        if self.pages.currentIndex() == 2:
            self._refresh_history_chart()

        # Page 3: Diagnostics
        all_stats = self.storage.get_all_time_totals()
        notes_txt = "\n".join(f"  • {n}" for n in snap.diagnostics) if snap.diagnostics else "  • Standard telemetry active"
        self.diag_info_lbl.setText(
            f"Collector Backend: {type(self.engine.collector).__name__} ({snap.platform_name})  |  GUI: Qt6 ({QT_BINDING})\n"
            f"SQLite Database: {self.storage.db_path} ({int(all_stats['samples'])} stored samples, {format_energy(all_stats['energy_wh'])} cumulative)\n"
            f"Active Sensor Notes:\n{notes_txt}"
        )

        # System Tray Tooltip
        if self.tray_icon is not None:
            self.tray_icon.setToolTip(
                f"{__app_name__}: {snap.total_watts:.1f} W  •  {format_currency(impact.burn_rate_per_hour, sym)}/hr  •  {co2_hr:.1f} g CO₂/hr"
            )

    def _refresh_hw_table(self, snap: PowerSnapshot) -> None:
        comps = sorted(snap.components, key=lambda c: c.watts, reverse=True)
        self.hw_table.setRowCount(len(comps))
        sym = self.tariff.currency_symbol

        for row, c in enumerate(comps):
            _, m_cost, m_co2 = monthly_projection_for_watts(c.watts, self.tariff)
            load_info = " / ".join(
                x
                for x in [
                    f"{c.utilization_pct:.0f}%" if c.utilization_pct is not None else "",
                    c.extra_info,
                ]
                if x
            ) or "—"
            temp_str = f"{c.temperature_c:.1f} °C" if c.temperature_c is not None else "—"
            share_pct = (c.watts / max(0.1, snap.total_watts)) * 100.0

            cells = [
                c.name,
                c.category.upper(),
                c.sensor_source,
                load_info,
                temp_str,
                f"{c.watts:.2f} W ({share_pct:.0f}%)",
                format_energy(c.energy_wh),
                f"{format_currency(m_cost, sym)} • {m_co2:.2f} kg",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col >= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.hw_table.setItem(row, col, item)

    def _refresh_apps_table(self) -> None:
        snap = self.latest_snapshot
        if snap is None:
            return
        query = self.app_search_edit.text().strip().lower()
        procs = [
            p for p in snap.processes if (not query or query in p.app_name.lower())
        ]
        self.app_table.setRowCount(len(procs))
        sym = self.tariff.currency_symbol

        for row, p in enumerate(procs):
            _, m_cost, _ = monthly_projection_for_watts(p.watts, self.tariff)
            cells = [
                p.app_name,
                str(p.pid_count),
                f"{p.cpu_pct:.1f}%",
                f"{p.gpu_pct:.1f}%" if p.gpu_pct > 0 else "—",
                f"{p.memory_mb:.0f} MB",
                f"{p.watts:.2f} W",
                format_energy(p.energy_wh),
                format_currency(m_cost, sym),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col >= 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.app_table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Export & Lifecycle
    # ------------------------------------------------------------------

    def _export_csv_dialog(self) -> None:
        default_name = f"wattwise_telemetry_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV Power & Carbon Log",
            str(Path.home() / default_name),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        count = self.storage.export_csv(path, self.tariff, days=30)
        self.export_status_lbl.setText(f"✅ Exported {count} samples to {path}")

    def _export_json_dialog(self) -> None:
        default_name = f"wattwise_report_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON Power & Carbon Report",
            str(Path.home() / default_name),
            "JSON Files (*.json)",
        )
        if not path:
            return
        self.storage.export_json(path, self.latest_snapshot, self.tariff, days=30)
        self.export_status_lbl.setText(f"✅ Exported JSON report to {path}")

    def quit_application(self) -> None:
        self._force_quit = True
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if (
            not self._force_quit
            and self.minimize_to_tray
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        ):
            self.hide()
            event.ignore()
            return

        self.worker.stop()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.storage.close()
        event.accept()
