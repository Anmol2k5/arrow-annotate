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
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arrow.intent.compiler import recompile_change_request
from arrow.providers.runner import build_run_request, create_provider, run_provider_sync
from arrow.server.server import AgentServer
from arrow.storage.settings import get_project_dir, set_project_dir

log = logging.getLogger("arrow.ui.notch")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NOTCH_BG = "rgba(9, 9, 11, 240)"
NOTCH_BORDER = "rgba(255, 255, 255, 12)"

IDLE_W, IDLE_H = 80, 32
HOME_W, HOME_H = 340, 380
AGENTS_W, AGENTS_H = 400, 400
SCREENSHOTS_W, SCREENSHOTS_H = 760, 440

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
    """Best human-readable label for a source/destination anchor."""
    if not anchor:
        return ""
    label = anchor.get("label")
    if label:
        return label
    element = anchor.get("element") or {}
    return (
        element.get("name")
        or element.get("text")
        or anchor.get("selector")
        or (anchor.get("geometry") and "selected region")
        or ""
    )


def format_change_request(cr: dict) -> str:
    """Render a compiled change request as a paste-ready prompt (Codex/Claude/IDE)."""
    if not cr:
        return ""
    intent = INTENT_LABELS.get(cr.get("normalized_intent", ""), cr.get("normalized_intent", "unknown"))

    lines = ["## Arrow change request"]
    lines.append(f"**Intent:** {intent}")
    if cr.get("summary"):
        lines.append(f"**Summary:** {cr['summary']}")
    if cr.get("raw_user_request"):
        lines.append(f"**Instruction:** {cr['raw_user_request']}")

    src_label = _anchor_label(cr.get("source") or {})
    dst_label = _anchor_label(cr.get("destination") or {})
    if src_label:
        lines.append(f"**Source:** {src_label}")
    if dst_label:
        lines.append(f"**Destination:** {dst_label}")
    if cr.get("move_relationship"):
        lines.append(f"**Move relationship:** {cr['move_relationship']}")
    if cr.get("confidence") is not None:
        lines.append(f"**Confidence:** {round(cr['confidence'], 2)}")

    files = cr.get("likely_files") or []
    if files:
        f = files[0]
        loc = f["source_file"]
        if f.get("source_line") is not None:
            loc += f":{f['source_line']}"
        lines.append(f"**Likely file:** {loc}")

    for op in (cr.get("requested_changes") or []):
        lines.append(f"- {op.get('description', '')}")

    for title, key in (("Acceptance criteria", "acceptance_criteria"), ("Constraints", "constraints")):
        items = cr.get(key) or []
        if items:
            lines.append(f"**{title}:**")
            lines.extend(f"- {c}" for c in items)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ScreenshotThumbnail  – clickable thumbnail with delete, copy, send-to-AI
