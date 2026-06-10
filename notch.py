import math
import random
import os
import json

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QRect, QPoint, QSize, pyqtProperty, QUrl
)
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QBrush, QPen, QFont, QFontMetrics,
    QPixmap, QPainterPath, QRegion, QTransform, QDesktopServices, QAction,
    QConicalGradient, QPalette
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QGraphicsDropShadowEffect, QFrame, QSizePolicy,
    QSpacerItem, QScrollArea, QGridLayout, QButtonGroup, QSlider,
    QListWidget, QListWidgetItem, QProgressBar, QFileDialog, QMessageBox
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from server import AgentServer

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
class ScreenshotThumbnail(QFrame):
    deleted = __import__("PyQt6.QtCore", fromlist=["pyqtSignal"]).pyqtSignal(object)

    from PyQt6.QtCore import pyqtSignal
    deleted = pyqtSignal(object)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path
        self._preview = None
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedSize(130, 100)
        self.setStyleSheet("""
            ScreenshotThumbnail {
                background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,10);
                border-radius: 10px;
            }
            ScreenshotThumbnail:hover {
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,18);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._img_label = QLabel()
        self._img_label.setFixedSize(122, 72)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._img_label)

        bottom = QHBoxLayout()
        bottom.setSpacing(0)

        name_label = QLabel(os.path.basename(self._path)[:16])
        name_label.setStyleSheet("color: rgba(255,255,255,100); font-size: 9px;")
        bottom.addWidget(name_label)
        bottom.addStretch()

        del_btn = QPushButton("×")
        del_btn.setFixedSize(16, 16)
        del_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,80);
                background: transparent;
                border: none;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { color: #EF4444; }
        """)
        del_btn.clicked.connect(self._delete)
        bottom.addWidget(del_btn)

        layout.addLayout(bottom)

        self._load_thumb()

    def _load_thumb(self):
        pix = QPixmap(self._path)
        if not pix.isNull():
            self._preview = pix
            self._img_label.setPixmap(pix.scaled(122, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _delete(self):
        reply = QMessageBox.question(self, "Delete", f"Delete {os.path.basename(self._path)}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self._path)
            except Exception:
                pass
            self.deleted.emit(self)

    def mouseDoubleClickEvent(self, event):
        if self._preview:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Screenshot Detail")
            dlg.setIconPixmap(self._preview.scaled(480, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            dlg.exec()


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
class ScreenshotsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumbnails = []
        self._setup_ui()
        self._scan_existing()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        hdr = QLabel("Captured Screenshots")
        hdr.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        top.addWidget(hdr)
        top.addStretch()

        capture_btn = QPushButton("+ Capture")
        capture_btn.setStyleSheet("""
            QPushButton {
                color: #7DD3FC;
                background: rgba(125,211,252,12);
                border: 1px solid rgba(125,211,252,25);
                border-radius: 12px;
                padding: 4px 14px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(125,211,252,20); }
        """)
        capture_btn.clicked.connect(self._capture)
        top.addWidget(capture_btn)

        layout.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 3px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,20); border-radius: 2px; }
        """)
        self._grid_w = QWidget()
        self._grid_w.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_w)
        self._grid.setSpacing(6)
        scroll.setWidget(self._grid_w)
        layout.addWidget(scroll, 1)

    def _capture(self):
        try:
            import mss, io, base64
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

            self._add_thumbnail(path)
        except Exception as e:
            QMessageBox.warning(self, "Capture Error", str(e))

    def _scan_existing(self):
        if not os.path.isdir("screenshots"):
            return
        for fn in sorted(os.listdir("screenshots"), reverse=True):
            if fn.lower().endswith((".png", ".jpg", ".jpeg")):
                self._add_thumbnail(os.path.join("screenshots", fn))

    def _add_thumbnail(self, path):
        thumb = ScreenshotThumbnail(path)
        thumb.deleted.connect(self._remove_thumbnail)
        self._thumbnails.append(thumb)
        row = (len(self._thumbnails) - 1) // 3
        col = (len(self._thumbnails) - 1) % 3
        self._grid.addWidget(thumb, row, col)

    def _remove_thumbnail(self, thumb):
        self._grid.removeWidget(thumb)
        self._thumbnails.remove(thumb)
        thumb.deleteLater()


# ---------------------------------------------------------------------------
# DynamicNotch  – main overlay widget
# ---------------------------------------------------------------------------
class DynamicNotch(QWidget):
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

        self._setup_window()
        self._build_ui()
        self._position_idle()
        self._anim_group = None

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
        for name in ("Home", "Agents", "Screenshots"):
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
        self._screens_view = ScreenshotsView()
        self._content_stack.addWidget(self._home_view)
        self._content_stack.addWidget(self._agents_view)
        self._content_stack.addWidget(self._screens_view)
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

        idx = {"home": 0, "agents": 1, "screenshots": 2}.get(tab, 0)
        self._content_stack.setCurrentIndex(idx)
        for n, btn in self._tab_btns.items():
            btn.setChecked(n.lower() == tab)

        # size
        sizes = {
            "home": (EXPANDED_W, EXPANDED_H),
            "agents": (AGENTS_W, AGENTS_H),
            "screenshots": (SCREENSHOTS_W, SCREENSHOTS_H),
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
            sizes = {"home": (EXPANDED_W, EXPANDED_H), "agents": (AGENTS_W, AGENTS_H), "screenshots": (SCREENSHOTS_W, SCREENSHOTS_H)}
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
