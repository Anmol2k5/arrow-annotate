"""Desktop controls remain usable without a Python console."""

import importlib
from pathlib import Path

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

from arrow.storage import settings


class Notch(QWidget):
    def __init__(self):
        super().__init__()
        self.expansions = 0

    def expand(self):
        self.expansions += 1


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray_module():
    return importlib.import_module("arrow.ui.tray")


@pytest.fixture
def installed_tray(qt_app, tray_module, tmp_path, monkeypatch):
    # The headless Qt platform has no system tray; the real menu and signals
    # still run, while platform availability is the only simulated capability.
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    resources = tmp_path / "resources"
    icon = resources / "arrow" / "ui" / "assets" / "arrow.png"
    icon.parent.mkdir(parents=True)
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    assert pixmap.save(str(icon))
    extension = resources / "browser_extension"
    extension.mkdir()
    data = tmp_path / "capture data"
    monkeypatch.setattr(tray_module, "resource_dir", lambda: resources)
    monkeypatch.setattr(tray_module, "data_dir", lambda: data)
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "settings"))
    calls = []
    notch = Notch()
    tray = tray_module.install_tray(
        qt_app, notch,
        on_settings=lambda: calls.append(("settings", QThread.currentThread())),
        on_capture=lambda: calls.append(("capture", QThread.currentThread())),
    )
    yield tray, notch, calls, resources, data
    if tray is not None:
        tray.hide()
        tray.contextMenu().close()
        tray.deleteLater()
    notch.close()


def action(tray, label):
    return next(item for item in tray.contextMenu().actions() if item.text() == label)


def test_no_system_tray_is_a_supported_environment(qt_app, tray_module, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    notch = Notch()
    assert tray_module.install_tray(qt_app, notch, lambda: None, lambda: None) is None
    assert not notch.isVisible()
    notch.close()


def test_tray_loads_bundled_icon_and_offers_all_desktop_controls(installed_tray):
    tray, _, _, _, _ = installed_tray
    assert tray.isVisible()
    assert not tray.icon().isNull()
    assert tray.toolTip() == "Arrow Annotate"
    assert [item.text() for item in tray.contextMenu().actions() if not item.isSeparator()] == [
        "Show Arrow", "New capture", "Capture settings", "Open data folder",
        "Browser extension folder", "About / Quick guide", "Quit",
    ]


def test_show_action_and_tray_click_reveal_and_expand_notch(installed_tray):
    tray, notch, _, _, _ = installed_tray
    action(tray, "Show Arrow").trigger()
    assert notch.isVisible()
    assert notch.expansions == 1
    notch.hide()
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert notch.isVisible()
    assert notch.expansions == 2
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    assert notch.expansions == 2


def test_capture_and_settings_actions_run_on_qt_main_thread(qt_app, installed_tray):
    tray, _, calls, _, _ = installed_tray
    action(tray, "New capture").trigger()
    action(tray, "Capture settings").trigger()
    assert calls == [("capture", qt_app.thread()), ("settings", qt_app.thread())]


def test_folder_actions_open_local_urls(installed_tray, monkeypatch):
    tray, _, _, resources, data = installed_tray
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    action(tray, "Open data folder").trigger()
    action(tray, "Browser extension folder").trigger()
    assert all(url.isLocalFile() for url in opened)
    assert [Path(url.toLocalFile()) for url in opened] == [data, resources / "browser_extension"]
    assert data.is_dir()


def test_guide_reads_current_shortcut_each_time(installed_tray, monkeypatch):
    tray, notch, _, _, _ = installed_tray
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.append((parent, title, text)))
    action(tray, "About / Quick guide").trigger()
    assert shown[-1][0] is notch
    assert "ctrl+space" in shown[-1][2].lower()
    assert "hold" in shown[-1][2].lower()
    assert "release" in shown[-1][2].lower()
    settings.set_capture_preferences("alt+a", "en-US")
    action(tray, "About / Quick guide").trigger()
    assert "alt+a" in shown[-1][2].lower()
    assert "ctrl+space" not in shown[-1][2].lower()


def test_quit_action_requests_normal_qt_shutdown(qt_app, tray_module, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    quit_requests = []
    monkeypatch.setattr(qt_app, "quit", lambda: quit_requests.append("quit"))
    notch = Notch()
    tray = tray_module.install_tray(qt_app, notch, lambda: None, lambda: None)
    try:
        action(tray, "Quit").trigger()
        assert quit_requests == ["quit"]
    finally:
        tray.hide()
        tray.contextMenu().close()
        notch.close()
        tray.deleteLater()
