"""Custom high-DPI vector QPainter widgets for real-time power, device breakdown, and history charts."""

from __future__ import annotations

from collections import deque
import datetime as dt
import math
from typing import Optional

from wattwise.models import HardwareComponent, HistoricalBucket, TariffProfile
from wattwise.pricing import (
    energy_carbon_grams,
    energy_cost,
    format_carbon,
    format_currency,
    format_energy,
)
from wattwise.ui.qt_compat import (
    QColor,
    QFont,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPointF,
    QRectF,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
)
from wattwise.ui.theme import CATEGORY_COLORS, DARK_PALETTE, ThemePalette


class KpiCard(QFrame):
    """Compact metric card with top accent indicator, title, big value, and subtitle."""

    def __init__(
        self,
        title: str,
        accent_hex: str = "#10B981",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._accent_hex = accent_hex
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {accent_hex}; font-size: 11px;")
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("MutedLabel")
        self.title_lbl.setStyleSheet("font-weight: 600; font-size: 12px;")
        top_row.addWidget(self.dot)
        top_row.addWidget(self.title_lbl)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.value_lbl = QLabel("—")
        val_font = QFont()
        val_font.setPointSize(18)
        val_font.setBold(True)
        self.value_lbl.setFont(val_font)
        layout.addWidget(self.value_lbl)

        self.sub_lbl = QLabel("")
        self.sub_lbl.setObjectName("MutedLabel")
        layout.addWidget(self.sub_lbl)

    def set_metrics(self, primary: str, secondary: str) -> None:
        self.value_lbl.setText(primary)
        self.sub_lbl.setText(secondary)


class RadialPowerGauge(QWidget):
    """Smooth 240-degree radial arc gauge displaying instantaneous system wattage & burn rate."""

    def __init__(self, palette: ThemePalette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.watts: float = 0.0
        self.peak_watts: float = 0.0
        self.scale_max: float = 90.0
        self.sensor_mode: str = "hybrid"
        self.burn_text: str = "$0.0000 / hr"
        self.co2_rate_text: str = "0.0 g CO₂ / hr"
        self.setMinimumSize(230, 210)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.update()

    def update_reading(
        self,
        watts: float,
        peak_watts: float,
        sensor_mode: str,
        burn_text: str,
        co2_rate_text: str,
    ) -> None:
        self.watts = max(0.0, watts)
        self.peak_watts = max(self.peak_watts, peak_watts, self.watts)
        # Adaptive ceiling: 60W, 90W, 140W, 220W, 350W, 600W
        for cap in (60.0, 95.0, 150.0, 240.0, 380.0, 650.0):
            if self.peak_watts <= cap * 0.88:
                self.scale_max = cap
                break
        else:
            self.scale_max = max(650.0, math.ceil(self.peak_watts / 100.0) * 100.0)

        self.sensor_mode = sensor_mode
        self.burn_text = burn_text
        self.co2_rate_text = co2_rate_text
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        diameter = min(w - 28.0, h - 24.0)
        cx = w / 2.0
        cy = h / 2.0 + 8.0
        radius = max(50.0, diameter / 2.0 - 10.0)
        arc_rect = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)

        # 240 deg sweep from 210 deg clockwise to -30 deg (Qt uses 1/16th degree counter-clockwise)
        start_angle_deg = 210.0
        span_total_deg = -240.0
        pen_width = max(11.0, radius * 0.14)

        # Background track
        track_pen = QPen(QColor(self.palette.border_strong), pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(arc_rect, int(start_angle_deg * 16), int(span_total_deg * 16))

        # Active arc
        ratio = max(0.02, min(1.0, self.watts / max(1.0, self.scale_max)))
        grad = QLinearGradient(arc_rect.bottomLeft(), arc_rect.topRight())
        grad.setColorAt(0.0, QColor(self.palette.accent_emerald))
        grad.setColorAt(0.55, QColor(self.palette.accent_cyan))
        grad.setColorAt(1.0, QColor(self.palette.accent_amber if ratio < 0.82 else self.palette.accent_rose))

        val_pen = QPen(grad, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(val_pen)
        painter.drawArc(arc_rect, int(start_angle_deg * 16), int(span_total_deg * ratio * 16))

        # Center wattage value
        f_big = QFont()
        f_big.setPointSize(22)
        f_big.setBold(True)
        painter.setFont(f_big)
        painter.setPen(QColor(self.palette.text_primary))
        painter.drawText(
            QRectF(cx - radius, cy - 34.0, radius * 2.0, 36.0),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.watts:.1f} W",
        )

        # Burn rate & CO2/hr
        f_sub = QFont()
        f_sub.setPointSize(9)
        painter.setFont(f_sub)
        painter.setPen(QColor(self.palette.text_muted))
        painter.drawText(
            QRectF(cx - radius, cy + 4.0, radius * 2.0, 18.0),
            Qt.AlignmentFlag.AlignCenter,
            self.burn_text,
        )
        painter.drawText(
            QRectF(cx - radius, cy + 21.0, radius * 2.0, 18.0),
            Qt.AlignmentFlag.AlignCenter,
            self.co2_rate_text,
        )

        # Sensor mode pill at bottom of gauge
        mode_map = {
            "direct": ("DIRECT SENSOR", self.palette.accent_emerald),
            "hybrid": ("HYBRID SENSOR", self.palette.accent_cyan),
            "estimated": ("CALIBRATED MODEL", self.palette.accent_amber),
        }
        badge_txt, badge_hex = mode_map.get(self.sensor_mode, ("TELEMETRY", self.palette.accent_cyan))
        pill_rect = QRectF(cx - 64.0, cy + radius * 0.56, 128.0, 22.0)
        c_badge = QColor(badge_hex)
        bg_badge = QColor(c_badge)
        bg_badge.setAlpha(36 if self.palette.is_dark else 26)

        painter.setPen(QPen(c_badge, 1.0))
        painter.setBrush(bg_badge)
        painter.drawRoundedRect(pill_rect, 11.0, 11.0)

        f_pill = QFont()
        f_pill.setPointSize(8)
        f_pill.setBold(True)
        painter.setFont(f_pill)
        painter.setPen(c_badge)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, badge_txt)
        painter.end()


class LivePowerChart(QWidget):
    """Multi-series rolling real-time area chart (Total System, CPU, GPU) with hover crosshair."""

    def __init__(
        self,
        max_points: int = 180,
        palette: ThemePalette = DARK_PALETTE,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.palette = palette
        self.max_points = max_points
        self._samples: deque[tuple[float, float, float, float]] = deque(maxlen=max_points)
        self._hover_x: Optional[float] = None
        self.setMouseTracking(True)
        self.setMinimumHeight(215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.update()

    def append_sample(self, ts: float, total_w: float, cpu_w: float, gpu_w: float) -> None:
        self._samples.append((ts, max(0.0, total_w), max(0.0, cpu_w), max(0.0, gpu_w)))
        self.update()

    def clear_samples(self) -> None:
        self._samples.clear()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position() if hasattr(event, "position") else event.pos()
        self._hover_x = float(pos.x())
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover_x = None
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        left, top, right, bottom = 46.0, 28.0, 14.0, 24.0
        plot = QRectF(left, top, max(40.0, w - left - right), max(40.0, h - top - bottom))

        # Legend at top-right
        legend_items = [
            ("Total System", self.palette.accent_emerald, 108.0),
            ("CPU", self.palette.accent_cyan, 68.0),
            ("GPU", self.palette.accent_violet, 64.0),
        ]
        lx = plot.right() - 242.0
        f_leg = QFont()
        f_leg.setPointSize(9)
        f_leg.setBold(True)
        painter.setFont(f_leg)
        for label, hex_c, step_w in legend_items:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(hex_c))
            painter.drawEllipse(QPointF(lx, 12.0), 4.5, 4.5)
            painter.setPen(QColor(self.palette.text_secondary))
            painter.drawText(QRectF(lx + 9.0, 3.0, step_w - 12.0, 18.0), Qt.AlignmentFlag.AlignVCenter, label)
            lx += step_w

        pts = list(self._samples)
        max_val = max([p[1] for p in pts], default=30.0)
        y_max = max(20.0, math.ceil((max_val * 1.18) / 10.0) * 10.0)

        # Horizontal grid lines + Y labels
        f_axis = QFont()
        f_axis.setPointSize(8)
        painter.setFont(f_axis)
        grid_pen = QPen(QColor(self.palette.grid_line), 1.0, Qt.PenStyle.DashLine)
        for i in range(5):
            frac = i / 4.0
            y = plot.bottom() - frac * plot.height()
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            val = frac * y_max
            painter.setPen(QColor(self.palette.text_muted))
            painter.drawText(
                QRectF(2.0, y - 8.0, left - 8.0, 16.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{val:.0f}W",
            )

        if not pts:
            painter.setPen(QColor(self.palette.text_muted))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Collecting live hardware telemetry…")
            painter.end()
            return

        n = len(pts)

        def x_for(idx: int) -> float:
            if n == 1:
                return plot.right()
            # Anchor right-aligned or full-width once >= 2 samples
            span = max(1, n - 1)
            return plot.left() + (idx / span) * plot.width()

        def y_for(val: float) -> float:
            return plot.bottom() - min(1.0, max(0.0, val / y_max)) * plot.height()

        # Draw each series (GPU back, CPU mid, Total front)
        series_cfg = [
            (3, self.palette.accent_violet, 1.6, 26),
            (2, self.palette.accent_cyan, 1.8, 32),
            (1, self.palette.accent_emerald, 2.5, 52),
        ]
        for tup_idx, col_hex, width_px, fill_alpha in series_cfg:
            line_path = QPainterPath()
            area_path = QPainterPath()
            first_x = x_for(0)
            first_y = y_for(pts[0][tup_idx])
            line_path.moveTo(first_x, first_y)
            area_path.moveTo(first_x, plot.bottom())
            area_path.lineTo(first_x, first_y)

            for i in range(1, n):
                px = x_for(i)
                py = y_for(pts[i][tup_idx])
                line_path.lineTo(px, py)
                area_path.lineTo(px, py)

            last_x = x_for(n - 1)
            area_path.lineTo(last_x, plot.bottom())
            area_path.closeSubpath()

            fill_grad = QLinearGradient(QPointF(0, plot.top()), QPointF(0, plot.bottom()))
            c_top = QColor(col_hex)
            c_top.setAlpha(fill_alpha)
            c_bot = QColor(col_hex)
            c_bot.setAlpha(2)
            fill_grad.setColorAt(0.0, c_top)
            fill_grad.setColorAt(1.0, c_bot)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_grad)
            painter.drawPath(area_path)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(col_hex), width_px))
            painter.drawPath(line_path)

        # X-axis timestamps (start & latest)
        t_start = dt.datetime.fromtimestamp(pts[0][0]).strftime("%H:%M:%S")
        t_end = dt.datetime.fromtimestamp(pts[-1][0]).strftime("%H:%M:%S")
        painter.setPen(QColor(self.palette.text_muted))
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4.0, 90.0, 16.0), Qt.AlignmentFlag.AlignLeft, t_start)
        painter.drawText(QRectF(plot.right() - 90.0, plot.bottom() + 4.0, 90.0, 16.0), Qt.AlignmentFlag.AlignRight, t_end)

        # Hover crosshair & tooltip HUD
        if self._hover_x is not None and plot.left() <= self._hover_x <= plot.right() and n >= 1:
            rel = (self._hover_x - plot.left()) / max(1.0, plot.width())
            idx = max(0, min(n - 1, int(round(rel * max(1, n - 1)))))
            hx = x_for(idx)
            ts, tot_w, cpu_w, gpu_w = pts[idx]
            oth_w = max(0.0, tot_w - cpu_w - gpu_w)

            painter.setPen(QPen(QColor(self.palette.text_muted), 1.0, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(hx, plot.top()), QPointF(hx, plot.bottom()))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.palette.accent_emerald))
            painter.drawEllipse(QPointF(hx, y_for(tot_w)), 4.0, 4.0)

            tip_w, tip_h = 158.0, 74.0
            tx = hx + 12.0 if (hx + 12.0 + tip_w <= plot.right()) else (hx - tip_w - 12.0)
            ty = plot.top() + 8.0
            tip_rect = QRectF(tx, ty, tip_w, tip_h)

            bg = QColor(self.palette.bg_sidebar)
            bg.setAlpha(238)
            painter.setPen(QPen(QColor(self.palette.border_strong), 1.0))
            painter.setBrush(bg)
            painter.drawRoundedRect(tip_rect, 8.0, 8.0)

            t_str = dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            lines = [
                f"{t_str}  •  {tot_w:.1f} W",
                f"CPU: {cpu_w:.1f} W   GPU: {gpu_w:.1f} W",
                f"Other Devices: {oth_w:.1f} W",
            ]
            painter.setPen(QColor(self.palette.text_primary))
            f_tip = QFont()
            f_tip.setPointSize(8)
            f_tip.setBold(True)
            painter.setFont(f_tip)
            painter.drawText(QRectF(tx + 9.0, ty + 6.0, tip_w - 18.0, 18.0), Qt.AlignmentFlag.AlignLeft, lines[0])
            f_tip.setBold(False)
            painter.setFont(f_tip)
            painter.setPen(QColor(self.palette.text_secondary))
            painter.drawText(QRectF(tx + 9.0, ty + 27.0, tip_w - 18.0, 18.0), Qt.AlignmentFlag.AlignLeft, lines[1])
            painter.drawText(QRectF(tx + 9.0, ty + 46.0, tip_w - 18.0, 18.0), Qt.AlignmentFlag.AlignLeft, lines[2])

        painter.end()


