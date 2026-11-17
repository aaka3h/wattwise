"""GUI smoke & rendering tests for WattWiseMainWindow across tabs and themes."""

from __future__ import annotations

import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wattwise.collectors import PowerEngine
from wattwise.storage import WattWiseStorage
from wattwise.ui.main_window import WattWiseMainWindow
from wattwise.ui.qt_compat import QApplication


def test_main_window_tabs_themes_and_live_updates(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    store = WattWiseStorage(db_path=tmp_path / "ui_test.db")
    engine = PowerEngine(storage=store)

    win = WattWiseMainWindow(storage=store, engine=engine, start_worker=False)
    try:
        win.show()
        s1 = engine.sample()
        win._on_snapshot(s1)
        time.sleep(0.15)
        s2 = engine.sample()
        win._on_snapshot(s2)

        # Navigate across all 4 pages and trigger full paintEvent rendering
        for page_idx in range(4):
            win.switch_page(page_idx)
            app.processEvents()
            pix = win.grab()
            assert not pix.isNull()

        # Test filtering applications
        win.switch_page(1)
        win.app_search_edit.setText("python")
        app.processEvents()
        win.app_search_edit.setText("")
        app.processEvents()

        # Test Cost & Carbon preset switching & history toggles
        win.switch_page(2)
        ger_idx = win.region_combo.findData("germany")
        assert ger_idx >= 0
        win.region_combo.setCurrentIndex(ger_idx)
        app.processEvents()
        assert win.tariff.currency_symbol == "€"

        for period in ("24h", "7d", "30d"):
            win._set_history_period(period)
            app.processEvents()
        for metric in ("energy", "cost", "carbon"):
            win._set_history_metric(metric)
            app.processEvents()

        # Toggle Light & Dark themes
        win._toggle_theme()
        app.processEvents()
        assert win.palette_theme.name == "light"
        win._toggle_theme()
        app.processEvents()
        assert win.palette_theme.name == "dark"
    finally:
        win.quit_application()
