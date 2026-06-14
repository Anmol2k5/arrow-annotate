import math
import random
import os
import json

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QRect, QPoint,     QSize, pyqtSignal, pyqtProperty, QUrl
)
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QBrush, QPen, QFont, QFontMetrics,
    QPixmap, QPainterPath, QRegion, QTransform, QDesktopServices, QAction,
    QConicalGradient, QPalette, QCursor
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QGraphicsDropShadowEffect, QFrame, QSizePolicy,
    QSpacerItem, QScrollArea, QGridLayout, QButtonGroup, QSlider,
    QListWidget, QListWidgetItem, QProgressBar, QFileDialog, QMessageBox
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from server import AgentServer
from capture_store import CaptureRecord, CaptureStore
from voice_input import VoiceInput

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NOTCH_BG = "rgba(9, 9, 11, 240)"
NOTCH_BORDER = "rgba(255, 255, 255, 12)"

IDLE_W, IDLE_H = 72, 30
EXPANDED_W, EXPANDED_H = 440, 380
AGENTS_W, AGENTS_H = 440, 420
SCREENSHOTS_W, SCREENSHOTS_H = 480, 440
SETTINGS_W, SETTINGS_H = 400, 460

TOP_OFFSET = 8
ANIM_MS = 350

ACCENT_COLORS = [
    ("#7DD3FC", "#Sky"), ("#34D399", "#Emerald"), ("#A78BFA", "#Violet"),
    ("#F472B6", "#Pink"), ("#FB923C", "#Orange"), ("#FBBF24", "#Amber"),
]

PILL_STYLE = """
    QPushButton {{
        color: rgba(255,255,255,140);
        background: rgba(255,255,255,8);
        border-radius: {r}px;
        padding: {p}px 16px;
        font-size: 11px;
        font-weight: 500;
    }}
    QPushButton:checked {{
        color: white;
        background: rgba(255,255,255,15);
    }}
    QPushButton:hover {{
        background: rgba(255,255,255,12);
    }}
"""


# ---------------------------------------------------------------------------
# Glowing triangle logo  (idle state)
# ---------------------------------------------------------------------------
class GlowingTriangleLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2, self.height() / 2
        r = 10
        angle = -math.pi / 2
        pts = []
        for _ in range(3):
            pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            angle += 2 * math.pi / 3

        path = QPainterPath()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        path.lineTo(pts[2])
        path.closeSubpath()

        grad = QLinearGradient(pts[0], pts[1])
        grad.setColorAt(0.0, QColor("#7DD3FC"))
        grad.setColorAt(0.5, QColor("#3B82F6"))
        grad.setColorAt(1.0, QColor("#6366F1"))

        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)


# ---------------------------------------------------------------------------
# MiniWaveformWidget  – 5‑bar jitter visualiser
# ---------------------------------------------------------------------------
class MiniWaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = [0.2, 0.5, 0.8, 0.5, 0.3]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._jitter)
        self._timer.start(55)
        self.setFixedSize(44, 22)

    def _jitter(self):
        for i in range(5):
            self._bars[i] = max(0.08, min(1.0, self._bars[i] + random.uniform(-0.18, 0.18)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bw, sp, n = 4, 3, 5
        tw = n * bw + (n - 1) * sp
        sx = (self.width() - tw) / 2.0

        for i, h in enumerate(self._bars):
            bh = h * self.height()
            x = sx + i * (bw + sp)
            y = self.height() - bh

            grad = QLinearGradient(x, y, x + bw, y + bh)
            grad.setColorAt(0.0, QColor("#7DD3FC"))
            grad.setColorAt(1.0, QColor("#3B82F6"))

            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, y, bw, bh), 2, 2)


# ---------------------------------------------------------------------------
# PulseDotsWidget  – three breathing dots  (Emerald / Purple / Amber)
# ---------------------------------------------------------------------------
class PulseDotsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacities = [0.4, 0.4, 0.4]
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(100)
        self.setFixedSize(42, 18)
        self._colors = ["#22C55E", "#A855F7", "#F59E0B"]

    def _pulse(self):
        self._phase += 0.18
        for i in range(3):
            self._opacities[i] = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(self._phase + i * 2.094))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dr, sp = 3.5, 10
        n = 3
        tw = n * 2 * dr + (n - 1) * sp
        sx = (self.width() - tw) / 2.0
        cy = self.height() / 2.0

        for i in range(n):
            alpha = int(self._opacities[i] * 255)
            x = sx + i * (2 * dr + sp) + dr
            c = QColor(self._colors[i])
            c.setAlpha(alpha)
            painter.setBrush(c)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, cy), dr, dr)


