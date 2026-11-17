"""Unified Qt6 compatibility layer (PySide6 primary, PyQt6 fallback) and vector app icon."""

from __future__ import annotations

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import (
        QAction,
        QColor,
        QFont,
        QIcon,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QPolygonF,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
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
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    QT_BINDING = "PySide6"
except ImportError:  # pragma: no cover - fallback for distros with system PyQt6 only
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]
    from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal as Signal  # type: ignore[no-redef]
    from PyQt6.QtGui import (  # type: ignore[no-redef]
        QAction,
        QColor,
        QFont,
        QIcon,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QPolygonF,
    )
    from PyQt6.QtWidgets import (  # type: ignore[no-redef]
        QAbstractItemView,
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
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    QT_BINDING = "PyQt6"


def create_app_icon(size: int = 128) -> QIcon:
    """Render a crisp high-DPI vector lightning badge icon without external image assets."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Rounded gradient squircle background
    pad = size * 0.06
    rect = QRectF(pad, pad, size - 2 * pad, size - 2 * pad)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#059669"))
    grad.setColorAt(0.55, QColor("#0EA5E9"))
    grad.setColorAt(1.0, QColor("#6366F1"))

    painter.setPen(QPen(QColor(255, 255, 255, 45), max(1.5, size * 0.02)))
    painter.setBrush(grad)
    radius = size * 0.24
    painter.drawRoundedRect(rect, radius, radius)

    # Crisp white lightning bolt
    bolt = QPolygonF(
        [
            QPointF(size * 0.56, size * 0.17),
            QPointF(size * 0.28, size * 0.54),
            QPointF(size * 0.48, size * 0.54),
            QPointF(size * 0.42, size * 0.83),
            QPointF(size * 0.72, size * 0.45),
            QPointF(size * 0.52, size * 0.45),
        ]
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPolygon(bolt)
    painter.end()

    return QIcon(pix)


__all__ = [
    "QT_BINDING",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QPointF",
    "QRectF",
    "QSize",
    "Qt",
    "QThread",
    "QTimer",
    "Signal",
    "QAction",
    "QColor",
    "QFont",
    "QIcon",
    "QLinearGradient",
    "QPainter",
    "QPainterPath",
    "QPen",
    "QPixmap",
    "QPolygonF",
    "QAbstractItemView",
    "QApplication",
    "QCheckBox",
    "QComboBox",
    "QDoubleSpinBox",
    "QFileDialog",
    "QFrame",
    "QGridLayout",
    "QHBoxLayout",
    "QHeaderView",
    "QLabel",
    "QLineEdit",
    "QMainWindow",
    "QMenu",
    "QMessageBox",
    "QPushButton",
    "QScrollArea",
    "QSizePolicy",
    "QSpinBox",
    "QStackedWidget",
    "QSystemTrayIcon",
    "QTableWidget",
    "QTableWidgetItem",
    "QVBoxLayout",
    "QWidget",
    "create_app_icon",
]
