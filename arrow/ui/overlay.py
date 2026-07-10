import math
import time

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class StrokePoint:
    def __init__(self, point: QPointF):
        self.point = point
        self.timestamp = time.time()


class SelectionOverlay(QWidget):
    """
    Freehand neon drawing overlay.
    Renamed to SelectionOverlay to match main.py imports without breaking, 
    but functions as a freehand Neon drawing surface.
    """
    selection_complete = pyqtSignal(object)  # emits a pseudo-SelectionResult with bounding rect

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        self._points: list[StrokePoint] = []
        self._is_drawing = False
        self._active = False
        
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._update_fade)
        self._fade_timer.start(16)  # ~60fps
        
        self._offset = QPointF(0, 0)

    def _update_geometry(self):
        screens = QApplication.screens()
        if screens:
            geom = screens[0].geometry()
            for s in screens[1:]:
                geom = geom.united(s.geometry())
            self.setGeometry(geom)
            self._offset = QPointF(geom.topLeft())

    def show_overlay(self):
        """Called when hotkey is pressed."""
        self._update_geometry()
        self._active = True
        self._points.clear()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_overlay(self):
        """Called when hotkey is released."""
        self._active = False
        self._is_drawing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        # Calculate bounding box for capture
        if self._points:
            min_x = min(p.point.x() for p in self._points)
            max_x = max(p.point.x() for p in self._points)
            min_y = min(p.point.y() for p in self._points)
            max_y = max(p.point.y() for p in self._points)
            
            # Map back to global coordinates
            global_x = min_x + self._offset.x()
            global_y = min_y + self._offset.y()
            
            pad = 100
            rect = {
                "x": max(0, int(global_x - pad)),
                "y": max(0, int(global_y - pad)),
                "width": int(max_x - min_x + pad * 2),
                "height": int(max_y - min_y + pad * 2)
            }
            
            # Mock SelectionResult object for main.py compatibility
            class MockResult:
                def __init__(self, r): self.r = r
                def to_dict(self): return self.r
                
            self.selection_complete.emit(MockResult(rect))
        else:
            # Full screen fallback
            geom = self.geometry()
            rect = {"x": geom.x(), "y": geom.y(), "width": geom.width(), "height": geom.height()}
            
            class MockResult:
                def __init__(self, r): self.r = r
                def to_dict(self): return self.r
                
            self.selection_complete.emit(MockResult(rect))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = True
            pt = event.globalPosition() - self._offset
            self._points = [StrokePoint(pt)]
            self.update()

    def mouseMoveEvent(self, event):
        if self._is_drawing:
            pt = event.globalPosition() - self._offset
            
            # Smoothing (moving average)
            if self._points:
                last_pt = self._points[-1].point
                dist = math.hypot(pt.x() - last_pt.x(), pt.y() - last_pt.y())
                if dist < 2.0:
                    return
                # Simple smoothing weight
                pt = QPointF(last_pt.x() * 0.4 + pt.x() * 0.6, 
                             last_pt.y() * 0.4 + pt.y() * 0.6)
                             
            self._points.append(StrokePoint(pt))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = False

    def _update_fade(self):
        now = time.time()
        orig_len = len(self._points)
        # 2.0 second comet tail
        self._points = [p for p in self._points if now - p.timestamp < 2.0]
        
        if len(self._points) != orig_len or self._points:
            self.update()
        elif not self._active and not self._points:
            self.hide()

    def paintEvent(self, event):
        if len(self._points) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        
        for i in range(1, len(self._points)):
            p1 = self._points[i-1]
            p2 = self._points[i]
            
            age = now - p2.timestamp
            if age > 2.0: 
                continue
                
            alpha_ratio = max(0.0, 1.0 - (age / 2.0))
            
            # Render neon glow layers
            # Outer shadow
            pen_outer = QPen(QColor(167, 139, 250, int(25 * alpha_ratio)), 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_outer)
            painter.drawLine(p1.point, p2.point)
            
            # Inner shadow
            pen_inner = QPen(QColor(167, 139, 250, int(80 * alpha_ratio)), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_inner)
            painter.drawLine(p1.point, p2.point)
            
            # Core bright stroke
            pen_core = QPen(QColor(230, 220, 255, int(255 * alpha_ratio)), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_core)
            painter.drawLine(p1.point, p2.point)
            
        painter.end()
