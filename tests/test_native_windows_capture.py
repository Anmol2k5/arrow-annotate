"""Opt-in integration against a visible Windows desktop, never offscreen Qt."""

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM", "").lower() != "windows",
    reason="Requires Windows and explicit QT_QPA_PLATFORM=windows on an interactive desktop",
)


def _native_api():
    """Declare pointer-sized handles explicitly, including on 64-bit Windows."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
        ]

    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    return user, MonitorInfo


def _native_rect(user, handle):
    rect = wintypes.RECT()
    assert bool(user.GetWindowRect(handle, ctypes.byref(rect))), "GetWindowRect failed"
    return rect.left, rect.top, rect.right, rect.bottom


def _owner_at(user, point):
    return int(user.GetAncestor(user.WindowFromPoint(wintypes.POINT(*point)), 2) or 0)


def _wait_for(predicate, *, timeout=5):
    from PyQt6.QtTest import QTest

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(20)  # Keep the owning Qt GUI thread pumping native/UIA events.
    return False


def test_native_windows_frozen_context_and_physical_capture():
    # Must precede QApplication construction in this dedicated pytest process.
    os.environ["QT_ACCESSIBILITY"] = "1"
    from PIL import ImageChops
    from PyQt6.QtCore import QPoint, Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

    from arrow.capture.coordinate_mapper import CoordinateMapper
    from arrow.capture.screenshot_service import ScreenshotService
    from arrow.capture.session import Annotation
    from arrow.context.window_text import collect_window_contexts, freeze_window_targets

    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "windows", "The native test must use the Windows Qt platform"
    user, monitor_info_type = _native_api()
    target = QWidget()
    target.setWindowTitle("Arrow synthetic native target")
    target.setStyleSheet("QWidget { background-color: rgb(39, 43, 49); color: white; }")
    layout = QVBoxLayout(target)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addWidget(QLabel("Non-sensitive synthetic target context"))
    button = QPushButton("Blue button")
    button.setMinimumHeight(90)
    button.setStyleSheet(
        "QPushButton { background-color: rgb(24, 94, 210); color: white; "
        "border: 0px; border-radius: 0px; padding: 0px; }"
    )
    layout.addWidget(button)
    password = QLineEdit()
    password.setEchoMode(QLineEdit.EchoMode.Password)
    password.setText("SyntheticPasswordValue_419")
    password.setAccessibleName("SyntheticPasswordAccessibleName_419")
    layout.addWidget(password)
    target.resize(480, 280)
    screen = app.primaryScreen()
    assert screen is not None, "An interactive Windows display is required"
    target.move(screen.availableGeometry().center() - target.rect().center())
    cover = QWidget(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    cover.setWindowTitle("Arrow synthetic covering overlay")
    cover_layout = QVBoxLayout(cover)
    cover_layout.addWidget(QLabel("Overlay text must be excluded"))
    cover.setStyleSheet("QWidget { background-color: rgb(220, 180, 25); }")
    heartbeat = QTimer()
    ticks = []
    heartbeat.timeout.connect(lambda: ticks.append(worker.is_alive()))
    try:
        target.show()
        target.raise_()
        target.activateWindow()
        # Force a real child HWND so GetWindowRect supplies independent geometry.
        button_handle = int(button.winId())
        target_handle = int(target.winId())
        assert _wait_for(lambda: target.windowHandle().isExposed()), "Target was not exposed"
        QTest.qWait(200)
        origin = button.mapToGlobal(QPoint(0, 0))
        annotation = Annotation(
            id="native-source", type="rectangle", role="source",
            geometry={"x": origin.x(), "y": origin.y(), "width": button.width(), "height": button.height()},
        )
        actual_button = _native_rect(user, button_handle)
        actual_target = _native_rect(user, target_handle)
        actual_center = (
            round((actual_button[0] + actual_button[2]) / 2),
            round((actual_button[1] + actual_button[3]) / 2),
        )
        mapper = CoordinateMapper.from_qt()
        logical_center = button.mapToGlobal(button.rect().center())
        mapped_screen, mx, my = mapper.virtual_to_physical(logical_center.x(), logical_center.y())
        mapped_point = (round(mapped_screen.x + mx), round(mapped_screen.y + my))
        assert all(abs(a - b) <= 2 for a, b in zip(mapped_point, actual_center)), "Qt/Win32 point mismatch"
        frozen = freeze_window_targets([annotation])
        owner = frozen["source"]
        assert owner["handle"] == target_handle, "The exposed target HWND was not frozen"
        assert owner["window_title"] == target.windowTitle(), "The target title was not frozen"
        assert tuple(owner["bounds"]) == actual_target, "Frozen bounds differ from native GetWindowRect"
        assert all(abs(a - b) <= 2 for a, b in zip(owner["physical_point"], actual_center)), "Frozen point mismatch"
        assert _owner_at(user, owner["physical_point"]) == target_handle, "Target does not own source point"

        cover.setGeometry(target.frameGeometry())
        cover.show()
        cover.raise_()
        cover.activateWindow()
        cover_handle = int(cover.winId())
        assert _wait_for(lambda: _owner_at(user, owner["physical_point"]) == cover_handle), "Overlay did not cover point"
        contexts = []
        worker = threading.Thread(target=lambda: contexts.append(collect_window_contexts(frozen)), daemon=True)
        heartbeat.start(10)
        worker_started = time.monotonic()
        worker.start()
        assert _wait_for(lambda: not worker.is_alive(), timeout=20), "UIA worker exceeded the 20-second deadline"
        worker_elapsed = time.monotonic() - worker_started
        heartbeat.stop()
        assert worker_elapsed < 0.1 or any(ticks), "Qt event loop did not remain responsive during UIA collection"
        assert bool(contexts), "UIA worker returned no result"
        evidence = contexts[0]["source"]
        assert evidence["available"] is True, "Real Windows UIA is unavailable or the frozen target changed"
        assert evidence["handle"] == target_handle, "UIA collection changed the frozen HWND"
        assert "Blue button" in evidence["text"], "Real UIA did not expose the target button"
        assert "Non-sensitive synthetic target context" in evidence["text"], "Real UIA lost target context"
        assert "Overlay text must be excluded" not in evidence["text"], "Overlay text contaminated target context"
        assert "SyntheticPasswordValue_419" not in evidence["text"], "Password value leaked into context"
        assert "SyntheticPasswordAccessibleName_419" not in evidence["text"], "Password node name leaked into context"
        # ControlFromPoint now hits another HWND; omission is the valid safe result.
        assert "element" not in evidence, "Point-element evidence belongs to the covering overlay"

        cover.hide()
        target.raise_()
        assert _wait_for(lambda: _owner_at(user, actual_center) == target_handle), "Target was not uncovered"
        QTest.qWait(200)  # Let the compositor remove the covering window before desktop capture.
        raw, composed_screen, capture_mapper = ScreenshotService().capture_raw(None)
        rendered = ScreenshotService().render_annotations(raw, [annotation], capture_mapper)

        # Derive the expected image rectangle from native monitor/window rectangles,
        # independent of CoordinateMapper's annotation conversion. Capture normalizes
        # monitor images onto a common Qt scale, so account for that composition.
        info = monitor_info_type()
        info.cbSize = ctypes.sizeof(info)
        native_monitor = user.MonitorFromWindow(target_handle, 2)
        assert bool(user.GetMonitorInfoW(native_monitor, ctypes.byref(info))), "GetMonitorInfoW failed"
        monitor = info.rcMonitor
        qt_screen = target.screen().geometry()
        sx = qt_screen.width() * composed_screen.scale / (monitor.right - monitor.left)
        sy = qt_screen.height() * composed_screen.scale / (monitor.bottom - monitor.top)
        offset_x = round((qt_screen.x() - composed_screen.x) * composed_screen.scale)
        offset_y = round((qt_screen.y() - composed_screen.y) * composed_screen.scale)
        left, top, right, bottom = actual_button
        expected = (
            round(offset_x + (left - monitor.left) * sx),
            round(offset_y + (top - monitor.top) * sy),
            round(offset_x + (right - monitor.left) * sx),
            round(offset_y + (bottom - monitor.top) * sy),
        )
        x1, y1, x2, y2 = expected
        assert 0 <= x1 < x2 < raw.width and 0 <= y1 < y2 < raw.height, "Native button is outside captured desktop"
        # Sample the solid button away from text and all borders. An image generated
        # in memory or an incorrect desktop offset cannot satisfy this native probe.
        sample = (round(x1 + (x2 - x1) * 0.15), round(y1 + (y2 - y1) * 0.2))
        blue = raw.getpixel(sample)
        assert all(abs(a - b) <= 8 for a, b in zip(blue, (24, 94, 210))), "Raw desktop missed the native blue button"
        difference = ImageChops.difference(raw.convert("RGB"), rendered).getbbox()
        assert difference is not None, "Annotation rendering changed no pixels"
        # PIL rectangle outlines include the right/bottom pixel.
        expected_changed = (x1, y1, x2 + 1, y2 + 1)
        assert all(abs(a - b) <= 2 for a, b in zip(difference, expected_changed)), "Rendered box misses native button bounds"
        # Only boolean test outcomes/JUnit are persisted; desktop pixels stay in RAM.
    finally:
        heartbeat.stop()
        cover.close()
        target.close()
        app.processEvents()
