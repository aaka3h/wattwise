"""Modern Dark and Light visual themes and Qt StyleSheets for WattWise."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    name: str
    is_dark: bool
    bg_window: str
    bg_sidebar: str
    bg_card: str
    bg_card_alt: str
    bg_input: str
    bg_elevated: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent_primary: str
    accent_emerald: str
    accent_cyan: str
    accent_violet: str
    accent_amber: str
    accent_rose: str
    accent_blue: str
    grid_line: str


DARK_PALETTE = ThemePalette(
    name="dark",
    is_dark=True,
    bg_window="#1C1C1E",
    bg_sidebar="#161618",
    bg_card="#2C2C2E",
    bg_card_alt="#3A3A3C",
    bg_input="#1C1C1E",
    bg_elevated="#3A3A3C",
    border="#38383A",
    border_strong="#48484A",
    text_primary="#F5F5F7",
    text_secondary="#AEAEB2",
    text_muted="#8E8E93",
    accent_primary="#007AFF",
    accent_emerald="#34C759",
    accent_cyan="#5AC8FA",
    accent_violet="#AF52DE",
    accent_amber="#FF9500",
    accent_rose="#FF3B30",
    accent_blue="#007AFF",
    grid_line="#2C2C2E",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    bg_window="#F2F2F7",
    bg_sidebar="#FFFFFF",
    bg_card="#FFFFFF",
    bg_card_alt="#F9F9FB",
    bg_input="#FFFFFF",
    bg_elevated="#FFFFFF",
    border="#D1D1D6",
    border_strong="#C7C7CC",
    text_primary="#1C1C1E",
    text_secondary="#3A3A3C",
    text_muted="#8E8E93",
    accent_primary="#007AFF",
    accent_emerald="#28CD41",
    accent_cyan="#55BEF0",
    accent_violet="#AF52DE",
    accent_amber="#FF9500",
    accent_rose="#FF3B30",
    accent_blue="#007AFF",
    grid_line="#E5E5EA",
)

CATEGORY_COLORS: dict[str, str] = {
    "cpu": "#5AC8FA",
    "gpu": "#AF52DE",
    "ane": "#FF2D55",
    "display": "#FF9500",
    "memory": "#34C759",
    "storage": "#007AFF",
    "network": "#8E8E93",
    "battery_charge": "#30D158",
    "other": "#AEAEB2",
}


def get_palette(name: str) -> ThemePalette:
    return LIGHT_PALETTE if (name or "").lower() == "light" else DARK_PALETTE


def build_stylesheet(p: ThemePalette) -> str:
    """Build complete QSS stylesheet for the main window and child controls."""
    # --- Computed contextual colours ---
    _font_stack = (
        '"SF Pro Display", "SF Pro Text", ".AppleSystemUIFont", '
        '"Helvetica Neue", "Segoe UI Variable", "Inter", sans-serif'
    )

    # Navigation button states
    nav_hover = "#2C2C2E" if p.is_dark else "#E5E5EA"
    # Translucent accent tint for active nav (pill highlight)
    nav_active_bg = "rgba(0, 122, 255, 0.15)" if p.is_dark else "rgba(0, 122, 255, 0.10)"

    # Segment control selected
    seg_active_bg = "#FFFFFF" if not p.is_dark else "#636366"

    # Primary button – system accent blue gradient
    btn_primary_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #0A84FF, stop:1 #0070E0)"
    ) if p.is_dark else (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #007AFF, stop:1 #0066DD)"
    )
    btn_primary_hover = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #409CFF, stop:1 #0A84FF)"
    ) if p.is_dark else (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        "stop:0 #3395FF, stop:1 #007AFF)"
    )
    btn_primary_pressed = "#005EC4" if p.is_dark else "#004EAA"

    # Secondary / action button
    action_bg = "#2C2C2E" if p.is_dark else "#F2F2F7"
    action_hover_border = p.accent_primary

    # Subtle alternating row tint (barely visible)
    table_alt = "#242426" if p.is_dark else "#F9F9FB"
    table_header_bg = "#1C1C1E" if p.is_dark else "#F2F2F7"
    table_selection = "rgba(0, 122, 255, 0.18)" if p.is_dark else "rgba(0, 122, 255, 0.12)"

    # Scrollbar handle
    scrollbar_handle = "rgba(142, 142, 147, 0.45)" if p.is_dark else "rgba(142, 142, 147, 0.35)"
    scrollbar_handle_hover = "rgba(142, 142, 147, 0.70)" if p.is_dark else "rgba(142, 142, 147, 0.55)"

    # Sidebar separator border
    sidebar_border = "#2C2C2E" if p.is_dark else "#D1D1D6"

    # Card shadow border (simulates elevation via double border trick)
    card_shadow_border = "rgba(0, 0, 0, 0.25)" if p.is_dark else "rgba(0, 0, 0, 0.06)"

    # Input field inset appearance
    input_border = "#48484A" if p.is_dark else "#C7C7CC"
    input_focus_border = p.accent_primary

    # ComboBox dropdown
    combo_drop_bg = p.bg_elevated
    combo_selection = p.accent_primary

    # Checkbox tick
    checkbox_check_bg = p.accent_primary

    # Segment control container bg
    seg_container_bg = "#1C1C1E" if p.is_dark else "#E5E5EA"

    return f"""
    /* ============================================================
       WattWise — macOS-inspired premium theme ({p.name})
       ============================================================ */

    /* --- Base window & root --- */
    QMainWindow, QWidget#RootContainer {{
        background-color: {p.bg_window};
        color: {p.text_primary};
        font-family: {_font_stack};
        font-size: 13px;
    }}

    /* --- Sidebar (frosted-glass feel) --- */
    QFrame#Sidebar {{
        background-color: {p.bg_sidebar};
        border-right: 1px solid {sidebar_border};
    }}

    /* --- Cards --- */
    QFrame#Card {{
        background-color: {p.bg_card};
        border: 1px solid {card_shadow_border};
        border-radius: 16px;
        padding: 4px;
    }}

    QFrame#SubCard {{
        background-color: {p.bg_card_alt};
        border: 1px solid {p.border};
        border-radius: 14px;
        padding: 2px;
    }}

    /* --- Typography --- */
    QLabel {{
        color: {p.text_primary};
        background: transparent;
    }}

    QLabel#MutedLabel {{
        color: {p.text_muted};
        font-size: 12px;
        letter-spacing: 0.2px;
    }}

    QLabel#SectionTitle {{
        color: {p.text_primary};
        font-size: 16px;
        font-weight: 700;
        letter-spacing: -0.2px;
    }}

    QLabel#PageTitle {{
        color: {p.text_primary};
        font-size: 24px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }}

    /* --- Sidebar navigation buttons (pill-shaped selection) --- */
    QPushButton#NavButton {{
        text-align: left;
        padding: 8px 16px;
        border-radius: 10px;
        border: none;
        background-color: transparent;
        color: {p.text_secondary};
        font-size: 13px;
        font-weight: 500;
    }}

    QPushButton#NavButton:hover {{
        background-color: {nav_hover};
        color: {p.text_primary};
    }}

    QPushButton#NavButton[active="true"] {{
        background-color: {nav_active_bg};
        border: none;
        color: {p.accent_primary};
        font-weight: 600;
    }}

    /* --- Primary button (system accent blue gradient) --- */
    QPushButton#PrimaryButton {{
        background: {btn_primary_bg};
        border: none;
        border-radius: 10px;
        padding: 9px 20px;
        color: #FFFFFF;
        font-weight: 600;
        font-size: 13px;
    }}

    QPushButton#PrimaryButton:hover {{
        background: {btn_primary_hover};
    }}

    QPushButton#PrimaryButton:pressed {{
        background-color: {btn_primary_pressed};
    }}

    /* --- Secondary / action button --- */
    QPushButton#ActionButton {{
        background-color: {action_bg};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 8px 16px;
        color: {p.text_primary};
        font-weight: 500;
        font-size: 13px;
    }}

    QPushButton#ActionButton:hover {{
        border-color: {action_hover_border};
        color: {p.accent_primary};
    }}

    QPushButton#ActionButton:pressed {{
        background-color: {p.bg_card_alt};
    }}

    /* --- Segmented controls (rounded pill toggles) --- */
    QPushButton#SegmentButton {{
        background-color: {seg_container_bg};
        border: none;
        border-radius: 8px;
        padding: 6px 14px;
        color: {p.text_muted};
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#SegmentButton[active="true"] {{
        background-color: {seg_active_bg};
        border: none;
        color: {p.text_primary};
        font-weight: 600;
    }}

    /* --- Inputs (macOS rounded inset) --- */
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
        background-color: {p.bg_input};
        border: 1px solid {input_border};
        border-radius: 8px;
        padding: 7px 12px;
        color: {p.text_primary};
        font-size: 13px;
        selection-background-color: {p.accent_primary};
        selection-color: #FFFFFF;
    }}

    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
        border: 2px solid {input_focus_border};
        padding: 6px 11px;
    }}

    QComboBox::drop-down {{
        border: none;
        padding-right: 8px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {combo_drop_bg};
        color: {p.text_primary};
        border: 1px solid {p.border_strong};
        border-radius: 10px;
        padding: 4px;
        selection-background-color: {combo_selection};
        selection-color: #FFFFFF;
    }}

    /* --- Tables (subtle alternating rows) --- */
    QTableWidget {{
        background-color: {p.bg_card};
        alternate-background-color: {table_alt};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 12px;
        gridline-color: transparent;
        selection-background-color: {table_selection};
        selection-color: {p.text_primary};
        font-size: 13px;
    }}

    QHeaderView::section {{
        background-color: {table_header_bg};
        color: {p.text_muted};
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        padding: 10px 12px;
        border: none;
        border-bottom: 1px solid {p.border};
        letter-spacing: 0.5px;
    }}

    /* --- Scroll area --- */
    QScrollArea {{
        border: none;
        background: transparent;
    }}

    /* --- macOS-style thin overlay scrollbars --- */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 1px;
    }}

    QScrollBar::handle:vertical {{
        background: {scrollbar_handle};
        border-radius: 3px;
        min-height: 32px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {scrollbar_handle_hover};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 1px 4px;
    }}

    QScrollBar::handle:horizontal {{
        background: {scrollbar_handle};
        border-radius: 3px;
        min-width: 32px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {scrollbar_handle_hover};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    /* --- Checkbox --- */
    QCheckBox {{
        color: {p.text_primary};
        spacing: 8px;
        font-size: 13px;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1.5px solid {p.border_strong};
        background-color: {p.bg_input};
    }}

    QCheckBox::indicator:checked {{
        background-color: {checkbox_check_bg};
        border-color: {checkbox_check_bg};
    }}

    /* --- Tooltips --- */
    QToolTip {{
        background-color: {p.bg_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 12px;
    }}

    /* --- Tab widget --- */
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 10px;
        background-color: {p.bg_card};
    }}

    QTabBar::tab {{
        background-color: transparent;
        color: {p.text_muted};
        padding: 8px 16px;
        border: none;
        font-weight: 500;
        font-size: 13px;
    }}

    QTabBar::tab:selected {{
        color: {p.accent_primary};
        border-bottom: 2px solid {p.accent_primary};
        font-weight: 600;
    }}

    QTabBar::tab:hover {{
        color: {p.text_primary};
    }}

    /* --- Group box --- */
    QGroupBox {{
        border: 1px solid {p.border};
        border-radius: 12px;
        margin-top: 10px;
        padding-top: 18px;
        font-weight: 600;
        color: {p.text_primary};
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 6px;
        color: {p.text_secondary};
    }}
    """