# ---------------------------------------------------------------------------
class ScreenshotThumbnail(QFrame):
    deleted = pyqtSignal(object)
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
        # Queued: emitted from a worker thread, delivered on the main thread.
        self.provider_finished.connect(self._on_provider_finished)
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedSize(320, 400)
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
                scaled = pix.scaled(320, 160, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                x = (scaled.width() - 320) // 2
                y = (scaled.height() - 160) // 2
                cropped = scaled.copy(x, y, 320, 160)

                rounded = QPixmap(320, 160)
                rounded.fill(Qt.GlobalColor.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(QRectF(0, 0, 320, 160), 12, 12)
                path.addRect(QRectF(0, 12, 320, 148))
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, cropped)
                painter.end()

                self._img_label.setPixmap(rounded)
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

        # Action row: edit the instruction, copy the request, or send it
        # straight to a coding agent.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        edit_btn = self._action_button("✏️ Edit", self._edit_instruction)
        btn_row.addWidget(edit_btn)

        copy_btn = self._action_button("📋 Copy", self._copy_request)
        btn_row.addWidget(copy_btn)

        self._provider_buttons = {}
        for name in ("Codex", "Claude Code"):
            btn = self._action_button(f"▶ {name}", lambda _=False, n=name: self._send_to_provider(n))
            btn.setEnabled(self._provider_available(name))
            if not btn.isEnabled():
                btn.setToolTip(f"{name} CLI not found on PATH")
            self._provider_buttons[name] = btn
            btn_row.addWidget(btn)

        btn_row.addStretch()
        v.addLayout(btn_row)

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
        self._chip_lbl.setText(INTENT_LABELS.get(cr.get("normalized_intent", ""), "Unknown"))

        conf = cr.get("confidence")
        self._conf_lbl.setText(f"{round(conf * 100)}%" if conf is not None else "")
        self._conf_lbl.setVisible(conf is not None)

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
            arrow_lbl = QLabel(f"{src or '…'}  →  {dst or '…'}")
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
        """Let the user edit the instruction, recompile, and persist the result."""
        current = self._change_request.get("raw_user_request", "")
        text, ok = QInputDialog.getText(self, "Edit instruction", "Instruction:", text=current)
        if not ok:
            return

        new_instruction = text.strip()
        new_cr = recompile_change_request(self._change_request, new_instruction)
        if new_cr is None:
            return

        self._change_request = new_cr.to_dict()
        if new_instruction:
            self._text = new_instruction
            self._text_lbl.setText(new_instruction)

        capture_id = self._change_request.get("capture_id")
        if capture_id:
            try:
                from arrow.storage.capture_store import CaptureStore
                CaptureStore().update_change_request(
                    capture_id, self._change_request,
                    annotation_text=new_instruction or None,
                )
            except Exception as e:
                log.error("Failed to persist edited change request: %s", e)

        self._fill_intent_content()

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

    def _copy_request(self):
        """Copy a paste-ready change request (with screenshot path) to the clipboard."""
        text = format_change_request(self._change_request)
        if not text:
            return
        if self._path:
            text += f"\n**Screenshot:** {self._path}"
        QApplication.clipboard().setText(text)

    def _send_to_provider(self, name: str):
        """Send the compiled change request straight to Codex / Claude Code."""
        cr = self._change_request
        if not cr:
            return

        request = build_run_request(
            cr.get("capture_id") or "",
            cr,
            format_change_request(cr),
            fallback_repo=get_project_dir(),
        )
        if request is None:
            QMessageBox.warning(
                self, f"Send to {name}",
                "No repository is attached to this capture, so there is nowhere safe to work. "
                "Select a repository first.",
            )
            return

        try:
            provider = create_provider(name)
        except ValueError as e:
            QMessageBox.warning(self, "Send", str(e))
            return
        if not provider.detect():
            QMessageBox.warning(self, name, f"{name} CLI was not found on PATH.")
            return

        self._set_sending(True, name)
        threading.Thread(
            target=self._run_provider_thread, args=(provider, request, name), daemon=True
        ).start()

    def _run_provider_thread(self, provider, request, name: str):
        final = run_provider_sync(provider, request)
        # Emitting a queued signal is thread-safe and delivers on the main thread.
        self.provider_finished.emit(final, request, name)

    def _on_provider_finished(self, final, request, name: str):
        self._set_sending(False, name)
        box = QMessageBox(self)
        box.setWindowTitle(f"{name} run finished")
        box.setIcon(QMessageBox.Icon.Information if final.type == "done" else QMessageBox.Icon.Warning)
        box.setText(f"{final.message or final.type}\n\nCapture: {request.capture_id}")
        box.exec()

    def _set_sending(self, active: bool, name: str):
        for n, btn in getattr(self, "_provider_buttons", {}).items():
            btn.setEnabled(not active)
            btn.setText(f"⏳ {n}" if active else f"▶ {n}")
        if not active and self._provider_buttons:
            for n, btn in self._provider_buttons.items():
                if not self._provider_available(n):
                    btn.setEnabled(False)

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

        for icon, tooltip in [("🎙️", "Voice capture"), ("⌨️", "Keyboard capture"), ("🖱️", "Pointer capture")]:
            btn = QPushButton(icon)
            btn.setFixedSize(28, 28)
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

        doc_btn = QPushButton("📄")
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
        row2.addWidget(add_btn)

        row2.addStretch()

        copy_btn = QPushButton("📄 Copy all")
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
        row2.addWidget(copy_btn)

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

    def _scan_existing(self):
        for thumb in self._thumbnails:
            self._hbox.removeWidget(thumb)
            thumb.deleteLater()
        self._thumbnails.clear()

        while self._hbox.count():
            item = self._hbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from arrow.storage.capture_store import CaptureStore
        store = CaptureStore()
        for rec in store.get_all():
            if os.path.exists(rec.screenshot_path):
                self._add_thumbnail(
                    rec.screenshot_path,
                    rec.annotation_text,
                    rec.timestamp,
                    getattr(rec, 'window_title', ''),
                    getattr(rec, 'change_request', None),
                )

        self._hbox.addStretch()
        self._all_btn.setText(f"All {len(self._thumbnails)}")

    def _add_thumbnail(self, path, text="", timestamp="", window_title="", change_request=None):
        thumb = ScreenshotThumbnail(path, text, timestamp, window_title, change_request)
        thumb.deleted.connect(self._remove_thumbnail)
        self._thumbnails.append(thumb)

        count = self._hbox.count()
        if count > 0:
            self._hbox.insertWidget(count - 1, thumb)
        else:
            self._hbox.addWidget(thumb)
            self._hbox.addStretch()
        self._all_btn.setText(f"All {len(self._thumbnails)}")

    def _remove_thumbnail(self, thumb):
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
        self._border_radius = 16.0
        self._docked = False
        self._anim_progress = 0.0
        self._expanded_size = (SCREENSHOTS_W, SCREENSHOTS_H)
        self._idle_rect = QRect()
        self._expanded_rect = QRect()
        self._is_recording = False

        self._setup_window()
        self._build_ui()
        self._position_idle()
        self._anim_group = None
        self._auto_collapse_timer = None

    # -- property for border-radius interpolation --
    def get_anim_progress(self):
        return self._anim_progress

    def set_anim_progress(self, v):
        self._anim_progress = v
        br = int(16 + (20 - 16) * v)
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

        # ---- Idle widget (logo ↔ waveform stacked) ----
        self._idle_w = QWidget()
        idle_l = QHBoxLayout(self._idle_w)
        idle_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle_l.setContentsMargins(0, 0, 0, 0)

        self._idle_stack = QStackedWidget()
        self._idle_stack.setFixedSize(44, 22)

        self._logo = GlowingTriangleLogo()
        logo_container = QWidget()
        logo_layout = QHBoxLayout(logo_container)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.addWidget(self._logo)

        self._waveform = MiniWaveformWidget()
        self._idle_stack.addWidget(logo_container)   # index 0 = logo
        self._idle_stack.addWidget(self._waveform)    # index 1 = waveform
        self._idle_stack.setCurrentIndex(0)

        idle_l.addWidget(self._idle_stack)
        cl.addWidget(self._idle_w)

        # ---- Expanded widget with tabs ----
        self._expanded_w = QWidget()
        expanded_layout = QVBoxLayout(self._expanded_w)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(0)

        self._screens_view = ScreenshotsView()
        expanded_layout.addWidget(self._screens_view, 1)

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
    def expand(self, tab="screens"):
        self._state = "expanded"

        # Show expanded content immediately so it's visible during animation
        self._idle_w.hide()
        self._expanded_w.show()

        self._expanded_size = (SCREENSHOTS_W, SCREENSHOTS_H)
        self._animate_to(self._calc_expanded_rect(), 1.0)

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
            y = TOP_OFFSET
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

    def leaveEvent(self, event):
        if not self._docked:
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
        """Toggle idle pill between logo (default) and waveform (recording)."""
        self._is_recording = recording
        if recording:
            self._idle_stack.setCurrentIndex(1)  # waveform
            self._waveform.start()
        else:
            self._idle_stack.setCurrentIndex(0)  # logo
            self._waveform.stop()

    def refresh_screenshots(self):
        """Reload screenshots from CaptureStore into the ScreenshotsView."""
        self._screens_view._scan_existing()

    def auto_expand_briefly(self, duration_ms: int = 1500):
        """Expand the notch to Screens tab, then auto-collapse after duration_ms."""
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
        if not self._docked and not self.underMouse():
            self.collapse()
        self._auto_collapse_timer = None

    def set_status(self, text):
        pass

    def update_status(self, text):
        pass
