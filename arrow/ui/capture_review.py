"""Capture review inside the notch; the image is the saved handoff image."""
import hashlib
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from arrow.context.review import save_review
from arrow.storage.capture_store import CaptureStore


class CaptureReview(QWidget):
    close_requested = pyqtSignal()
    retake_requested = pyqtSignal()
    saved = pyqtSignal(object)

    def __init__(self, capture_id, *, store=None, parent=None):
        super().__init__(parent)
        self.capture_id = capture_id
        self.store = store or CaptureStore()
        record = self.store.get(capture_id)
        if record is None:
            raise ValueError('This capture was deleted.')
        self.setObjectName('captureReview')
        self.setStyleSheet('''
            #captureReview {background:transparent;}
            #captureReview QWidget#reviewBody {background:#09090b;}
            #captureReview QLabel,#captureReview QCheckBox {color:#e4e4e7;background:transparent;font-size:12px;}
            #captureReview QPushButton {background:#27272a;color:#fafafa;border-radius:7px;padding:8px;}
            #captureReview QPushButton:hover {background:#3f3f46;}
            #captureReview QPlainTextEdit {background:#18181b;color:#fafafa;border:1px solid #3f3f46;border-radius:7px;padding:6px;}
            #captureReview QScrollArea {background:#09090b;border:none;}
            #captureReview QScrollBar:vertical {background:#18181b;width:6px;}
            #captureReview QScrollBar:horizontal {background:#18181b;height:6px;}
            #captureReview QScrollBar::handle {background:#52525b;border-radius:3px;min-height:20px;min-width:20px;}
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        header = QHBoxLayout()
        back = QPushButton('‹ Captures')
        back.clicked.connect(self.close_requested)
        header.addWidget(back)
        header.addWidget(QLabel('Review capture'))
        retake = QPushButton('Retake')
        retake.clicked.connect(self.retake_requested)
        header.addWidget(retake)
        root.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('reviewBody')
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 8, 0)
        assets = (record.change_request or {}).get('assets', {})
        path = assets.get('agent-annotated') or assets.get('annotated') or record.screenshot_path
        self.image_path = Path(path)
        self._image_digest = hashlib.sha256(self.image_path.read_bytes()).digest() if self.image_path.is_file() else None
        self.image = QPixmap(path)
        self.image_label = QLabel()
        self.image_label.setStyleSheet('background:#09090b;')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_scroll = QScrollArea()
        image_scroll.setMinimumHeight(230)
        image_scroll.setMaximumHeight(260)
        image_scroll.setWidget(self.image_label)
        content.addWidget(image_scroll)
        if self.image.isNull():
            self.image_label.setText('Saved image is unavailable. Retake this capture.')
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(10, 200)
        self.zoom.setValue(max(10, min(100, round(430 / max(1, self.image.width()) * 100))))
        self.zoom.valueChanged.connect(self._zoom)
        self._zoom(self.zoom.value())
        content.addWidget(QLabel('Image zoom · 100% shows the saved pixels'))
        content.addWidget(self.zoom)
        content.addWidget(QLabel('Instruction'))
        self.instruction = QPlainTextEdit(record.annotation_text or '')
        self.instruction.setMinimumHeight(90)
        self.instruction.setMaximumHeight(120)
        content.addWidget(self.instruction)
        self.include_text = QCheckBox('Include window text in future exports')
        self.include_text.setChecked(record.capture_context.get('review', {}).get('window_text_included', True))
        content.addWidget(self.include_text)
        self.window_editors = {}
        for role, window in record.capture_context.get('window_context', {}).items():
            label = QLabel(f"{role.title()} · {window.get('window_title', '')} · {window.get('status', 'unavailable')}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            content.addWidget(label)
            editor = QPlainTextEdit(window.get('text', ''))
            editor.setMinimumHeight(110)
            editor.setMaximumHeight(140)
            editor.setEnabled(self.include_text.isChecked())
            self.include_text.toggled.connect(editor.setEnabled)
            content.addWidget(editor)
            self.window_editors[role] = editor
        if not self.window_editors:
            content.addWidget(QLabel('No accessible window text was recorded.'))
        note = QLabel('Corrections affect future exports. Existing sent context and saved image pixels remain unchanged; use Retake to correct the drawing.')
        note.setWordWrap(True)
        content.addWidget(note)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.save_button = QPushButton('Save review')
        self.save_button.setStyleSheet('background:#a78bfa;color:#09090b;font-weight:600;border-radius:8px;padding:10px;')
        self.save_button.clicked.connect(self.save)
        root.addWidget(self.save_button)

    def _zoom(self, percentage):
        if not self.image.isNull():
            self.image_label.setPixmap(self.image.scaled(max(1, round(self.image.width() * percentage / 100)),
                max(1, round(self.image.height() * percentage / 100)), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self.image_label.adjustSize()

    def save(self):
        try:
            if (self.image.isNull() or not self.image_path.is_file()
                    or hashlib.sha256(self.image_path.read_bytes()).digest() != self._image_digest):
                self.status.setText('The saved image is missing or changed. Retake or reopen this capture before exporting.')
                return False
            record = save_review(self.capture_id, self.instruction.toPlainText(),
                {role: editor.toPlainText() for role, editor in self.window_editors.items()},
                self.include_text.isChecked(), store=self.store)
        except Exception:
            self.status.setText('Could not save this review. Check available disk space and try again; nothing has been sent.')
            return False
        self.status.setText('Review saved. Future copies and agent handoffs use these corrections.')
        self.saved.emit(record)
        return True
