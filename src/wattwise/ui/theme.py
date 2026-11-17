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
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
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
    bg_window="#0B1120",
    bg_sidebar="#080D1A",
    bg_card="#111827",
    bg_card_alt="#172033",
    bg_input="#0F172A",
    border="#1E293B",
    border_strong="#334155",
    text_primary="#F8FAFC",
    text_secondary="#CBD5E1",
    text_muted="#94A3B8",
    accent_emerald="#10B981",
    accent_cyan="#06B6D4",
    accent_violet="#8B5CF6",
    accent_amber="#F59E0B",
    accent_rose="#F43F5E",
    accent_blue="#3B82F6",
    grid_line="#1E293B",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    bg_window="#F1F5F9",
    bg_sidebar="#FFFFFF",
    bg_card="#FFFFFF",
    bg_card_alt="#F8FAFC",
    bg_input="#F8FAFC",
    border="#E2E8F0",
    border_strong="#CBD5E1",
    text_primary="#0F172A",
    text_secondary="#334155",
    text_muted="#64748B",
    accent_emerald="#059669",
    accent_cyan="#0891B2",
    accent_violet="#7C3AED",
    accent_amber="#D97706",
    accent_rose="#E11D48",
    accent_blue="#2563EB",
    grid_line="#E2E8F0",
)

CATEGORY_COLORS: dict[str, str] = {
    "cpu": "#06B6D4",
    "gpu": "#8B5CF6",
    "ane": "#EC4899",
    "display": "#F59E0B",
    "memory": "#10B981",
    "storage": "#3B82F6",
    "network": "#64748B",
    "battery_charge": "#14B8A6",
    "other": "#94A3B8",
}


def get_palette(name: str) -> ThemePalette:
    return LIGHT_PALETTE if (name or "").lower() == "light" else DARK_PALETTE


def build_stylesheet(p: ThemePalette) -> str:
    """Build complete QSS stylesheet for the main window and child controls."""
    nav_hover = "#162036" if p.is_dark else "#F1F5F9"
    nav_active_bg = "#132A2E" if p.is_dark else "#ECFDF5"
    btn_primary_bg = p.accent_emerald
    btn_primary_hover = "#059669" if p.is_dark else "#047857"

    return f"""
    QMainWindow, QWidget#RootContainer {{
        background-color: {p.bg_window};
        color: {p.text_primary};
        font-family: "Inter", "Segoe UI", "SF Pro Text", "Ubuntu", sans-serif;
        font-size: 13px;
    }}

    QFrame#Sidebar {{
        background-color: {p.bg_sidebar};
        border-right: 1px solid {p.border};
    }}

    QFrame#Card {{
        background-color: {p.bg_card};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}

    QFrame#SubCard {{
        background-color: {p.bg_card_alt};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}

    QLabel {{
        color: {p.text_primary};
        background: transparent;
    }}

    QLabel#MutedLabel {{
        color: {p.text_muted};
        font-size: 12px;
    }}

    QLabel#SectionTitle {{
        color: {p.text_primary};
        font-size: 15px;
        font-weight: 700;
    }}

    QLabel#PageTitle {{
        color: {p.text_primary};
        font-size: 20px;
        font-weight: 700;
    }}

    QPushButton#NavButton {{
        text-align: left;
        padding: 10px 14px;
        border-radius: 9px;
        border: 1px solid transparent;
        background-color: transparent;
        color: {p.text_secondary};
        font-size: 13px;
        font-weight: 600;
    }}

    QPushButton#NavButton:hover {{
        background-color: {nav_hover};
        color: {p.text_primary};
    }}

    QPushButton#NavButton[active="true"] {{
        background-color: {nav_active_bg};
        border: 1px solid {p.accent_emerald};
        color: {p.accent_emerald};
        font-weight: 700;
    }}

    QPushButton#ActionButton {{
        background-color: {p.bg_card_alt};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        padding: 7px 14px;
        color: {p.text_primary};
        font-weight: 600;
    }}

    QPushButton#ActionButton:hover {{
        border-color: {p.accent_cyan};
    }}

    QPushButton#PrimaryButton {{
        background-color: {btn_primary_bg};
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        color: #FFFFFF;
        font-weight: 700;
    }}

    QPushButton#PrimaryButton:hover {{
        background-color: {btn_primary_hover};
    }}

    QPushButton#SegmentButton {{
        background-color: {p.bg_input};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 5px 12px;
        color: {p.text_muted};
        font-size: 12px;
        font-weight: 600;
    }}

    QPushButton#SegmentButton[active="true"] {{
        background-color: {nav_active_bg};
        border: 1px solid {p.accent_emerald};
        color: {p.accent_emerald};
    }}

    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
        background-color: {p.bg_input};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        padding: 6px 10px;
        color: {p.text_primary};
        selection-background-color: {p.accent_emerald};
    }}

    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
        border: 1px solid {p.accent_cyan};
    }}

    QComboBox QAbstractItemView {{
        background-color: {p.bg_card};
        color: {p.text_primary};
        border: 1px solid {p.border_strong};
        selection-background-color: {p.accent_emerald};
        selection-color: #FFFFFF;
    }}

    QTableWidget {{
        background-color: {p.bg_card};
        alternate-background-color: {p.bg_card_alt};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 10px;
        gridline-color: {p.border};
        selection-background-color: {nav_active_bg};
        selection-color: {p.text_primary};
    }}

    QHeaderView::section {{
        background-color: {p.bg_card_alt};
        color: {p.text_muted};
        font-weight: 700;
        font-size: 11px;
        text-transform: uppercase;
        padding: 8px 10px;
        border: none;
        border-bottom: 1px solid {p.border_strong};
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical {{
        background: {p.border_strong};
        border-radius: 4px;
        min-height: 24px;
    }}

    QCheckBox {{
        color: {p.text_primary};
        spacing: 8px;
    }}
    """
