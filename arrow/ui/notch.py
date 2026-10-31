import logging
import math
import os
import random
import threading

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
        QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arrow.providers.runner import build_run_request, create_provider
from arrow.server.server import AgentServer
from arrow.storage.settings import get_project_dir, get_ui_preferences, set_project_dir
from arrow.ui.clipboard import copy_capture
from arrow.ui.settings_panel import SettingsPanel

log = logging.getLogger("arrow.ui.notch")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NOTCH_BG = "rgba(9, 9, 11, 240)"
NOTCH_BORDER = "rgba(255, 255, 255, 12)"

# A slim visible pill inside a slightly larger hover/click target.
IDLE_W, IDLE_H = 152, 32
HOME_W, HOME_H = 340, 380
AGENTS_W, AGENTS_H = 400, 400
SCREENSHOTS_W, SCREENSHOTS_H = 520, 640

TOP_OFFSET = 8
ANIM_MS = 350

ACCENT_COLORS = [
    ("#7DD3FC", "Sky"), ("#34D399", "Emerald"), ("#A78BFA", "Violet"),
    ("#F472B6", "Pink"), ("#FB923C", "Orange"), ("#FBBF24", "Amber"),
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

TAB_STYLE = """
    QPushButton {
        color: rgba(255,255,255,100);
        background: transparent;
        border: none;
        border-radius: 12px;
        padding: 5px 18px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }
    QPushButton:checked {
        color: white;
        background: rgba(255,255,255,12);
    }
    QPushButton:hover {
        color: rgba(255,255,255,180);
        background: rgba(255,255,255,6);
    }
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
        angle = 0.0
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
# MiniWaveformWidget  – 5-bar jitter visualiser
# ---------------------------------------------------------------------------
class MiniWaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = [0.2, 0.5, 0.8, 0.5, 0.3]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._jitter)
        self.setFixedSize(44, 22)
        # Timer starts stopped — only runs when visible/recording
        self._active = False

    def start(self):
        if not self._active:
            self._active = True
            self._timer.start(55)

    def stop(self):
        if self._active:
            self._active = False
            self._timer.stop()

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
# Change-request formatting helpers
# ---------------------------------------------------------------------------

INTENT_LABELS = {
    "move_element": "Move element",
    "resize_element": "Resize element",
    "restyle_element": "Restyle element",
    "replace_content": "Replace content",
    "remove_element": "Remove element",
    "add_element": "Add element",
    "align_elements": "Align elements",
    "change_spacing": "Change spacing",
    "change_responsive_behavior": "Change responsive behavior",
    "fix_interaction": "Fix interaction",
    "fix_visual_bug": "Fix visual bug",
    "inspect_or_explain": "Inspect / explain",
    "unknown": "Unknown",
}


def _anchor_label(anchor: dict) -> str:
    from arrow.intent.prompt_builder import anchor_label
    return anchor_label(anchor)


def format_change_request(cr: dict) -> str:
    from arrow.intent.prompt_builder import format_prompt
    return format_prompt(cr)


# ---------------------------------------------------------------------------
# ScreenshotThumbnail  – clickable thumbnail with delete, copy, send-to-AI
# ---------------------------------------------------------------------------
class ScreenshotThumbnail(QFrame):
    deleted = pyqtSignal(object)
    connection_requested = pyqtSignal()
    provider_finished = pyqtSignal(object, object, object)  # event, request, name

    def __init__(self, path, annotation_text="", timestamp="", window_title="",
                 change_request=None, parent=None):
        super().__init__(parent)
        self._path = path
        self._text = annotation_text
        self._timestamp = timestamp
        self._window_title = window_title
        self._change_request = change_request or {}
        self._preview = None
        self._provider_buttons = {}
        self._awaiting_prompt_copy = False
        # Queued: emitted from a worker thread, delivered on the main thread.
        self.provider_finished.connect(self._on_provider_finished)
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedWidth(320)
        self.setMinimumHeight(490)
        self.setStyleSheet("""
            ScreenshotThumbnail {
                background: #18181b;
                border: 1px solid rgba(255,255,255,10);
                border-radius: 12px;
            }
            ScreenshotThumbnail:hover {
                border: 1px solid rgba(255,255,255,30);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        img_container = QWidget()
        img_container.setFixedSize(320, 160)
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(0)
        
        self._img_label = QLabel(img_container)
        self._img_label.setFixedSize(320, 160)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("background: #09090b; border-top-left-radius: 12px; border-top-right-radius: 12px;")

        app_name = "App"
        if self._window_title:
            parts = self._window_title.split("-")
            app_name = parts[-1].strip() if len(parts) > 1 else self._window_title.strip()
            if len(app_name) > 16:
                app_name = app_name[:14] + "..."
        if not app_name:
            app_name = "App"

        self._badge = QLabel(app_name, img_container)
        self._badge.setStyleSheet("""
            background: rgba(80,80,80,200);
            color: white;
            border-radius: 10px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        self._badge.move(12, 12)

        layout.addWidget(img_container)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(16, 12, 16, 12)

        text_str = self._text if self._text else "Visual highlight"
        self._text_lbl = QLabel(text_str)
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setStyleSheet("color: #F8FAFC; font-size: 13px; font-weight: 600; line-height: 1.4;")
        self._text_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        text_layout.addWidget(self._text_lbl)

        # Compiled intent panel (from the orchestrator's change request)
        if self._change_request:
            text_layout.addWidget(self._build_intent_panel())

        text_layout.addStretch()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        app_lbl = QLabel(app_name)
        app_lbl.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500; border: none;")

        time_str = "just now"
        if self._timestamp:
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(self._timestamp)
                diff = datetime.datetime.now() - dt
                secs = int(diff.total_seconds())
                if secs < 60:
                    time_str = f"{secs}s ago"
                elif secs < 3600:
                    time_str = f"{secs//60}m ago"
                elif secs < 86400:
                    time_str = f"{secs//3600}h ago"
                else:
                    time_str = f"{secs//86400}d ago"
            except Exception:
                pass

        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("color: #64748B; font-size: 11px; border: none;")

        footer.addWidget(app_lbl)
        footer.addStretch()
        footer.addWidget(time_lbl)

        text_layout.addLayout(footer)
        layout.addLayout(text_layout)

        try:
            pix = QPixmap(self._path)
            if not pix.isNull():
                scaled = pix.scaled(320, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                self._img_label.setPixmap(scaled)
                self._preview = pix
        except Exception:
            pass

    def _build_intent_panel(self):
        """Compact card section showing the compiled change request."""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,6);
                border: 1px solid rgba(255,255,255,8);
                border-radius: 10px;
            }
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        self._chip_lbl = QLabel("")
        self._chip_lbl.setStyleSheet("""
            background: rgba(167,139,250,30);
            color: #C4B5FD;
            border-radius: 8px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: 700;
        """)
        header.addWidget(self._chip_lbl)

        self._conf_lbl = QLabel("")
        self._conf_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600; border: none;")
        header.addWidget(self._conf_lbl)

        header.addStretch()
        v.addLayout(header)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        edit_row.addWidget(self._action_button("Review", self._edit_instruction))
        self._combined_copy_button = self._action_button("Copy image + prompt", self._copy_request)
        edit_row.addWidget(self._combined_copy_button)
        v.addLayout(edit_row)

        copy_row = QHBoxLayout()
        copy_row.addWidget(self._action_button("Image only", lambda: self._copy_request('image')))
        copy_row.addWidget(self._action_button("Prompt only", lambda: self._copy_request('text')))
        v.addLayout(copy_row)

        send_row = QHBoxLayout()
        self._target_combo = QComboBox()
        self._target_combo.setStyleSheet('QComboBox {background:#27272a;color:#fafafa;border:1px solid #3f3f46;border-radius:6px;padding:4px;} QComboBox QAbstractItemView {background:#18181b;color:#fafafa;}')
        from arrow.providers.handoff import available_clients
        for name, installed in available_clients().items():
            self._target_combo.addItem(name)
            self._target_combo.setItemData(self._target_combo.count()-1,
                                          'Installed' if installed else 'Connect or install in Settings', Qt.ItemDataRole.ToolTipRole)
        send_row.addWidget(self._target_combo, 1)
        send = self._action_button('Open in agent', lambda: self._send_to_provider(self._target_combo.currentText()))
        send.setToolTip('CLI targets start an interactive session with the context. Desktop targets may require pasting the copied context.')
        send_row.addWidget(send)
        self._provider_buttons = {'send': send}
        v.addLayout(send_row)
        v.addWidget(self._action_button('Connect agents / choose repository', self.connection_requested.emit))
        self._action_status = QLabel("")
        self._action_status.setWordWrap(True)
        self._action_status.setStyleSheet("color: #94A3B8; font-size: 10px; border: none;")
        v.addWidget(self._action_status)

        # Refreshable info section (summary / source→destination / likely file).
        self._info_widget = QWidget()
        self._info_v = QVBoxLayout(self._info_widget)
        self._info_v.setContentsMargins(0, 0, 0, 0)
        self._info_v.setSpacing(6)
        v.addWidget(self._info_widget)

        self._fill_intent_content()
        return panel

    def _fill_intent_content(self):
        """(Re)build the chip, confidence and info section from the current request."""
        cr = self._change_request
        self._chip_lbl.setText("Capture context")

        conf = cr.get("confidence")
        self._conf_lbl.setText(f"{round(conf * 100)}%" if conf is not None else "")
        self._conf_lbl.hide()

        while self._info_v.count():
            item = self._info_v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if cr.get("summary"):
            summary = QLabel(cr["summary"])
            summary.setWordWrap(True)
            summary.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: 500; border: none;")
            self._info_v.addWidget(summary)

        src = _anchor_label(cr.get("source") or {})
        dst = _anchor_label(cr.get("destination") or {})
        if src or dst:
            arrow_lbl = QLabel(f"{src}  →  {dst}" if src and dst else src or dst)
            arrow_lbl.setWordWrap(True)
            arrow_lbl.setStyleSheet("color: #7DD3FC; font-size: 11px; font-weight: 500; border: none;")
            self._info_v.addWidget(arrow_lbl)

        files = cr.get("likely_files") or []
        if files:
            f = files[0]
            loc = f["source_file"]
            if f.get("source_line") is not None:
                loc += f":{f['source_line']}"
            file_lbl = QLabel(f"📄 {loc}")
            file_lbl.setStyleSheet("color: #94A3B8; font-size: 10px; font-family: Consolas, monospace; border: none;")
            self._info_v.addWidget(file_lbl)

        self._info_v.addStretch()

    def _edit_instruction(self):
        review = getattr(self.window(), 'show_capture_review', None)
        if review:
            review(self)

    def _apply_review(self, record):
        self._change_request = record.change_request or {}
        self._text = record.annotation_text or ''
        self._text_lbl.setText(self._text)
        self._awaiting_prompt_copy = False
        self._combined_copy_button.setText('Copy image + prompt')
        self._fill_intent_content()

    def _export_payload(self):
        from arrow.context.capture_bundle import build_capture_bundle
        capture_id = self._change_request.get('capture_id')
        if capture_id:
            try:
                bundle = build_capture_bundle(capture_id)
                return bundle.prompt_text, bundle.annotated_path or self._path
            except LookupError:
                pass  # Legacy/unpersisted cards still offer their own image/text.
        return format_change_request(self._change_request) or self._text, self._path

    @staticmethod
    def _action_button(text, slot):
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,10);
                color: white;
                border-radius: 10px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(255,255,255,18); }
            QPushButton:disabled { color: rgba(255,255,255,45); }
        """)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _provider_available(name: str) -> bool:
        try:
            return create_provider(name).detect()
        except Exception:
            return False

    def _copy_request(self, mode='both', reviewed=False):
        # QPushButton.clicked may pass a checked boolean.
        if isinstance(mode, bool):
            mode = 'both'
        review = getattr(self.window(), 'show_capture_review', None)
        if review and not reviewed:
            from arrow.storage.capture_store import CaptureStore
            record = CaptureStore().get(self._change_request.get('capture_id'))
            if record is not None and not record.capture_context.get('review', {}).get('instruction_reviewed'):
                review(self, copy_mode=mode)
                return
        text, image_path = self._export_payload()
        if mode == 'both' and get_ui_preferences()['clipboard_mode'] == 'two_step':
            try:
                if not self._awaiting_prompt_copy:
                    copy_capture(text, image_path, mode='image')
                    self._awaiting_prompt_copy = True
                    self._combined_copy_button.setText('2 · Copy prompt')
                    self._action_status.setText('1/2 · Image copied. Paste it into ChatGPT to attach it, '
                                                'then click “2 · Copy prompt” and paste again.')
                else:
                    copy_capture(text, image_path, mode='text')
                    self._awaiting_prompt_copy = False
                    self._combined_copy_button.setText('Copy image + prompt')
                    self._action_status.setText('2/2 · Prompt copied. Paste it alongside the attached image.')
            except ValueError as exc:
                self._action_status.setText(str(exc))
            return
        try:
            copy_capture(text, image_path, mode=mode)
        except ValueError as exc:
            self._action_status.setText(str(exc))
            return
        self._awaiting_prompt_copy = False
        self._combined_copy_button.setText('Copy image + prompt')
        messages = {
            'both': "Image + prompt copied. If your app pastes only one, use Image only / Prompt only.",
            'image': "Annotated image copied.", 'text': "Prompt copied.",
        }
        self._action_status.setText(messages[mode])

    def _send_to_provider(self, name: str, reviewed=False):
        """Send the compiled change request straight to Codex / Claude Code."""
        cr = self._change_request
        if not cr:
            return
        if not reviewed:
            review = getattr(self.window(), 'show_capture_review', None)
            if review:
                review(self, send_to=name)
                return

        request = build_run_request(
            cr.get("capture_id") or "",
            cr,
            format_change_request(cr),
            fallback_repo=get_project_dir(),
        )
        if request is None:
            self._action_status.setText('Choose your project repository in Settings › Agents before sending.')
            self.connection_requested.emit()
            return

        self._set_sending(True, name)
        threading.Thread(
            target=self._run_provider_thread, args=(None, request, name), daemon=True
        ).start()

    def _run_provider_thread(self, provider, request, name: str):
        from arrow.providers.handoff import HandoffResult, handoff_capture
        try:
            final = handoff_capture(request.capture_id, name)
        except Exception as error:
            final = HandoffResult(str(error), status='failed')
        # Emitting a queued signal is thread-safe and delivers on the main thread.
        try:
            self.provider_finished.emit(final, request, name)
        except RuntimeError:
            log.info("Provider completed after its capture card was closed")

    def _on_provider_finished(self, final, request, name: str):
        self._set_sending(False, name)
        if final.prompt_text:
            QApplication.clipboard().setText(final.prompt_text)
        self._action_status.setText(final.message)

    def _set_sending(self, active: bool, name: str):
        for n, btn in getattr(self, "_provider_buttons", {}).items():
            btn.setEnabled(not active)
            btn.setText("Opening…" if active else "Open in agent")
        if hasattr(self, '_action_status'):
            self._action_status.setText(f"Sending image and prompt to {name}…" if active else "")

    def mouseDoubleClickEvent(self, event):
        if self._preview:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Screenshot Detail")
            dlg.setIconPixmap(self._preview.scaled(480, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            dlg.exec()


class ScreenshotsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumbnails = []
        self._setup_ui()
        self._scan_existing()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(20)

        # --- Top Toolbar ---
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        
        pill_frame = QFrame()
        pill_frame.setStyleSheet("""
            QFrame {
                background: #18181b;
                border: 1px solid rgba(255,255,255,10);
                border-radius: 18px;
            }
        """)
        pill_layout = QHBoxLayout(pill_frame)
        pill_layout.setContentsMargins(8, 4, 8, 4)
        pill_layout.setSpacing(8)

        for icon, tooltip in [("New capture", "Draw and speak")]:
            btn = QPushButton(icon)
            btn.setFixedSize(110, 32)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: white;
                    font-size: 15px;
                    border: none;
                    border-radius: 14px;
                }
                QPushButton:hover { background: rgba(255,255,255,10); }
            """)
            btn.clicked.connect(self._highlight)
            pill_layout.addWidget(btn)

        top.addWidget(pill_frame)
        top.addStretch()

        self._repo_lbl = QLabel("")
        self._repo_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500; background: transparent; border: none;")
        top.addWidget(self._repo_lbl)

        repo_btn = QPushButton("📁")
        repo_btn.setFixedSize(36, 36)
        repo_btn.setToolTip("Select repository")
        repo_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #A1A1AA;
                font-size: 18px;
                border: none;
            }
            QPushButton:hover { color: white; }
        """)
        repo_btn.clicked.connect(self._select_repository)
        top.addWidget(repo_btn)

        doc_btn = QPushButton("⚙")
        doc_btn.setToolTip("Settings: capture, agent connections, clipboard and notch")
        doc_btn.clicked.connect(self._settings)
        doc_btn.setFixedSize(36, 36)
        doc_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #A1A1AA;
                font-size: 18px;
                border: none;
            }
            QPushButton:hover { color: white; }
        """)
        top.addWidget(doc_btn)
        
        layout.addLayout(top)

        # --- Second Row ---
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)

        self._all_btn = QPushButton("All 0")
        self._all_btn.setFixedHeight(32)
        self._all_btn.setStyleSheet("""
            QPushButton {
                background: white;
                color: black;
                border-radius: 16px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        row2.addWidget(self._all_btn)
        self._history = QComboBox()
        self._history.setMinimumWidth(110)
        self._history.setStyleSheet('color: white; background: #27272a; padding: 6px; border-radius: 8px;')
        self._history.currentIndexChanged.connect(self._select_capture)
        row2.addWidget(self._history, 1)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(32, 32)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #18181b;
                color: white;
                border-radius: 16px;
                font-size: 18px;
            }
            QPushButton:hover { background: #27272a; }
        """)
        add_btn.clicked.connect(self._highlight)
        add_btn.hide()

        row2.addStretch()

        copy_btn = QPushButton("📄 Copy all prompts")
        copy_btn.setFixedHeight(32)
        copy_btn.setStyleSheet("""
            QPushButton {
                background: #18181b;
                border-radius: 16px;
                color: white;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background: #27272a; }
        """)
        copy_btn.clicked.connect(self._copy_all)
        copy_btn.hide()

        trash_btn = QPushButton("🗑️")
        trash_btn.setFixedSize(32, 32)
        trash_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #A1A1AA;
                font-size: 16px;
                border: none;
            }
            QPushButton:hover { color: #EF4444; }
        """)
        trash_btn.clicked.connect(self._clear_all)
        row2.addWidget(trash_btn)

        layout.addLayout(row2)

        # --- Cards Area ---
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: #3f3f46; border-radius: 3px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { height: 6px; background: transparent; }
            QScrollBar::handle:horizontal { background: rgba(255,255,255,20); border-radius: 3px; }
        """)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")

        self._hbox = QHBoxLayout(self._container)
        self._hbox.setContentsMargins(0, 0, 0, 8)
        self._hbox.setSpacing(16)

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._refresh_repo_label()

    def _select_repository(self):
        """Pick a project folder, persist it, and tell the orchestrator."""
        from PyQt6.QtWidgets import QFileDialog

        start = get_project_dir() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Select project repository", start)
        if not path:
            return
        set_project_dir(path)

        parent_notch = self.window()
        on_selected = getattr(parent_notch, "on_project_selected", None)
        if on_selected:
            try:
                on_selected(path)
            except Exception as e:
                log.error("Failed to update orchestrator project dir: %s", e)

        self._refresh_repo_label()

    def _refresh_repo_label(self):
        repo = get_project_dir()
        if repo:
            name = os.path.basename(repo.rstrip("\\/")) or repo
            self._repo_lbl.setText(f"📁 {name}")
            self._repo_lbl.setToolTip(repo)
        else:
            self._repo_lbl.setText("")
            self._repo_lbl.setToolTip("")

    def _settings(self):
        callback = getattr(self.window(), "show_settings", None)
        if callback:
            callback()

    def _highlight(self):
        parent_notch = self.window()
        if hasattr(parent_notch, 'on_highlight_requested'):
            parent_notch.on_highlight_requested()

    def _copy_all(self):
        try:
            from arrow.storage.capture_store import CaptureStore
            store = CaptureStore()
            parts = []
            for rec in store.get_all():
                if rec.change_request:
                    parts.append(format_change_request(rec.change_request))
                elif rec.annotation_text:
                    parts.append(rec.annotation_text)
            QApplication.clipboard().setText("\n\n".join(parts))
        except Exception as e:
            QMessageBox.warning(self, "Copy Error", str(e))

    def _clear_all(self):
        reply = QMessageBox.question(self, "Clear All", "Delete all screenshots?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            from arrow.storage.capture_store import CaptureStore
            store = CaptureStore()
            failed = []
            for rec in store.get_all():
                store.delete(rec.id)
                if os.path.exists(rec.screenshot_path):
                    try:
                        os.remove(rec.screenshot_path)
                    except Exception:
                        failed.append(rec.screenshot_path)
            self._scan_existing()
            if failed:
                QMessageBox.warning(self, "Partial Cleanup", f"Removed from library but could not delete {len(failed)} file(s):\n" + "\n".join(failed))

    def _select_capture(self, index):
        path = self._history.itemData(index)
        for card in self._thumbnails:
            card.setVisible(card._path == path)

    def _scan_existing(self):
        from arrow.storage.capture_store import CaptureStore
        selected = self._history.currentData()
        existing = {card._path: card for card in self._thumbnails}
        records = [record for record in CaptureStore().get_all() if os.path.isfile(record.screenshot_path)]
        paths = {record.screenshot_path for record in records}
        for path, card in existing.items():
            if path not in paths:
                self._remove_thumbnail(card)
        self._history.blockSignals(True)
        self._history.clear()
        for record in records:
            if record.screenshot_path not in existing:
                self._add_thumbnail(record.screenshot_path, record.annotation_text, record.timestamp,
                                    record.window_title, record.change_request)
            self._history.addItem((record.annotation_text or 'Visual capture')[:35], record.screenshot_path)
        index = 0 if any(record.screenshot_path not in existing for record in records) else self._history.findData(selected)
        self._history.setCurrentIndex(max(0, index))
        self._history.blockSignals(False)
        self._select_capture(self._history.currentIndex())
        self._all_btn.setText(f'{len(records)} captures')

    def _add_thumbnail(self, path, text="", timestamp="", window_title="", change_request=None):
        thumb = ScreenshotThumbnail(path, text, timestamp, window_title, change_request)
        thumb.deleted.connect(self._remove_thumbnail)
        thumb.connection_requested.connect(lambda: self.window().show_settings('Agents'))
        self._thumbnails.append(thumb)

        count = self._hbox.count()
        if count > 0:
            self._hbox.insertWidget(count - 1, thumb)
        else:
            self._hbox.addWidget(thumb)
            self._hbox.addStretch()
        self._all_btn.setText(f"All {len(self._thumbnails)}")

    def _remove_thumbnail(self, thumb):
        index = self._history.findData(thumb._path)
        if index >= 0:
            self._history.removeItem(index)
        self._hbox.removeWidget(thumb)
        if thumb in self._thumbnails:
            self._thumbnails.remove(thumb)
        thumb.deleteLater()
        self._all_btn.setText(f"All {len(self._thumbnails)}")


# ---------------------------------------------------------------------------
# DynamicNotch  – main overlay widget
# ---------------------------------------------------------------------------
class DynamicNotch(QWidget):
    def __init__(self, server: AgentServer = None):
        super().__init__()
        self._server = server
        self._state = "idle"
        self._border_radius = 6.0
        self._docked = get_ui_preferences()['keep_notch_open']
        self._settings_open = False
        self._anim_progress = 0.0
        self._expanded_size = (SCREENSHOTS_W, SCREENSHOTS_H)
        self._idle_rect = QRect()
        self._expanded_rect = QRect()
        self._is_recording = False

        self._setup_window()
        self._build_ui()
        self.set_anim_progress(0)
        self._position_idle()
        self._anim_group = None
        self._auto_collapse_timer = None
        if self._docked:
            QTimer.singleShot(0, self.expand)

    # -- property for border-radius interpolation --
    def get_anim_progress(self):
        return self._anim_progress

    def set_anim_progress(self, v):
        self._anim_progress = v
        br = round(6 + 14 * v)
        self._border_radius = br
        collapsed = (12, 4, 12, 16)
        expanded = (24, 20, 24, 20)
        self._main_layout.setContentsMargins(*(round(a + (b - a) * v) for a, b in zip(collapsed, expanded)))
        self._shadow.setBlurRadius(8 + 27 * v)
        self._shadow.setOffset(0, 2 + 14 * v)
        color = f'rgba({round(24 - 15*v)}, {round(24 - 15*v)}, {round(27 - 16*v)}, {round(205 + 35*v)})'
        self._container.setStyleSheet(f"""
            #notchContainer {{
                background: {color};
                border: 1px solid {NOTCH_BORDER};
                border-radius: {br}px;
            }}
        """)

    anim_progress = pyqtProperty(float, get_anim_progress, set_anim_progress)

    def paintEvent(self, event):
        # Keep the invisible padding usable on Windows layered windows, where
        # alpha-zero pixels otherwise pass hover/clicks to the application below.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        painter.end()

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

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(self._shadow)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._main_layout.setContentsMargins(24, 20, 24, 20)
        self._main_layout.setSpacing(0)

        self._container = QFrame()
        self._container.setObjectName("notchContainer")
        self._container.setStyleSheet(f"""
            #notchContainer {{
                background: {NOTCH_BG};
                border: 1px solid {NOTCH_BORDER};
                border-radius: 16px;
            }}
        """)
        cl = QVBoxLayout(self._container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ---- Idle handle: unadorned pill, with a compact recording waveform ----
        self._idle_w = QWidget()
        idle_l = QHBoxLayout(self._idle_w)
        idle_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_l.setContentsMargins(0, 0, 0, 0)

        self._idle_stack = QStackedWidget()
        self._idle_stack.setFixedSize(44, 8)

        self._waveform = MiniWaveformWidget()
        self._waveform.setFixedSize(44, 8)
        self._idle_stack.addWidget(QWidget())       # index 0 = plain pill
        self._idle_stack.addWidget(self._waveform)    # index 1 = waveform
        self._idle_stack.setCurrentIndex(0)

        idle_l.addWidget(self._idle_stack)
        cl.addWidget(self._idle_w)

        # ---- Expanded widget with tabs ----
        self._expanded_w = QWidget()
        expanded_layout = QVBoxLayout(self._expanded_w)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(0)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #F8FAFC; padding: 8px 24px;")
        self._status_label.hide()
        expanded_layout.addWidget(self._status_label)

        self._content_stack = QStackedWidget()
        self._screens_view = ScreenshotsView()
        self._settings_view = SettingsPanel(self._save_capture_preferences)
        self._settings_view.close_requested.connect(self.show_captures)
        self._settings_view.repository_changed.connect(self._repository_changed)
        self._settings_view.preferences_changed.connect(self._apply_ui_preferences)
        self._content_stack.addWidget(self._screens_view)
        self._content_stack.addWidget(self._settings_view)
        expanded_layout.addWidget(self._content_stack, 1)

        self._expanded_w.hide()
        cl.addWidget(self._expanded_w, 1)

        self._main_layout.addWidget(self._container)

    # ------------------------------------------------------------------
    # Positioning helpers
    # ------------------------------------------------------------------
    def _position_idle(self):
        screen = QApplication.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            x = ag.center().x() - IDLE_W // 2
            y = ag.y() + TOP_OFFSET
            self._idle_rect = QRect(x, y, IDLE_W, IDLE_H)
            self.setGeometry(self._idle_rect)

    def show_capture_review(self, card, send_to=None, copy_mode=None):
        from arrow.ui.capture_review import CaptureReview
        try:
            review = CaptureReview(card._change_request.get('capture_id'))
        except ValueError as error:
            card._action_status.setText(str(error))
            return
        previous = getattr(self, '_review_view', None)
        if previous is not None:
            self._content_stack.removeWidget(previous)
            previous.deleteLater()
        self._review_view = review
        self._content_stack.addWidget(review)
        review.close_requested.connect(self.show_captures)
        def saved(record):
            card._apply_review(record)
            if send_to:
                self.show_captures()
                card._send_to_provider(send_to, reviewed=True)
            elif copy_mode:
                self.show_captures()
                card._copy_request(copy_mode, reviewed=True)
        review.saved.connect(saved)
        def retake():
            self.show_captures()
            self._screens_view._highlight()
        review.retake_requested.connect(retake)
        if send_to:
            review.save_button.setText(f'Save and open {send_to}')
        elif copy_mode:
            review.save_button.setText('Save and copy ' + {'both': 'image + prompt', 'image': 'image', 'text': 'prompt'}[copy_mode])
        self._settings_open = True  # Keep the notch open while the user reviews.
        if self._auto_collapse_timer is not None:
            self._auto_collapse_timer.stop()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.expand()
        self._content_stack.setCurrentWidget(review)
        self.raise_()
        self.activateWindow()

    def _calc_expanded_rect(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return QRect(0, 0, self._expanded_size[0], self._expanded_size[1])
        ag = screen.availableGeometry()
        ew, eh = self._expanded_size
        ew = min(ew, max(1, ag.width() - 16))
        eh = min(eh, max(1, ag.height() - TOP_OFFSET - 8))
        x = ag.center().x() - ew // 2
        y = ag.y() + TOP_OFFSET
        return QRect(x, y, ew, eh)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def expand(self, tab="screens"):
        self._state = "expanded"

        # Show expanded content immediately so it's visible during animation
        self._idle_w.hide()
        self._expanded_w.show()

        self._expanded_size = (SCREENSHOTS_W, SCREENSHOTS_H)
        self._animate_to(self._calc_expanded_rect(), 1.0)

    def show_settings(self, tab='Capture'):
        if self._auto_collapse_timer is not None:
            self._auto_collapse_timer.stop()
        self._settings_open = True
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self._content_stack.setCurrentWidget(self._settings_view)
        self._settings_view.repository_input.setText(get_project_dir() or '')
        self._settings_view.select_tab(tab)
        self.expand()
        self.raise_()
        self.activateWindow()
        self._settings_view.setFocus()

    def show_captures(self):
        self._settings_open = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._content_stack.setCurrentWidget(self._screens_view)
        self.expand()

    def _save_capture_preferences(self, shortcut, language):
        callback = getattr(self, 'on_capture_preferences_changed', None)
        if not callable(callback):
            raise ValueError('Capture controls are not ready. Try again after startup.')
        callback(shortcut, language)

    def _repository_changed(self, path):
        callback = getattr(self, 'on_project_selected', None)
        if callback:
            callback(path)
        self._screens_view._refresh_repo_label()

    def _apply_ui_preferences(self):
        self.set_docked(get_ui_preferences()['keep_notch_open'])

    def collapse(self):
        if self._state == "idle":
            return
        self._state = "idle"

        # Hide expanded content immediately for clean pill contraction
        self._expanded_w.hide()
        self._idle_w.show()

        # Recalculate idle rect in case screen geometry changed
        self._position_idle_rect()
        self._animate_to(self._idle_rect, 0.0)

    def _position_idle_rect(self):
        """Recalculate the idle rect without moving the window."""
        screen = QApplication.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            x = ag.center().x() - IDLE_W // 2
            y = ag.y() + TOP_OFFSET
            self._idle_rect = QRect(x, y, IDLE_W, IDLE_H)

    def _animate_to(self, target_rect, target_progress):
        # Stop and clean up any running animation group
        if self._anim_group is not None:
            if self._anim_group.state() == QParallelAnimationGroup.State.Running:
                self._anim_group.stop()
            # Prevent signal accumulation — delete old group
            self._anim_group.deleteLater()
            self._anim_group = None

        geo_anim = QPropertyAnimation(self, b"geometry")
        geo_anim.setEndValue(target_rect)
        geo_anim.setDuration(ANIM_MS)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        br_anim = QPropertyAnimation(self, b"anim_progress")
        br_anim.setEndValue(target_progress)
        br_anim.setDuration(ANIM_MS)
        br_anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(geo_anim)
        self._anim_group.addAnimation(br_anim)
        self._anim_group.start()

    # ------------------------------------------------------------------
    # Mouse events  (hover to expand)
    # ------------------------------------------------------------------
    def enterEvent(self, event):
        # Cancel auto-collapse if we re-enter
        if self._auto_collapse_timer is not None:
            self._auto_collapse_timer.stop()
            self._auto_collapse_timer = None
        self.expand()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._state == 'idle':
            self.expand()
            event.accept()
            return
        super().mousePressEvent(event)

    def leaveEvent(self, event):
        if not self._docked and not self._settings_open:
            self.collapse()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Dock / Undock
    # ------------------------------------------------------------------
    def set_docked(self, docked):
        self._docked = docked
        if docked:
            self.expand()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_recording(self, recording: bool):
        """Show a compact waveform while recording, preserving the slim pill."""
        self._is_recording = recording
        if recording:
            self._idle_stack.setCurrentIndex(1)  # waveform
            self._waveform.start()
        else:
            self._idle_stack.setCurrentIndex(0)  # plain pill
            self._waveform.stop()

    def refresh_screenshots(self):
        """Reload screenshots from CaptureStore into the ScreenshotsView."""
        self._screens_view._scan_existing()

    def auto_expand_briefly(self, duration_ms: int = 4000):
        """Expand the notch to Screens tab, then auto-collapse after duration_ms."""
        if not get_ui_preferences()['auto_expand_capture'] or self._settings_open:
            return
        self._content_stack.setCurrentWidget(self._screens_view)
        self.expand(tab="screens")
        # Set up auto-collapse timer
        if self._auto_collapse_timer is not None:
            self._auto_collapse_timer.stop()
        self._auto_collapse_timer = QTimer(self)
        self._auto_collapse_timer.setSingleShot(True)
        self._auto_collapse_timer.timeout.connect(self._auto_collapse_tick)
        self._auto_collapse_timer.start(duration_ms)

    def _auto_collapse_tick(self):
        """Collapse unless user is hovering or docked."""
        if not self._docked and not self._settings_open and not self.underMouse():
            self.collapse()
        self._auto_collapse_timer = None

    def set_status(self, text):
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))
        if text and self._state == "idle" and get_ui_preferences()['auto_expand_capture']:
            self.expand()

    def update_status(self, text):
        self.set_status(text)
