"""Desktop system-tray controls for Arrow Annotate."""

from collections.abc import Callable

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from arrow.core.paths import data_dir, resource_dir
from arrow.storage import settings


def install_tray(
    app: QApplication,
    notch: QWidget,
    on_settings: Callable[[], None],
    on_capture: Callable[[], None],
) -> QSystemTrayIcon | None:
    """Install controls on the Qt thread; the caller retains the returned tray."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    tray = QSystemTrayIcon(QIcon(str(resource_dir() / "arrow" / "ui" / "assets" / "arrow.png")), app)
    tray.setToolTip("Arrow Annotate")
    # The notch owns the menu because QSystemTrayIcon does not take ownership.
    menu = QMenu(notch)

    def show_arrow():
        notch.show()
        notch.expand()
        notch.raise_()
        notch.activateWindow()

    def open_data_folder():
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def open_extension_folder():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resource_dir() / "browser_extension")))

    def show_guide():
        shortcut = settings.get_capture_shortcut()
        QMessageBox.information(
            notch,
            "Arrow Annotate — Quick guide",
            "Arrow Annotate turns screenshots and spoken instructions into context for coding agents.\n\n"
            f"Hold {shortcut}, draw around the source and an optional destination, and speak your instruction. "
            "Release either shortcut key to capture. Esc cancels.\n\n"
            "New capture also starts a session; select Done or press Enter to finish. "
            "Capture settings changes the shortcut and speech language.\n\n"
            "Open Arrow to review captures, copy images and prompts, or send them to Codex or Claude Code. "
            "Select your project folder before sending to a coding agent.\n\n"
            "Use Browser extension folder to locate the unpacked Chrome extension. "
            "Quit exits Arrow and releases its shortcuts.",
        )

    menu.addAction("Show Arrow", show_arrow)
    menu.addAction("New capture", on_capture)
    menu.addAction("Capture settings", on_settings)
    menu.addSeparator()
    menu.addAction("Open data folder", open_data_folder)
    menu.addAction("Browser extension folder", open_extension_folder)
    menu.addAction("About / Quick guide", show_guide)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)

    def activated(reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            show_arrow()

    tray.activated.connect(activated)
    tray.show()
    return tray