# ---------------------------------------------------------------------------
# ThinkingSpinnerWidget  – rotating arc
# ---------------------------------------------------------------------------
class ThinkingSpinnerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._spin)
        self._timer.start(40)
        self.setFixedSize(22, 22)

    def _spin(self):
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(QColor("#7DD3FC"), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        margin = 2.5
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawArc(rect, self._angle * 16, 270 * 16)


# ---------------------------------------------------------------------------
# ScreenshotThumbnail  – clickable thumbnail with delete
# ---------------------------------------------------------------------------
class CaptureCard(QFrame):
    deleted = pyqtSignal(object)
    send_requested = pyqtSignal(object)
    copy_requested = pyqtSignal(object)
    open_requested = pyqtSignal(object)

    def __init__(self, record: "CaptureRecord", parent=None):
        super().__init__(parent)
        self._record = record
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            CaptureCard {
                background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,10);
                border-radius: 10px;
            }
            CaptureCard:hover {
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,18);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # -- Left: thumbnail --
        thumb_layout = QVBoxLayout()
        thumb_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._img_label = QLabel()
        self._img_label.setFixedSize(120, 75)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_thumb()
        thumb_layout.addWidget(self._img_label)
        layout.addLayout(thumb_layout)

        # -- Right: metadata + actions --
        right = QVBoxLayout()
        right.setSpacing(3)

        # Annotation
        annotation = self._record.annotation_text or "No annotation"
        self._annotation_label = QLabel(annotation)
        self._annotation_label.setStyleSheet("color: rgba(255,255,255,180); font-size: 10px; font-weight: 600;")
        self._annotation_label.setWordWrap(True)
        self._annotation_label.setMaximumHeight(36)
        right.addWidget(self._annotation_label)

        # Element selector
        if self._record.element_selector and self._record.element_selector != "web_page":
            sel = QLabel(f"`{self._record.element_selector[:55]}`")
            sel.setStyleSheet("color: #7DD3FC; font-size: 9px;")
            right.addWidget(sel)
        else:
            sel = QLabel("No web element detected")
            sel.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
            right.addWidget(sel)

        # React components
        if self._record.react_components:
            rc = QLabel(f"\u269B {self._record.react_components[:60]}")
            rc.setStyleSheet("color: #A78BFA; font-size: 9px;")
            right.addWidget(rc)

        # Cursor position
        pos = QLabel(f"\U0001F4CD ({self._record.cursor_x}, {self._record.cursor_y})")
        pos.setStyleSheet("color: rgba(255,255,255,100); font-size: 9px;")
        right.addWidget(pos)

        right.addStretch()

        # -- Action buttons --
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        open_btn = QPushButton("Open")
        open_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,140); background: rgba(255,255,255,8);
                border: 1px solid rgba(255,255,255,12); border-radius: 10px;
                padding: 3px 10px; font-size: 9px; font-weight: 500;
            }
            QPushButton:hover { background: rgba(255,255,255,14); }
        """)
        open_btn.clicked.connect(lambda: self.open_requested.emit(self))
        btn_row.addWidget(open_btn)

        copy_btn = QPushButton("Copy Code")
        copy_btn.setStyleSheet("""
            QPushButton {
                color: #7DD3FC; background: rgba(125,211,252,12);
                border: 1px solid rgba(125,211,252,25); border-radius: 10px;
                padding: 3px 10px; font-size: 9px; font-weight: 500;
            }
            QPushButton:hover { background: rgba(125,211,252,20); }
        """)
        copy_btn.clicked.connect(lambda: self.copy_requested.emit(self))
        btn_row.addWidget(copy_btn)

        send_btn = QPushButton("Send to Agent")
        send_btn.setStyleSheet("""
            QPushButton {
                color: #34D399; background: rgba(52,211,153,12);
                border: 1px solid rgba(52,211,153,25); border-radius: 10px;
                padding: 3px 10px; font-size: 9px; font-weight: 500;
            }
            QPushButton:hover { background: rgba(52,211,153,20); }
        """)
        send_btn.clicked.connect(lambda: self.send_requested.emit(self))
        btn_row.addWidget(send_btn)

        btn_row.addStretch()

        # Status badge
        st = self._record.agentation_status
        if st == "sent":
            badge = QLabel("\u25CF Sent")
            badge.setStyleSheet("color: #34D399; font-size: 9px; font-weight: 600;")
        elif st:
            badge = QLabel(f"\u25CF {st.title()}")
            badge.setStyleSheet("color: #F59E0B; font-size: 9px; font-weight: 600;")
        else:
            badge = QLabel("\u25CB New")
            badge.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
        btn_row.addWidget(badge)

        # Delete
        del_btn = QPushButton("\u00D7")
        del_btn.setFixedSize(18, 18)
        del_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,60); background: transparent;
                border: none; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { color: #EF4444; }
        """)
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(del_btn)

        right.addLayout(btn_row)
        layout.addLayout(right, 1)

    def _load_thumb(self):
        pix = QPixmap(self._record.screenshot_path)
        if not pix.isNull():
            self._img_label.setPixmap(pix.scaled(120, 75, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _delete(self):
        reply = QMessageBox.question(self, "Delete", f"Delete this capture?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self._record.screenshot_path)
            except Exception:
                pass
            from capture_store import CaptureStore
            CaptureStore().delete(self._record.id)
            self.deleted.emit(self)

    @property
    def record(self):
        return self._record


# ---------------------------------------------------------------------------
# HomeView
# ---------------------------------------------------------------------------
class HomeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_logo_loaded)
        self._pending = {}
        self._accent = ACCENT_COLORS[0][0]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(8)

        # -- Integrations header --
        hdr = QLabel("Active Integrations")
        hdr.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 3px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,20); border-radius: 2px; }
        """)
        scroll_w = QWidget()
        scroll_w.setStyleSheet("background: transparent;")
        self._integrations_layout = QVBoxLayout(scroll_w)
        self._integrations_layout.setSpacing(4)
        scroll.setWidget(scroll_w)
        layout.addWidget(scroll, 1)

        for name, domain, status in [
            ("Slack", "slack.com", True), ("GitHub", "github.com", True),
            ("Notion", "notion.so", True), ("Figma", "figma.com", True),
        ]:
            self._add_integration(name, domain, status)

        # -- Accent colour picker --
        picker_layout = QHBoxLayout()
        picker_layout.setSpacing(6)
        lbl = QLabel("Accent")
        lbl.setStyleSheet("color: rgba(255,255,255,120); font-size: 10px;")
        picker_layout.addWidget(lbl)

        self._accent_group = QButtonGroup(self)
        self._accent_group.idClicked.connect(self._on_accent)
        for i, (code, name) in enumerate(ACCENT_COLORS):
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {code}; border-radius: 9px; border: 2px solid transparent;
                }}
                QPushButton:checked {{
                    border: 2px solid white;
                }}
            """)
            btn.setCheckable(True)
            if i == 0:
                btn.setChecked(True)
            self._accent_group.addButton(btn, i)
            picker_layout.addWidget(btn)
        picker_layout.addStretch()
        layout.addLayout(picker_layout)

        # -- Dock/Undock toggle --
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._dock_btn = QPushButton("Dock")
        self._dock_btn.setCheckable(True)
        self._dock_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,180);
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,14);
                border-radius: 16px;
                padding: 6px 20px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:checked {
                background: rgba(125,211,252,20);
                border: 1px solid rgba(125,211,252,40);
                color: #7DD3FC;
            }
            QPushButton:hover { background: rgba(255,255,255,16); }
        """)
        self._dock_btn.clicked.connect(self._toggle_dock)
        btn_row.addWidget(self._dock_btn)
        btn_row.addStretch()

        self._listening_label = QLabel("● Listening")
        self._listening_label.setStyleSheet("color: #22C55E; font-size: 10px; font-weight: 600;")
        btn_row.addWidget(self._listening_label)

        layout.addLayout(btn_row)

    def _add_integration(self, name, domain, status):
        row = QWidget()
        row.setFixedHeight(32)
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(4, 0, 4, 0)
        rl.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(20, 20)
        rl.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: rgba(255,255,255,180); font-size: 11px; font-weight: 500;")
        rl.addWidget(name_lbl)
        rl.addStretch()

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {'#22C55E' if status else '#6B7280'}; font-size: 8px;")
        dot.setFixedWidth(12)
        rl.addWidget(dot)

        self._integrations_layout.addWidget(row)

        # kick off Clearbit logo fetch
        url = QUrl(f"https://logo.clearbit.com/{domain}")
        reply = self._net.get(QNetworkRequest(url))
        self._pending[reply] = icon_lbl

    def _on_logo_loaded(self, reply):
        lbl = self._pending.pop(reply, None)
        if lbl is None:
            return
        data = reply.readAll()
        pix = QPixmap()
        if pix.loadFromData(data):
            lbl.setPixmap(pix.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        reply.deleteLater()

    def _on_accent(self, btn_id):
        self._accent = ACCENT_COLORS[btn_id][0]

    def _toggle_dock(self, checked):
        parent_notch = self.window()
        if hasattr(parent_notch, 'set_docked'):
            parent_notch.set_docked(checked)


# ---------------------------------------------------------------------------
# AgentsView
# ---------------------------------------------------------------------------
class AgentsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._populate_demo()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(6)

        hdr = QLabel("Task Queue")
        hdr.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 3px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,20); border-radius: 2px; }
        """)
        self._tasks_widget = QWidget()
        self._tasks_widget.setStyleSheet("background: transparent;")
        self._tasks_layout = QVBoxLayout(self._tasks_widget)
        self._tasks_layout.setSpacing(6)
        self._tasks_layout.addStretch()
        scroll.setWidget(self._tasks_widget)
        layout.addWidget(scroll, 1)

    def _populate_demo(self):
        tasks = [
            ("Web Scrape – example.com", 0.72, "running"),
            ("Data Export – Q2 Report", 1.0, "completed"),
            ("Screenshot Batch – 12 pages", 0.34, "running"),
            ("Email Digest Generation", 0.0, "pending"),
        ]
        for title, progress, status in tasks:
            self.add_task(title, progress, status)

    def add_task(self, title, progress, status):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,5);
                border: 1px solid rgba(255,255,255,8);
                border-radius: 10px;
            }
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(4)

        top = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("color: rgba(255,255,255,170); font-size: 11px; font-weight: 500;")
        top.addWidget(lbl)
        top.addStretch()

        status_colors = {"running": "#F59E0B", "completed": "#22C55E", "pending": "#6B7280", "error": "#EF4444"}
        status_lbl = QLabel(status.title())
        status_lbl.setStyleSheet(f"color: {status_colors.get(status, '#6B7280')}; font-size: 9px; font-weight: 600;")
        top.addWidget(status_lbl)

        if status == "running":
            cancel_btn = QPushButton("×")
            cancel_btn.setFixedSize(18, 18)
            cancel_btn.setStyleSheet("""
                QPushButton {
                    color: rgba(255,255,255,80);
                    background: transparent;
                    border: none;
                    font-size: 14px;
                }
                QPushButton:hover { color: #EF4444; }
            """)
            top.addWidget(cancel_btn)

        cl.addLayout(top)

        if status == "running":
            pb = QProgressBar()
            pb.setFixedHeight(4)
            pb.setRange(0, 100)
            pb.setValue(int(progress * 100))
            pb.setTextVisible(False)
            pb.setStyleSheet("""
                QProgressBar {
                    background: rgba(255,255,255,8);
                    border-radius: 2px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3B82F6, stop:1 #7DD3FC);
                    border-radius: 2px;
                }
            """)
            cl.addWidget(pb)
        elif status == "completed":
            done_lbl = QLabel("✓ Completed")
            done_lbl.setStyleSheet("color: rgba(34,197,94,100); font-size: 9px;")
            cl.addWidget(done_lbl)

        self._tasks_layout.insertWidget(self._tasks_layout.count() - 1, card)