class DeviceBreakdownWidget(QWidget):
    """Per-hardware-device horizontal power bars with live W, % share, temperature, and Wh."""

    def __init__(self, palette: ThemePalette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self._components: list[HardwareComponent] = []
        self._total_watts: float = 1.0
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.update()

    def update_devices(self, components: list[HardwareComponent], total_watts: float) -> None:
        self._components = sorted(components, key=lambda c: c.watts, reverse=True)
        self._total_watts = max(0.1, total_watts)
        row_h = 46
        needed = max(160, len(self._components) * row_h + 10)
        if self.minimumHeight() != needed:
            self.setMinimumHeight(needed)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        if not self._components:
            painter.setPen(QColor(self.palette.text_muted))
            painter.drawText(QRectF(0, 0, w, float(self.height())), Qt.AlignmentFlag.AlignCenter, "Probing hardware devices…")
            painter.end()
            return

        row_h = 45.0
        y = 4.0

        f_name = QFont()
        f_name.setPointSize(9)
        f_name.setBold(True)

        f_meta = QFont()
        f_meta.setPointSize(8)

        for comp in self._components:
            col_hex = CATEGORY_COLORS.get(comp.category, CATEGORY_COLORS["other"])
            share = max(0.0, min(1.0, comp.watts / self._total_watts))

            # Color dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(col_hex))
            painter.drawEllipse(QPointF(10.0, y + 10.0), 4.5, 4.5)

            # Device name + subtle metadata
            meta_bits: list[str] = []
            if comp.is_direct_sensor:
                meta_bits.append("Direct Sensor")
            if comp.utilization_pct is not None:
                meta_bits.append(f"{comp.utilization_pct:.0f}% load")
            if comp.temperature_c is not None:
                meta_bits.append(f"{comp.temperature_c:.0f}°C")
            if comp.extra_info:
                meta_bits.append(comp.extra_info)
            meta_str = "  •  ".join(meta_bits)

            painter.setFont(f_name)
            painter.setPen(QColor(self.palette.text_primary))
            name_text = comp.name
            if meta_str:
                name_text = f"{comp.name}   "
            painter.drawText(QRectF(22.0, y + 1.0, w * 0.62, 18.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name_text)

            # Right side live W + % + session Wh
            right_str = f"{comp.watts:.2f} W  ({share * 100.0:.0f}%)   •   {format_energy(comp.energy_wh)}"
            painter.setFont(f_name)
            painter.setPen(QColor(self.palette.text_primary))
            painter.drawText(
                QRectF(w - 250.0, y + 1.0, 242.0, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                right_str,
            )

            # Metadata subtitle right next to bar or above bar
            if meta_str:
                painter.setFont(f_meta)
                painter.setPen(QColor(self.palette.text_muted))
                painter.drawText(
                    QRectF(22.0, y + 17.0, w - 280.0, 14.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    meta_str,
                )

            # Progress bar track
            bar_y = y + 33.0
            bar_w = max(60.0, w - 30.0)
            track_rect = QRectF(22.0, bar_y, bar_w, 6.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.palette.border))
            painter.drawRoundedRect(track_rect, 3.2, 3.2)

            fill_w = max(4.0, bar_w * share) if comp.watts > 0.01 else 0.0
            if fill_w > 0:
                fill_rect = QRectF(22.0, bar_y, fill_w, 6.5)
                painter.setBrush(QColor(col_hex))
                painter.drawRoundedRect(fill_rect, 3.2, 3.2)

            y += row_h

        painter.end()


class HistoryBarChart(QWidget):
    """Interactive historical bar chart for Energy (Wh), Electricity Cost ($), or Carbon (g CO2e)."""

    def __init__(self, palette: ThemePalette = DARK_PALETTE, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.buckets: list[HistoricalBucket] = []
        self.chart_metric: str = "energy"  # "energy", "cost", "carbon"
        self.profile: TariffProfile = TariffProfile()
        self._hover_idx: Optional[int] = None
        self.setMouseTracking(True)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self.palette = palette
        self.update()

    def set_data(
        self,
        buckets: list[HistoricalBucket],
        chart_metric: str,
        profile: TariffProfile,
    ) -> None:
        self.buckets = list(buckets)
        self.chart_metric = chart_metric
        self.profile = profile
        self.update()

    def _bucket_val(self, b: HistoricalBucket) -> float:
        if self.chart_metric == "cost":
            return energy_cost(b.energy_wh, self.profile)
        if self.chart_metric == "carbon":
            return energy_carbon_grams(b.energy_wh, self.profile)
        return b.energy_wh

    def _format_val(self, val: float) -> str:
        if self.chart_metric == "cost":
            return format_currency(val, self.profile.currency_symbol)
        if self.chart_metric == "carbon":
            return format_carbon(val)
        return format_energy(val)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position() if hasattr(event, "position") else event.pos()
        left, right = 58.0, 16.0
        plot_w = max(40.0, float(self.width()) - left - right)
        mx = float(pos.x())
        if self.buckets and left <= mx <= left + plot_w:
            idx = int(((mx - left) / plot_w) * len(self.buckets))
            self._hover_idx = max(0, min(len(self.buckets) - 1, idx))
        else:
            self._hover_idx = None
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover_idx = None
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        left, top, right, bottom = 58.0, 18.0, 16.0, 28.0
        plot = QRectF(left, top, max(40.0, w - left - right), max(40.0, h - top - bottom))

        vals = [self._bucket_val(b) for b in self.buckets]
        max_v = max(vals, default=0.0)
        y_max = max_v * 1.2 if max_v > 0 else 1.0

        f_axis = QFont()
        f_axis.setPointSize(8)
        painter.setFont(f_axis)
        grid_pen = QPen(QColor(self.palette.grid_line), 1.0, Qt.PenStyle.DashLine)
        for i in range(5):
            frac = i / 4.0
            y = plot.bottom() - frac * plot.height()
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            v_lbl = self._format_val(frac * y_max) if max_v > 0 else "0"
            painter.setPen(QColor(self.palette.text_muted))
            painter.drawText(
                QRectF(2.0, y - 8.0, left - 6.0, 16.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                v_lbl.replace(" CO₂e", ""),
            )

        if not self.buckets:
            painter.end()
            return

        color_map = {
            "energy": self.palette.accent_cyan,
            "cost": self.palette.accent_emerald,
            "carbon": self.palette.accent_amber,
        }
        bar_hex = color_map.get(self.chart_metric, self.palette.accent_emerald)

        n = len(self.buckets)
        slot_w = plot.width() / max(1, n)
        bar_w = max(4.0, min(28.0, slot_w * 0.66))
        label_stride = max(1, math.ceil(n / 8))

        for i, b in enumerate(self.buckets):
            cx = plot.left() + (i + 0.5) * slot_w
            v = vals[i]
            bh = (v / y_max) * plot.height() if max_v > 0 else 0.0
            if bh > 0.5:
                brect = QRectF(cx - bar_w / 2.0, plot.bottom() - bh, bar_w, bh)
                c = QColor(bar_hex)
                if self._hover_idx is not None and i != self._hover_idx:
                    c.setAlpha(155)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(c)
                painter.drawRoundedRect(brect, 4.0, 4.0)

            if i % label_stride == 0 or i == n - 1:
                painter.setPen(QColor(self.palette.text_muted))
                painter.drawText(
                    QRectF(cx - 28.0, plot.bottom() + 5.0, 56.0, 18.0),
                    Qt.AlignmentFlag.AlignCenter,
                    b.bucket_label,
                )

        if self._hover_idx is not None and 0 <= self._hover_idx < n:
            b = self.buckets[self._hover_idx]
            cx = plot.left() + (self._hover_idx + 0.5) * slot_w
            tip_w, tip_h = 182.0, 74.0
            tx = cx + 10.0 if (cx + 10.0 + tip_w <= plot.right()) else (cx - tip_w - 10.0)
            ty = plot.top() + 6.0
            trect = QRectF(tx, ty, tip_w, tip_h)

            bg = QColor(self.palette.bg_sidebar)
            bg.setAlpha(240)
            painter.setPen(QPen(QColor(self.palette.border_strong), 1.0))
            painter.setBrush(bg)
            painter.drawRoundedRect(trect, 8.0, 8.0)

            c_str = format_currency(energy_cost(b.energy_wh, self.profile), self.profile.currency_symbol)
            co2_str = format_carbon(energy_carbon_grams(b.energy_wh, self.profile))

            f_tip = QFont()
            f_tip.setPointSize(8)
            f_tip.setBold(True)
            painter.setFont(f_tip)
            painter.setPen(QColor(self.palette.text_primary))
            painter.drawText(
                QRectF(tx + 9.0, ty + 6.0, tip_w - 18.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                f"{b.bucket_label}  •  Avg {b.avg_watts:.1f}W",
            )
            f_tip.setBold(False)
            painter.setFont(f_tip)
            painter.setPen(QColor(self.palette.text_secondary))
            painter.drawText(
                QRectF(tx + 9.0, ty + 27.0, tip_w - 18.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                f"Energy: {format_energy(b.energy_wh)}  ({c_str})",
            )
            painter.drawText(
                QRectF(tx + 9.0, ty + 46.0, tip_w - 18.0, 18.0),
                Qt.AlignmentFlag.AlignLeft,
                f"Footprint: {co2_str}",
            )

        painter.end()
