"""
Highlight Overlay — Transparent full-screen drag-selection widget.

Mirrors the TipTour "Focus Highlight" UX:
  1. User holds hotkey → overlay appears (screen dims)
  2. Click & drag → rubber-band selection rectangle
  3. Release → selection rect emitted via signal
  4. Escape → cancel

Uses PyQt6, consistent with the DynamicNotch overlay in notch.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt6.QtCore import (
    Qt, QRect, QPoint, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QPaintEvent,
    QKeyEvent, QMouseEvent, QCursor,
)
from PyQt6.QtWidgets import QWidget, QApplication

log = logging.getLogger("bluely.highlight_overlay")

# -- Design tokens (matching notch.py palette) --
DIM_ALPHA = 130
SELECTION_FILL = QColor(66, 133, 244, 50)
SELECTION_BORDER = QColor(66, 133, 244, 220)
INFO_BG = QColor(25, 25, 35, 210)
INFO_TEXT = QColor(230, 230, 240)
INFO_DIM = QColor(160, 160, 170)
ACCENT_BLUE = QColor(66, 133, 244)
HANDLE_COLOR = QColor(66, 133, 244, 200)


@dataclass
class SelectionResult:
    x: int
    y: int
    width: int
    height: int
    screen_rect: tuple[int, int, int, int]  # virtual screen bounds

    @property
    def normalized(self) -> tuple[int, int, int, int]:
        """Always positive width/height regardless of drag direction."""
        return (self.x, self.y, self.width, self.height)

    def to_dict(self) -> dict:
        return {
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
        }


class SelectionOverlay(QWidget):
    """Full-screen transparent overlay for rubber-band region selection.

    Signals:
        selection_complete(SelectionResult): emitted when user releases drag.
        cancelled(): emitted when user presses Escape.
    """

    selection_complete = pyqtSignal(object)  # SelectionResult
    cancelled = pyqtSignal()

    # ──────────────────────────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self._selection_active = False
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._selection_rect: QRect | None = None
        self._fade_opacity = 0.0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_step)
        self._visible_target = False

        # Full virtual screen geometry
        self._virtual_geometry = self._get_virtual_geometry()

        self._setup_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _get_virtual_geometry(self) -> QRect:
        """Return bounding rect of all screens."""
        app = QApplication.instance()
        if not app:
            return QRect(0, 0, 1920, 1080)
        geo = QRect()
        for screen in app.screens():
            geo = geo.united(screen.geometry())
        return geo

    # ──────────────────────────────────────────────────────────────────
    # Show / hide with fade
    # ──────────────────────────────────────────────────────────────────

    def show_overlay(self):
        """Show the overlay with a fade-in."""
        rect = self._virtual_geometry
        self.setGeometry(rect)
        self._visible_target = True
        self._fade_opacity = 0.0
        self._fade_timer.start(16)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def hide_overlay(self):
        """Hide the overlay immediately."""
        self._visible_target = False
        self._fade_opacity = 1.0
        self._fade_timer.start(16)

    def _fade_step(self):
        step = 0.08
        if self._visible_target:
            self._fade_opacity = min(1.0, self._fade_opacity + step)
            if self._fade_opacity >= 1.0:
                self._fade_timer.stop()
        else:
            self._fade_opacity = max(0.0, self._fade_opacity - step)
            if self._fade_opacity <= 0.0:
                self._fade_timer.stop()
                self.hide()
                self._reset_selection()
        self.update()

    # ──────────────────────────────────────────────────────────────────
    # Mouse events
    # ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent | None):
        if event and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_current = self._drag_start
            self._selection_active = True
            self._selection_rect = QRect(self._drag_start, QPoint(0, 0))
            self.setMouseTracking(True)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent | None):
        if event and self._selection_active and self._drag_start:
            self._drag_current = event.position().toPoint()
            self._update_selection_rect()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None):
        if event and event.button() == Qt.MouseButton.LeftButton and self._selection_active:
            self._selection_active = False
            self.setMouseTracking(False)
            self._drag_current = event.position().toPoint()
            self._update_selection_rect()

            if self._selection_rect and self._selection_rect.width() > 5 and self._selection_rect.height() > 5:
                result = SelectionResult(
                    x=self._selection_rect.x(),
                    y=self._selection_rect.y(),
                    width=self._selection_rect.width(),
                    height=self._selection_rect.height(),
                    screen_rect=(
                        self._virtual_geometry.x(),
                        self._virtual_geometry.y(),
                        self._virtual_geometry.width(),
                        self._virtual_geometry.height(),
                    ),
                )
                self.selection_complete.emit(result)
                self.hide_overlay()
            else:
                self._reset_selection()
                self.update()

    def keyPressEvent(self, event: QKeyEvent | None):
        if event and event.key() == Qt.Key.Key_Escape:
            self._selection_active = False
            self.setMouseTracking(False)
            self.cancelled.emit()
            self.hide_overlay()

    def _update_selection_rect(self):
        if self._drag_start and self._drag_current:
            x1 = min(self._drag_start.x(), self._drag_current.x())
            y1 = min(self._drag_start.y(), self._drag_current.y())
            x2 = max(self._drag_start.x(), self._drag_current.x())
            y2 = max(self._drag_start.y(), self._drag_current.y())
            self._selection_rect = QRect(x1, y1, x2 - x1, y2 - y1)

    def _reset_selection(self):
        self._selection_active = False
        self._drag_start = None
        self._drag_current = None
        self._selection_rect = None
        self.setMouseTracking(False)
        self.update()

    # ──────────────────────────────────────────────────────────────────
    # Paint
    # ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent | None):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        alpha = int(255 * self._fade_opacity)

        # 1. Dim the screen
        dim = QColor(0, 0, 0, int(DIM_ALPHA * self._fade_opacity))
        painter.fillRect(self.rect(), dim)

        if not self._selection_rect:
            # Show instructions when no drag in progress
            if self._fade_opacity > 0.5:
                self._draw_instructions(painter, alpha)
            return

        # 2. Clear the selection area (cut-out effect)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self._selection_rect, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # 3. Fill inside selection with subtle highlight
        fill = QColor(SELECTION_FILL)
        fill.setAlpha(int(fill.alpha() * self._fade_opacity))
        painter.fillRect(self._selection_rect, fill)

        # 4. Selection border
        border_pen = QPen(SELECTION_BORDER, 2)
        border_pen.setDashPattern([6, 3])
        painter.setPen(border_pen)
        painter.drawRect(self._selection_rect)

        # 5. Corner handles
        self._draw_handles(painter)

        # 6. Info label (dimensions)
        self._draw_dimension_label(painter, alpha)

    def _draw_instructions(self, painter: QPainter, alpha: int):
        font = QFont("Segoe UI", 14)
        font.setWeight(400)
        painter.setFont(font)

        text = "Click and drag to select a region  ·  Esc to cancel"
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)
        th = fm.height()

        pad = 20
        bx = (self.width() - tw) // 2 - pad
        by = self.height() // 2 - 80
        bw = tw + pad * 2
        bh = th + pad

        bg = QColor(INFO_BG)
        bg.setAlpha(int(bg.alpha() * self._fade_opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(bx, by, bw, bh, 12, 12)

        text_color = QColor(INFO_TEXT)
        text_color.setAlpha(alpha)
        painter.setPen(text_color)
        painter.drawText(bx + pad, by + pad + fm.ascent(), text)

    def _draw_handles(self, painter: QPainter):
        if not self._selection_rect:
            return
        r = self._selection_rect
        size = 8
        half = size // 2
        corners = [
            QPoint(r.left(), r.top()),
            QPoint(r.right(), r.top()),
            QPoint(r.left(), r.bottom()),
            QPoint(r.right(), r.bottom()),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HANDLE_COLOR)
        for pt in corners:
            painter.drawEllipse(pt.x() - half, pt.y() - half, size, size)

    def _draw_dimension_label(self, painter: QPainter, alpha: int):
        if not self._selection_rect:
            return
        r = self._selection_rect
        text = f"{r.width()} × {r.height()} px"
        font = QFont("Segoe UI", 11)
        font.setWeight(500)
        painter.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)

        pad = 10
        label_w = tw + pad * 2
        label_h = fm.height() + pad

        bx = r.x() + (r.width() - label_w) // 2
        by = r.y() + r.height() + 12

        bg = QColor(INFO_BG)
        bg.setAlpha(int(bg.alpha() * self._fade_opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(bx, by, label_w, label_h, 8, 8)

        text_color = QColor(INFO_DIM)
        text_color.setAlpha(alpha)
        painter.setPen(text_color)
        painter.drawText(bx + pad, by + pad + fm.ascent(), text)


__all__ = ["SelectionOverlay", "SelectionResult"]