# ---------------------------------------------------------------------------
# ScreenshotsView
# ---------------------------------------------------------------------------
class CapturesView(QWidget):
    def __init__(self, notch: "DynamicNotch"):
        super().__init__()
        self._notch = notch
        self._cards: list[CaptureCard] = []
        self._setup_ui()
        self._load_captures()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(8)

        # Header
        top = QHBoxLayout()
        hdr = QLabel("Captures")
        hdr.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        top.addWidget(hdr)
        top.addStretch()

        # Voice button
        self._voice_btn = QPushButton("\U0001F3A4")
        self._voice_btn.setFixedSize(28, 28)
        self._voice_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,140); background: rgba(255,255,255,8);
                border: 1px solid rgba(255,255,255,12); border-radius: 14px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(255,255,255,14); }
            QPushButton:checked { background: rgba(239,68,68,25); border-color: rgba(239,68,68,40); }
        """)
        self._voice_btn.setCheckable(True)
        self._voice_btn.clicked.connect(self._on_voice_toggle)
        top.addWidget(self._voice_btn)

        self._voice_status = QLabel("")
        self._voice_status.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
        top.addWidget(self._voice_status)

        # Capture button
        capture_btn = QPushButton("+ Capture")
        capture_btn.setStyleSheet("""
            QPushButton {
                color: #7DD3FC; background: rgba(125,211,252,12);
                border: 1px solid rgba(125,211,252,25); border-radius: 12px;
                padding: 4px 14px; font-size: 10px; font-weight: 600;
            }
            QPushButton:hover { background: rgba(125,211,252,20); }
        """)
        capture_btn.clicked.connect(self._on_capture)
        top.addWidget(capture_btn)

        layout.addLayout(top)

        # Scroll area with card list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 3px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,20); border-radius: 2px; }
        """)
        self._scroll_w = QWidget()
        self._scroll_w.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._scroll_w)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(6)
        self._card_layout.addStretch()
        scroll.setWidget(self._scroll_w)
        layout.addWidget(scroll, 1)

    def _load_captures(self):
        store = self._notch.get_capture_store()
        for record in store.get_all():
            self._add_card(record)

    def _add_card(self, record: "CaptureRecord"):
        card = CaptureCard(record)
        card.open_requested.connect(self._on_open)
        card.copy_requested.connect(self._on_copy)
        card.send_requested.connect(self._on_send)
        card.deleted.connect(self._remove_card)
        self._cards.append(card)
        self._card_layout.insertWidget(len(self._cards) - 1, card)

    def add_capture(self, record: "CaptureRecord"):
        self._add_card(record)

    def _remove_card(self, card: CaptureCard):
        self._card_layout.removeWidget(card)
        self._cards.remove(card)
        card.deleteLater()

    def _on_capture(self):
        self._notch.do_capture()

    def _on_voice_toggle(self, checked):
        if checked:
            self._voice_btn.setStyleSheet("""
                QPushButton {
                    color: #EF4444; background: rgba(239,68,68,25);
                    border: 1px solid rgba(239,68,68,40); border-radius: 14px;
                    font-size: 13px;
                }
                QPushButton:hover { background: rgba(239,68,68,30); }
            """)
            self._voice_status.setText("Listening...")
            self._voice_status.setStyleSheet("color: #EF4444; font-size: 9px;")
            self._notch.start_voice_capture()
        else:
            self._voice_btn.setStyleSheet("""
                QPushButton {
                    color: rgba(255,255,255,140); background: rgba(255,255,255,8);
                    border: 1px solid rgba(255,255,255,12); border-radius: 14px;
                    font-size: 13px;
                }
                QPushButton:hover { background: rgba(255,255,255,14); }
            """)
            self._voice_status.setText("")
            self._notch.stop_voice_capture()

    def _on_open(self, card: CaptureCard):
        self._notch.open_capture(card.record)

    def _on_copy(self, card: CaptureCard):
        self._notch.copy_capture_code(card.record)

    def _on_send(self, card: CaptureCard):
        self._notch.send_capture_to_agent(card.record)

    def on_voice_result(self, text: str):
        self._voice_status.setText(f"\u2713 {text[:30]}...")
        self._voice_status.setStyleSheet("color: #34D399; font-size: 9px;")
        self._voice_btn.setChecked(False)

    def on_voice_error(self, msg: str):
        self._voice_status.setText(f"\u2717 {msg}")
        self._voice_status.setStyleSheet("color: #EF4444; font-size: 9px;")
        QTimer.singleShot(3000, lambda: self._voice_status.setText(""))
        self._voice_btn.setChecked(False)

    def update_card_status(self, record: "CaptureRecord"):
        for card in self._cards:
            if card.record.id == record.id:
                card.record.agentation_status = record.agentation_status
                break


