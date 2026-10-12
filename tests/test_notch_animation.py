"""Fast offscreen checks for notch opening/closing transitions.

These test animation state and content reveal, not subjective Windows rendering.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from arrow.ui.notch import ANIM_MS, DynamicNotch

_APP = None


def _notch():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return DynamicNotch()


def test_expansion_uses_gentle_transition_and_does_not_restart_on_reentry():
    notch = _notch()
    try:
        assert 280 <= ANIM_MS <= 400
        notch.expand()
        group = notch._anim_group
        assert notch._state == "expanded"
        assert group is not None
        notch.expand()  # Enter events during geometry change must not reset.
        assert notch._anim_group is group
    finally:
        notch.close()


def test_content_stays_hidden_in_tiny_pill_and_fades_into_expanded_window():
    notch = _notch()
    try:
        notch.set_anim_progress(0.20)
        assert notch._expanded_w.isHidden()

        notch.set_anim_progress(0.80)
        assert not notch._expanded_w.isHidden()
        assert 0.0 < notch._expanded_opacity.opacity() < 1.0

        notch.set_anim_progress(1.0)
        assert notch._expanded_opacity.opacity() == 1.0
        notch.set_anim_progress(0.25)
        assert notch._expanded_w.isHidden()
    finally:
        notch.close()


def test_mid_animation_reversal_starts_from_current_geometry():
    notch = _notch()
    try:
        notch.expand()
        notch._anim_group.setCurrentTime(ANIM_MS // 2)
        midpoint = notch.geometry()
        notch.collapse()
        geo_animation = notch._anim_group.animationAt(0)
        assert geo_animation.startValue() == midpoint
        assert notch._state == "idle"
    finally:
        notch.close()


def test_hover_exit_uses_grace_period():
    notch = _notch()
    try:
        assert notch._hover_exit_timer.isSingleShot()
        assert 80 <= notch._hover_exit_timer.interval() <= 200
    finally:
        notch.close()
