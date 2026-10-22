from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from arrow.ui.notch import DynamicNotch, GlowingTriangleLogo


def test_idle_pill_is_slim_with_a_visible_recording_indicator(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    notch.show()
    app.processEvents()
    assert notch._container.height() <= 14
    assert notch._container.width() >= notch._container.height() * 7
    # Windows layered windows pass mouse input through fully transparent pixels.
    assert notch.grab().toImage().pixelColor(1, 1).alpha() > 0
    assert not notch._idle_stack.currentWidget().findChildren(GlowingTriangleLogo)
    notch.set_recording(True)
    app.processEvents()
    assert notch._waveform.isVisible()
    assert notch._waveform.height() <= notch._container.height()
    assert notch._waveform._timer.isActive()
    notch.set_recording(False)
    assert not notch._waveform._timer.isActive()
    notch.close()


def test_pill_click_expands_and_collapse_restores_its_shape(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    notch.show()
    idle_size = notch.size()
    point = QPointF(notch.rect().center())
    event = QMouseEvent(QEvent.Type.MouseButtonPress, point, point,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(notch, event)
    assert notch._state == 'expanded'
    notch._anim_group.stop()
    notch.set_anim_progress(1)
    notch.setGeometry(notch._calc_expanded_rect())
    app.processEvents()
    assert notch._screens_view.isVisible()
    notch.collapse()
    notch._anim_group.stop()
    notch.set_anim_progress(0)
    notch.setGeometry(notch._idle_rect)
    app.processEvents()
    assert notch.size() == idle_size
    assert notch._container.height() <= 14
    notch.close()


def test_idle_position_uses_the_primary_screens_actual_origin(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    screen = type('Screen', (), {'availableGeometry': lambda self: QRect(-1920, -1080, 1920, 1040)})()
    monkeypatch.setattr(QApplication, 'primaryScreen', lambda: screen)
    notch._position_idle_rect()
    assert -1080 <= notch._idle_rect.y() < -1040
    assert abs(notch._idle_rect.center().x() - screen.availableGeometry().center().x()) <= 1
    notch.close()
    app.processEvents()