# ---------------------------------------------------------------------------
# SessionView  – Agentation session management
# ---------------------------------------------------------------------------
class SessionView(QWidget):
    def __init__(self, notch: "DynamicNotch"):
        super().__init__()
        self._notch = notch
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(8)

        # -- Header --
        hdr = QLabel("Agentation Session")
        hdr.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        layout.addWidget(hdr)

        self._status_row = QHBoxLayout()
        self._status_dot = QLabel("○")
        self._status_dot.setStyleSheet("color: #6B7280; font-size: 10px;")
        self._status_row.addWidget(self._status_dot)
        self._status_text = QLabel("Disconnected")
        self._status_text.setStyleSheet("color: rgba(255,255,255,120); font-size: 11px;")
        self._status_row.addWidget(self._status_text)
        self._status_row.addStretch()
        layout.addLayout(self._status_row)

        # -- Session controls --
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self._start_btn = QPushButton("Start Task")
        self._start_btn.setStyleSheet("""
            QPushButton {
                color: #7DD3FC;
                background: rgba(125,211,252,12);
                border: 1px solid rgba(125,211,252,25);
                border-radius: 12px;
                padding: 6px 16px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(125,211,252,20); }
        """)
        self._start_btn.clicked.connect(self._on_start)
        ctrl_row.addWidget(self._start_btn)

        self._close_btn = QPushButton("Close Task")
        self._close_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,120);
                background: rgba(255,255,255,8);
                border: 1px solid rgba(255,255,255,12);
                border-radius: 12px;
                padding: 6px 16px;
                font-size: 10px;
                font-weight: 500;
            }
            QPushButton:hover { color: #EF4444; background: rgba(239,68,68,12); border-color: rgba(239,68,68,25); }
        """)
        self._close_btn.clicked.connect(self._on_close)
        self._close_btn.setEnabled(False)
        ctrl_row.addWidget(self._close_btn)

        ctrl_row.addStretch()

        self._session_id_label = QLabel("")
        self._session_id_label.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
        ctrl_row.addWidget(self._session_id_label)

        layout.addLayout(ctrl_row)

        # -- Send mode toggle --
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("Send Mode:")
        mode_lbl.setStyleSheet("color: rgba(255,255,255,120); font-size: 10px;")
        mode_row.addWidget(mode_lbl)

        self._auto_toggle = QPushButton("Auto")
        self._auto_toggle.setCheckable(True)
        self._auto_toggle.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,100);
                background: rgba(255,255,255,8);
                border: 1px solid rgba(255,255,255,12);
                border-radius: 10px;
                padding: 3px 14px;
                font-size: 10px;
                font-weight: 500;
            }
            QPushButton:checked {
                color: #7DD3FC;
                background: rgba(125,211,252,15);
                border: 1px solid rgba(125,211,252,30);
            }
            QPushButton:hover { background: rgba(255,255,255,12); }
        """)
        self._auto_toggle.toggled.connect(self._on_auto_toggle)
        mode_row.addWidget(self._auto_toggle)

        mode_row.addStretch()
        self._queue_badge = QLabel("")
        self._queue_badge.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: 600;")
        mode_row.addWidget(self._queue_badge)
        layout.addLayout(mode_row)

        # -- Annotation queue (manual mode) --
        self._queue_scroll = QScrollArea()
        self._queue_scroll.setWidgetResizable(True)
        self._queue_scroll.setMaximumHeight(100)
        self._queue_scroll.setStyleSheet("""
            QScrollArea { background: rgba(255,255,255,4); border: 1px solid rgba(255,255,255,8); border-radius: 8px; }
            QScrollBar:vertical { width: 3px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,20); border-radius: 2px; }
        """)
        self._queue_w = QWidget()
        self._queue_w.setStyleSheet("background: transparent;")
        self._queue_layout = QVBoxLayout(self._queue_w)
        self._queue_layout.setContentsMargins(8, 4, 8, 4)
        self._queue_layout.setSpacing(2)
        self._queue_scroll.setWidget(self._queue_w)
        layout.addWidget(self._queue_scroll)

        # -- Send / Request buttons --
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._send_btn = QPushButton("Send to Agentation")
        self._send_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: rgba(125,211,252,25);
                border: 1px solid rgba(125,211,252,40);
                border-radius: 14px;
                padding: 6px 18px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(125,211,252,35); }
            QPushButton:disabled { color: rgba(255,255,255,40); background: rgba(255,255,255,6); border-color: rgba(255,255,255,8); }
        """)
        self._send_btn.clicked.connect(self._on_send)
        self._send_btn.setEnabled(False)
        btn_row.addWidget(self._send_btn)

        self._request_btn = QPushButton("Request Agent")
        self._request_btn.setStyleSheet("""
            QPushButton {
                color: #34D399;
                background: rgba(52,211,153,12);
                border: 1px solid rgba(52,211,153,25);
                border-radius: 14px;
                padding: 6px 18px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(52,211,153,20); }
            QPushButton:disabled { color: rgba(255,255,255,40); background: rgba(255,255,255,6); border-color: rgba(255,255,255,8); }
        """)
        self._request_btn.clicked.connect(self._on_request)
        self._request_btn.setEnabled(False)
        btn_row.addWidget(self._request_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # -- Web Inspect button --
        web_row = QHBoxLayout()
        web_row.setSpacing(6)
        self._web_inspect_btn = QPushButton("🔍 Web Inspect (Test)")
        self._web_inspect_btn.setStyleSheet("""
            QPushButton {
                color: #A78BFA;
                background: rgba(167,139,250,10);
                border: 1px solid rgba(167,139,250,20);
                border-radius: 12px;
                padding: 4px 14px;
                font-size: 9px;
                font-weight: 500;
            }
            QPushButton:hover { background: rgba(167,139,250,18); }
            QPushButton:disabled { color: rgba(255,255,255,30); background: rgba(255,255,255,4); border-color: transparent; }
        """)
        self._web_inspect_btn.clicked.connect(self._on_web_inspect)
        self._web_inspect_btn.setEnabled(True)
        web_row.addWidget(self._web_inspect_btn)

        self._web_status_label = QLabel("")
        self._web_status_label.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
        web_row.addWidget(self._web_status_label)

        web_row.addStretch()
        layout.addLayout(web_row)

        # -- Status summary --
        summary_hdr = QLabel("Annotation Status")
        summary_hdr.setStyleSheet("color: rgba(255,255,255,120); font-size: 9px; font-weight: 600; letter-spacing: 0.5px;")
        layout.addWidget(summary_hdr)

        self._summary_grid = QGridLayout()
        self._summary_grid.setSpacing(4)
        self._summary_widgets = {}
        for label, color, key in [
            ("Pending", "#3B82F6", "pending"),
            ("Acknowledged", "#F59E0B", "acknowledged"),
            ("Resolved", "#22C55E", "resolved"),
            ("Dismissed", "#6B7280", "dismissed"),
        ]:
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: 600;")
            val = QLabel("0")
            val.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
            self._summary_widgets[key] = val
            row = len(self._summary_widgets) // 2
            col = (len(self._summary_widgets) - 1) % 2 * 2
            self._summary_grid.addWidget(lbl, row, col)
            self._summary_grid.addWidget(val, row, col + 1)
        layout.addLayout(self._summary_grid)

        layout.addStretch()

        # -- Notification / error label --
        self._notif_label = QLabel("")
        self._notif_label.setStyleSheet("color: rgba(255,255,255,80); font-size: 9px;")
        self._notif_label.setWordWrap(True)
        layout.addWidget(self._notif_label)

        # Initial state
        self._queue_scroll.hide()

    # -- Public API called by DynamicNotch --

    def set_agentation_status(self, available: bool):
        if available:
            self._status_dot.setStyleSheet("color: #22C55E; font-size: 10px;")
            self._status_dot.setText("●")
            self._status_text.setText("Agentation MCP connected")
            self._status_text.setStyleSheet("color: rgba(255,255,255,160); font-size: 11px;")
        else:
            self._status_dot.setStyleSheet("color: #EF4444; font-size: 10px;")
            self._status_dot.setText("●")
            self._status_text.setText("Agentation MCP offline")
            self._status_text.setStyleSheet("color: rgba(239,68,68,100); font-size: 11px;")

    def on_session_started(self, session: dict):
        self._start_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._request_btn.setEnabled(True)
        sid = session.get("id", "")
        self._session_id_label.setText(f"ID: {sid[:12]}...")
        self._notif_label.setText("Session active — capturing to Agentation")
        self._notif_label.setStyleSheet("color: #7DD3FC; font-size: 9px;")

    def on_session_closed(self):
        self._start_btn.setEnabled(True)
        self._close_btn.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._request_btn.setEnabled(False)
        self._session_id_label.setText("")
        self._clear_queue_display()
        self._queue_scroll.hide()
        for w in self._summary_widgets.values():
            w.setText("0")
        self._notif_label.setText("")

    def update_queue(self, count: int):
        if count > 0:
            self._queue_badge.setText(f"📦 {count} queued")
            self._queue_scroll.show()
        else:
            self._queue_badge.setText("")
            self._queue_scroll.hide()

    def update_status_summary(self, summary: dict, pending: list):
        for key, val in self._summary_widgets.items():
            val.setText(str(summary.get(key, 0)))
        total = summary.get("total", 0)
        if total > 0 and summary.get("resolved", 0) == total:
            self._notif_label.setText("✅ All annotations resolved")
            self._notif_label.setStyleSheet("color: #22C55E; font-size: 9px;")

    def show_error(self, msg: str):
        self._notif_label.setText(f"⚠ {msg}")
        self._notif_label.setStyleSheet("color: #EF4444; font-size: 9px;")

    def show_notification(self, msg: str):
        self._notif_label.setText(f"✓ {msg}")
        self._notif_label.setStyleSheet("color: #34D399; font-size: 9px;")

    def _clear_queue_display(self):
        while self._queue_layout.count() > 0:
            item = self._queue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # -- Internal callbacks --

    def _on_start(self):
        self._notch.start_agentation_session()

    def _on_close(self):
        self._notch.close_agentation_session()

    def _on_send(self):
        self._notch.send_annotations_to_agent()

    def _on_request(self):
        self._notch.send_annotations_to_agent()

    def _on_auto_toggle(self, checked):
        self._notch.set_auto_send(checked)
        if checked and self._notch._session_id:
            self._notch._flush_queue()

    def _on_web_inspect(self):
        """Test web inspect at center of screen."""
        screen = QApplication.primaryScreen()
        if not screen:
            self._web_status_label.setText("No screen")
            return
        ag = screen.availableGeometry()
        cx, cy = ag.center().x(), ag.center().y()
        self._web_status_label.setText("Inspecting...")
        self._web_status_label.setStyleSheet("color: #F59E0B; font-size: 9px;")
        QApplication.processEvents()

        result = self._notch.web_inspect_at(cx, cy)
        if result and result.get("status") == "ok":
            el = result.get("element", {})
            sel = el.get("selector", "?")
            comp = el.get("reactComponents", "")
            self._web_status_label.setText(f"Found: {sel}")
            self._web_status_label.setStyleSheet("color: #22C55E; font-size: 9px;")
            self.show_notification(f"React: {comp[:60]}" if comp else f"Element: {sel[:60]}")
        elif result and result.get("error"):
            self._web_status_label.setText(f"Error: {result['error'][:40]}")
            self._web_status_label.setStyleSheet("color: #EF4444; font-size: 9px;")
        else:
            self._web_status_label.setText("No response")
            self._web_status_label.setStyleSheet("color: #EF4444; font-size: 9px;")


# ---------------------------------------------------------------------------
# DynamicNotch  – main overlay widget
# ---------------------------------------------------------------------------
class DynamicNotch(QWidget):
    from agentation_client import AgentationClient, AgentationError
    from capture_store import CaptureRecord, CaptureStore
    from voice_input import VoiceInput

    def __init__(self, server: AgentServer = None):
        super().__init__()
        self._server = server
        self._state = "idle"           # "idle" | "expanded" | "settings"
        self._active_tab = "home"
        self._border_radius = 20.0
        self._docked = False
        self._anim_progress = 0.0      # 0 = idle, 1 = expanded
        self._expanded_size = (EXPANDED_W, EXPANDED_H)
        self._idle_rect = QRect()
        self._expanded_rect = QRect()

        # -- Agentation integration state --
        self._agentation = AgentationClient()
        self._agentation_available = False
        self._session_id = None
        self._session_url = ""
        self._auto_send = False
        self._annotation_queue: list[dict] = []  # unsent annotations (manual mode)
        self._annotation_statuses: dict[str, str] = {}  # annotation_id -> status

        self._capture_store = CaptureStore()
        self._voice = VoiceInput()
        self._voice.result_ready.connect(self._on_voice_result)
        self._voice.error.connect(self._on_voice_error)

        self._setup_window()
        self._build_ui()
        self._position_idle()
        self._anim_group = None

        # -- Agentation status poll timer --
        self._annotation_timer = QTimer(self)
        self._annotation_timer.timeout.connect(self._poll_annotation_status)
        self._annotation_timer.start(4000)

        # -- Initial health check --
        QTimer.singleShot(1000, self._check_agentation_health)

    # -- property for border-radius interpolation --
    def get_anim_progress(self):
        return self._anim_progress

    def set_anim_progress(self, v):
        self._anim_progress = v
        br = int(20 + (24 - 20) * v)
        self._border_radius = br
        self._container.setStyleSheet(f"""
            #notchContainer {{
                background: {NOTCH_BG};
                border: 1px solid {NOTCH_BORDER};
                border-radius: {br}px;
            }}
        """)

    anim_progress = pyqtProperty(float, get_anim_progress, set_anim_progress)

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------
    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MouseTracking, False)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(35)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(24, 20, 24, 20)   # room for shadow
        self._main_layout.setSpacing(0)

        self._container = QFrame()
        self._container.setObjectName("notchContainer")
        self._container.setStyleSheet(f"""
            #notchContainer {{
                background: {NOTCH_BG};
                border: 1px solid {NOTCH_BORDER};
                border-radius: 20px;
            }}
        """)
        cl = QVBoxLayout(self._container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # -- header stacked widget (idle <-> active) --
        self._header_stack = QStackedWidget()
        self._header_stack.setStyleSheet("background: transparent;")

        # page 0: idle header
        idle_w = QWidget()
        idle_l = QHBoxLayout(idle_w)
        idle_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_l.setContentsMargins(0, 0, 0, 0)
        self._logo = GlowingTriangleLogo()
        idle_l.addWidget(self._logo)
        self._header_stack.addWidget(idle_w)

        # page 1: active header
        active_w = QWidget()
        active_l = QHBoxLayout(active_w)
        active_l.setContentsMargins(16, 8, 16, 4)
        active_l.setSpacing(10)

        self._status_label = QLabel("Listening...")
        self._status_label.setStyleSheet("color: rgba(255,255,255,200); font-size: 12px; font-weight: 600;")
        active_l.addWidget(self._status_label)

        active_l.addStretch()

        self._waveform = MiniWaveformWidget()
        active_l.addWidget(self._waveform)

        self._pulse_dots = PulseDotsWidget()
        active_l.addWidget(self._pulse_dots)

        self._spinner = ThinkingSpinnerWidget()
        active_l.addWidget(self._spinner)

        self._header_stack.addWidget(active_w)
        cl.addWidget(self._header_stack)

        # -- tab header --
        self._tab_bar = QWidget()
        tb_l = QHBoxLayout(self._tab_bar)
        tb_l.setContentsMargins(16, 0, 16, 6)
        tb_l.setSpacing(4)

        self._tab_btns = {}
        for name in ("Home", "Agents", "Captures", "Session"):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(PILL_STYLE.format(r=12, p=4))
            btn.clicked.connect(lambda checked, n=name: self._switch_tab(n))
            self._tab_btns[name] = btn
            tb_l.addWidget(btn)
        self._tab_btns["Home"].setChecked(True)

        tb_l.addStretch()

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,100);
                background: transparent;
                border-radius: 12px;
                padding: 4px 10px;
                font-size: 14px;
            }
            QPushButton:hover { color: white; background: rgba(255,255,255,10); }
        """)
        self._settings_btn.clicked.connect(self._toggle_settings)
        tb_l.addWidget(self._settings_btn)

        cl.addWidget(self._tab_bar)

        # -- content stack --
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background: transparent;")
        self._home_view = HomeView()
        self._agents_view = AgentsView()
        self._captures_view = CapturesView(self)
        self._session_view = SessionView(self)
        self._content_stack.addWidget(self._home_view)
        self._content_stack.addWidget(self._agents_view)
        self._content_stack.addWidget(self._captures_view)
        self._content_stack.addWidget(self._session_view)
        cl.addWidget(self._content_stack, 1)

        self._main_layout.addWidget(self._container)

        # start collapsed
        self._header_stack.setCurrentIndex(0)
        self._tab_bar.hide()
        self._content_stack.hide()

    # ------------------------------------------------------------------
    # Positioning helpers
    # ------------------------------------------------------------------
    def _position_idle(self):
        screen = QApplication.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            x = ag.center().x() - IDLE_W // 2
            y = TOP_OFFSET
            self._idle_rect = QRect(x, y, IDLE_W, IDLE_H)
            self.setGeometry(self._idle_rect)

    def _calc_expanded_rect(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return QRect(0, 0, self._expanded_size[0], self._expanded_size[1])
        ag = screen.availableGeometry()
        ew, eh = self._expanded_size
        x = ag.center().x() - ew // 2
        y = TOP_OFFSET
        return QRect(x, y, ew, eh)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def expand(self, tab="home"):
        if self._state == "expanded" and self._active_tab == tab:
            return
        self._state = "expanded"
        self._active_tab = tab

        # show/hide widgets
        self._header_stack.setCurrentIndex(1)
        self._tab_bar.show()
        self._content_stack.show()

        idx = {"home": 0, "agents": 1, "captures": 2, "session": 3}.get(tab, 0)
        self._content_stack.setCurrentIndex(idx)
        for n, btn in self._tab_btns.items():
            btn.setChecked(n.lower() == tab)

        # size
        sizes = {
            "home": (EXPANDED_W, EXPANDED_H),
            "agents": (AGENTS_W, AGENTS_H),
            "captures": (SCREENSHOTS_W, SCREENSHOTS_H),
            "session": (440, 420),
        }
        self._expanded_size = sizes.get(tab, (EXPANDED_W, EXPANDED_H))
        self._animate_to(self._calc_expanded_rect(), 1.0)

    def collapse(self):
        if self._state == "idle":
            return
        self._state = "idle"

        self._animate_to(self._idle_rect, 0.0)

    def _animate_to(self, target_rect, target_progress):
        if self._anim_group and self._anim_group.state() == QParallelAnimationGroup.State.Running:
            self._anim_group.stop()

        geo_anim = QPropertyAnimation(self, b"geometry")
        geo_anim.setEndValue(target_rect)
        geo_anim.setDuration(ANIM_MS)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        br_anim = QPropertyAnimation(self, b"anim_progress")
        br_anim.setEndValue(target_progress)
        br_anim.setDuration(ANIM_MS)
        br_anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        br_anim.finished.connect(self._on_anim_finished)

        self._anim_group = QParallelAnimationGroup()
        self._anim_group.addAnimation(geo_anim)
        self._anim_group.addAnimation(br_anim)
        self._anim_group.start()

    def _on_anim_finished(self):
        if self._state == "idle":
            self._header_stack.setCurrentIndex(0)
            self._tab_bar.hide()
            self._content_stack.hide()

    # ------------------------------------------------------------------
    # Mouse events  (hover to expand)
    # ------------------------------------------------------------------
    def enterEvent(self, event):
        self.expand(self._active_tab)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._docked:
            self.collapse()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Tab / settings switching
    # ------------------------------------------------------------------
    def _switch_tab(self, name):
        self.expand(name.lower())

    def _toggle_settings(self):
        if self._state == "settings":
            self._settings_btn.setStyleSheet(self._settings_btn.styleSheet().replace("color: white;", "color: rgba(255,255,255,100);"))
            self.expand(self._active_tab)
        else:
            self._settings_btn.setStyleSheet(self._settings_btn.styleSheet().replace("color: rgba(255,255,255,100);", "color: white;"))
            self._state = "settings"
            sizes = {"home": (EXPANDED_W, EXPANDED_H), "agents": (AGENTS_W, AGENTS_H), "captures": (SCREENSHOTS_W, SCREENSHOTS_H)}
            self._expanded_size = (SETTINGS_W, SETTINGS_H)
            self._animate_to(self._calc_expanded_rect(), 1.0)

    # ------------------------------------------------------------------
    # Dock / Undock
    # ------------------------------------------------------------------
    def set_docked(self, docked):
        self._docked = docked
        if docked:
            self.expand(self._active_tab)

    # ------------------------------------------------------------------
    # Public API for server
    # ------------------------------------------------------------------
    def set_status(self, text):
        self._status_label.setText(text)

    def update_status(self, text):
        self._status_label.setText(text)

    # ------------------------------------------------------------------
    # Agentation Integration
    # ------------------------------------------------------------------

    def _check_agentation_health(self):
        try:
            self._agentation.health()
            self._agentation_available = True
            self._session_view.set_agentation_status(True)
        except AgentationError:
            self._agentation_available = False
            self._session_view.set_agentation_status(False)

    def _poll_annotation_status(self):
        if not self._session_id or not self._agentation_available:
            return
        try:
            pending = self._agentation.get_pending(self._session_id)
            pending_ids = {a["id"] for a in pending}
            for a in pending:
                self._annotation_statuses[a["id"]] = a.get("status", "pending")
            resolved_ids = set(self._annotation_statuses.keys()) - pending_ids
            summary = {"pending": len(pending_ids), "acknowledged": 0, "resolved": 0, "dismissed": 0, "total": len(self._annotation_statuses)}
            for aid, st in self._annotation_statuses.items():
                if st == "acknowledged":
                    summary["acknowledged"] += 1
                elif st == "resolved":
                    summary["resolved"] += 1
                elif st == "dismissed":
                    summary["dismissed"] += 1
            self._session_view.update_status_summary(summary, pending)
        except AgentationError:
            pass

    # -- Session lifecycle --

    def start_agentation_session(self, url: str = "bluely://session", project_name: str = ""):
        try:
            session = self._agentation.create_session(url, project_id=project_name or None)
            self._session_id = session["id"]
            self._session_url = url
            self._annotation_statuses.clear()
            self._annotation_queue.clear()
            self._session_view.on_session_started(session)
            self._status_label.setText(f"● Session {session['id'][:8]}")
        except AgentationError as e:
            self._session_view.show_error(f"Failed to create session: {e}")

    def close_agentation_session(self):
        if not self._session_id:
            return
        try:
            self._agentation.close_session(self._session_id)
        except AgentationError:
            pass
        self._session_id = None
        self._session_url = ""
        self._annotation_statuses.clear()
        self._annotation_queue.clear()
        self._session_view.on_session_closed()
        self._status_label.setText("Listening...")

    # -- Sending annotations --

    def queue_annotation(self, annotation_data: dict):
        self._annotation_queue.append(annotation_data)
        self._session_view.update_queue(len(self._annotation_queue))
        if self._auto_send and self._session_id:
            self._flush_queue()

    def _flush_queue(self):
        if not self._session_id or not self._annotation_queue:
            return
        batch = list(self._annotation_queue)
        self._annotation_queue.clear()
        self._session_view.update_queue(0)
        for item in batch:
            try:
                result = self._agentation.add_annotation(self._session_id, item)
                if result and "id" in result:
                    self._annotation_statuses[result["id"]] = "pending"
            except AgentationError as e:
                self._session_view.show_error(f"Send failed: {e}")
        self._poll_annotation_status()

    def send_annotations_to_agent(self):
        self._flush_queue()
        if self._session_id:
            try:
                resp = self._agentation.request_action(self._session_id, "Annotations ready for review")
                self._session_view.show_notification(f"Sent to agent ({resp.get('delivered', {}).get('total', 0)} endpoints)")
            except AgentationError as e:
                self._session_view.show_error(f"Action request failed: {e}")

    def set_auto_send(self, enabled: bool):
        self._auto_send = enabled

    # ------------------------------------------------------------------
    # Capture Store
    # ------------------------------------------------------------------

    def get_capture_store(self) -> CaptureStore:
        return self._capture_store

    def do_capture(self, annotation_text: str = ""):
        cursor_pos = QCursor.pos()
        cx, cy = cursor_pos.x(), cursor_pos.y()

        import mss
        from PIL import Image
        import datetime

        os.makedirs("screenshots", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join("screenshots", f"capture_{ts}.png")

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            pil_img = Image.frombytes("RGB", img.size, img.rgb)
            pil_img.save(path, "PNG")

        web_data = self.web_inspect_at(cx, cy)

        record = CaptureRecord(
            id=ts,
            timestamp=ts,
            screenshot_path=path,
            annotation_text=annotation_text,
            cursor_x=cx,
            cursor_y=cy,
        )
        if web_data and web_data.get("status") == "ok":
            el = web_data.get("element", {})
            record.element_selector = el.get("selector", "")
            record.element_path = el.get("elementPath", "")
            record.react_components = el.get("reactComponents", "")
            record.computed_styles = json.dumps(el.get("computedStyles", {}))
            record.accessibility = json.dumps(el.get("accessibility", {}))
            if el.get("boundingBox"):
                record.bounding_box = el["boundingBox"]
            if el.get("text"):
                record.selected_text = el["text"]

        self._capture_store.add(record)
        self._captures_view.add_capture(record)

        if self._session_id:
            self._queue_capture_as_annotation(record)

        self._session_view.show_notification(f"Captured: {os.path.basename(path)}")

    def _queue_capture_as_annotation(self, record: CaptureRecord):
        img_url = f"http://127.0.0.1:5001/screenshots/{os.path.basename(record.screenshot_path)}"
        annotation = {
            "x": record.cursor_x,
            "y": record.cursor_y,
            "comment": f"![screenshot]({img_url})" + (f"\n\n{record.annotation_text}" if record.annotation_text else ""),
            "element": record.element_selector or "web_page",
            "elementPath": record.element_path or record.screenshot_path,
            "selectedText": record.annotation_text or record.selected_text or "",
            "kind": "feedback",
        }
        if record.bounding_box:
            annotation["boundingBox"] = record.bounding_box
        if record.computed_styles:
            annotation["computedStyles"] = record.computed_styles
        if record.react_components:
            annotation["reactComponents"] = record.react_components
        if record.accessibility:
            annotation["accessibility"] = record.accessibility

        self.queue_annotation(annotation)
        record.agentation_status = "sent"
        self._capture_store.update(record)
        self._captures_view.update_card_status(record)

    def open_capture(self, record: CaptureRecord):
        QDesktopServices.openUrl(QUrl.fromLocalFile(record.screenshot_path))

    def copy_capture_code(self, record: CaptureRecord):
        clipboard = QApplication.clipboard()
        clipboard.setText(record.formatted_context())
        self._session_view.show_notification("Capture context copied to clipboard")

    def send_capture_to_agent(self, record: CaptureRecord):
        if not self._session_id:
            self._session_view.show_error("No active session. Start a task first.")
            return
        self._queue_capture_as_annotation(record)
        if self._session_id:
            try:
                resp = self._agentation.request_action(self._session_id, "Annotations ready for review")
                self._session_view.show_notification(f"Capture sent ({resp.get('delivered', {}).get('total', 0)} endpoints)")
            except AgentationError as e:
                self._session_view.show_error(f"Action request failed: {e}")

    # ------------------------------------------------------------------
    # Voice Capture
    # ------------------------------------------------------------------

    def start_voice_capture(self):
        self._voice.start_listening()

    def stop_voice_capture(self):
        self._voice.stop_listening()

    def _on_voice_result(self, text: str):
        self._captures_view.on_voice_result(text)
        self.do_capture(annotation_text=text)

    def _on_voice_error(self, msg: str):
        self._captures_view.on_voice_error(msg)

    # ------------------------------------------------------------------
    # Web Inspect  (browser extension via Flask)
    # ------------------------------------------------------------------

    def web_inspect_at(self, x: int, y: int) -> dict | None:
        """Inspect web element at screen coordinates via browser extension."""
        try:
            import urllib.request as _req
            body = json.dumps({"x": x, "y": y}).encode()
            resp = _req.urlopen(
                _req.Request(
                    "http://127.0.0.1:5001/inspect",
                    data=body,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=6,
            )
            return json.loads(resp.read().decode())
        except Exception:
            return None

    def capture_with_web_inspect(self, screenshot_b64: str, cursor_x: int, cursor_y: int, annotation_text: str = ""):
        """Capture a screenshot + web inspect at cursor, then queue annotation."""
        # Save screenshot via Flask
        try:
            import urllib.request as _req
            body = json.dumps({"image": screenshot_b64, "annotation": annotation_text}).encode()
            resp = _req.urlopen(
                _req.Request(
                    "http://127.0.0.1:5001/screenshots/save",
                    data=body,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=10,
            )
            saved = json.loads(resp.read().decode())
        except Exception as e:
            self._session_view.show_error(f"Screenshot save failed: {e}")
            return

        # Build annotation payload
        annotation = {
            "x": cursor_x,
            "y": cursor_y,
            "comment": f"![screenshot](http://127.0.0.1:5001{saved['url']})\n\n{annotation_text}" if annotation_text else f"![screenshot](http://127.0.0.1:5001{saved['url']})",
            "element": "web_page",
            "elementPath": saved["path"],
            "boundingBox": {"x": cursor_x - 50, "y": cursor_y - 50, "width": 100, "height": 100},
            "selectedText": annotation_text or "",
            "kind": "feedback",
        }

        # Try web inspect enrichment
        web_data = self.web_inspect_at(cursor_x, cursor_y)
        if web_data and web_data.get("status") == "ok":
            el = web_data.get("element", {})
            annotation["element"] = el.get("selector", "web_page")
            annotation["elementPath"] = el.get("elementPath", saved["path"])
            annotation["computedStyles"] = json.dumps(el.get("computedStyles", {}))
            annotation["reactComponents"] = el.get("reactComponents", "")
            annotation["accessibility"] = json.dumps(el.get("accessibility", {}))
            if el.get("boundingBox"):
                annotation["boundingBox"] = el["boundingBox"]
            if el.get("text"):
                annotation["selectedText"] = el["text"]
            self._session_view.show_notification("Web element captured")

        self.queue_annotation(annotation)
