"""Settings and CLI connection controls embedded in the notch."""

import os
import threading

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arrow.storage import settings


class SettingsPanel(QWidget):
    close_requested = pyqtSignal()
    repository_changed = pyqtSignal(str)
    preferences_changed = pyqtSignal()
    agents_checked = pyqtSignal(object)

    def __init__(self, save_capture, parent=None):
        super().__init__(parent)
        self._save_capture_callback = save_capture
        self._checking = False
        self._refresh_pending = False
        self._agent_statuses = {}
        self._login_processes = {}
        self.setObjectName('settingsPanel')
        self.setStyleSheet('''
            #settingsPanel { background: transparent; }
            #settingsPanel QLabel { color: #d4d4d8; background: transparent; border: none; font-size: 12px; }
            #settingsPanel QFrame#settingCard { background: #18181b; border: 1px solid #27272a; border-radius: 12px; }
            #settingsPanel QPushButton { background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46;
                border-radius: 8px; padding: 8px 12px; font-size: 12px; }
            #settingsPanel QPushButton:hover { background: #3f3f46; }
            #settingsPanel QPushButton:checked { background: #352953; color: #ddd6fe; border-color: #a78bfa; }
            #settingsPanel QPushButton:disabled { color: #71717a; border-color: #27272a; }
            #settingsPanel QPushButton[primary="true"] { background: #a78bfa; color: #09090b; font-weight: 600; }
            #settingsPanel QLineEdit, #settingsPanel QComboBox { background: #09090b; color: #fafafa;
                border: 1px solid #3f3f46; border-radius: 8px; padding: 8px; min-height: 18px; }
            #settingsPanel QLineEdit:focus, #settingsPanel QComboBox:focus { border-color: #a78bfa; }
            #settingsPanel QComboBox QAbstractItemView { background: #18181b; color: #fafafa; selection-background-color: #352953; }
            #settingsPanel QCheckBox { color: #e4e4e7; spacing: 8px; padding: 4px; }
            #settingsPanel QScrollArea { background: transparent; border: none; }
            #settingsPanel QScrollBar:vertical { background: transparent; width: 6px; }
            #settingsPanel QScrollBar::handle:vertical { background: #3f3f46; border-radius: 3px; min-height: 24px; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        back = QPushButton('‹ Captures')
        back.clicked.connect(self.close_requested)
        header.addWidget(back)
        title = QLabel('Settings')
        title.setStyleSheet('font-size: 18px; font-weight: 600; color: #fafafa;')
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        tabs = QHBoxLayout()
        self.tab_buttons = {}
        for name in ('Capture', 'Agents', 'General'):
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, tab=name: self.select_tab(tab))
            tabs.addWidget(button)
            self.tab_buttons[name] = button
        layout.addLayout(tabs)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        for builder in (self._build_capture, self._build_agents, self._build_general):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            body = QWidget()
            body.setObjectName('settingsPage')
            body.setStyleSheet('QWidget#settingsPage { background: transparent; }')
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 8, 0)
            body_layout.setSpacing(12)
            builder(body_layout)
            body_layout.addStretch()
            scroll.setWidget(body)
            self.pages.addWidget(scroll)
        self.agents_checked.connect(self._apply_agent_statuses)
        self._login_timer = QTimer(self)
        self._login_timer.setInterval(1000)
        self._login_timer.timeout.connect(self._poll_logins)
        self.select_tab('Capture')

    @staticmethod
    def _label(text):
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def _card(self, layout, title, description):
        frame = QFrame()
        frame.setObjectName('settingCard')
        content = QVBoxLayout(frame)
        content.setContentsMargins(16, 14, 16, 14)
        heading = self._label(title)
        heading.setStyleSheet('font-size: 14px; color: #fafafa; font-weight: 600;')
        content.addWidget(heading)
        content.addWidget(self._label(description))
        layout.addWidget(frame)
        return content

    def _build_capture(self, layout):
        card = self._card(layout, 'Draw and speak',
                          'Hold your shortcut while speaking and drawing. Release either shortcut key to finish. '
                          'Draw the source first, then release the mouse and draw the destination.')
        card.addWidget(self._label('Capture shortcut'))
        self.shortcut_input = QLineEdit(settings.get_capture_shortcut())
        self.shortcut_input.setPlaceholderText('ctrl+space or ctrl+shift')
        card.addWidget(self.shortcut_input)
        card.addWidget(self._label('Speech language'))
        self.language_combo = QComboBox()
        for title, value in [('English (India)', 'en-IN'), ('Hindi (India)', 'hi-IN'), ('English (US)', 'en-US')]:
            self.language_combo.addItem(title, value)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(settings.get_speech_language())))
        card.addWidget(self.language_combo)
        card.addWidget(self._label('Ctrl+Shift also works. Fn depends on keyboard firmware. Esc cancels; Enter finishes.'))
        buttons = QHBoxLayout()
        defaults = QPushButton('Restore defaults')
        defaults.clicked.connect(self._restore_capture_defaults)
        buttons.addWidget(defaults)
        save = QPushButton('Save capture settings')
        save.setProperty('primary', True)
        save.clicked.connect(self._save_capture)
        buttons.addWidget(save)
        card.addLayout(buttons)
        self.capture_status = self._label('')
        card.addWidget(self.capture_status)

    def _restore_capture_defaults(self):
        self.shortcut_input.setText(settings.DEFAULT_CAPTURE_SHORTCUT)
        self.language_combo.setCurrentIndex(self.language_combo.findData(settings.DEFAULT_SPEECH_LANGUAGE))
        self.capture_status.setText('Defaults selected. Save to apply.')

    def _save_capture(self):
        try:
            self._save_capture_callback(self.shortcut_input.text().strip(), self.language_combo.currentData())
        except Exception as error:
            self.capture_status.setText(str(error))
            return
        self.capture_status.setText('Capture settings saved.')

    def _build_agents(self, layout):
        layout.addWidget(self._label('Connect your installed CLI using its own sign-in. '
                                    'Arrow does not store passwords or API keys.'))
        self.agent_rows = {}
        for name in ('Codex', 'Claude Code'):
            card = self._card(layout, name, 'Sign in once, then send captures with their annotated image.')
            # Keep status separate so refreshing does not reconstruct controls.
            status = self._label('Open Agents or refresh to check installation and sign-in.')
            card.addWidget(status)
            buttons = QHBoxLayout()
            guide = QPushButton('Install guide')
            guide.clicked.connect(lambda checked=False, provider=name: self._open_install_guide(provider))
            connect = QPushButton('Connect')
            connect.setEnabled(False)
            connect.clicked.connect(lambda checked=False, provider=name: self._connect_agent(provider))
            buttons.addWidget(guide)
            buttons.addWidget(connect)
            card.addLayout(buttons)
            self.agent_rows[name] = (status, connect)
        self.refresh_agents_button = QPushButton('Refresh connections')
        self.refresh_agents_button.clicked.connect(self.refresh_agents)
        layout.addWidget(self.refresh_agents_button)
        card = self._card(layout, 'Project repository', 'Direct sends run in this folder using your CLI account.')
        self.repository_input = QLineEdit(settings.get_project_dir() or '')
        self.repository_input.setPlaceholderText('Choose your project folder')
        card.addWidget(self.repository_input)
        buttons = QHBoxLayout()
        browse = QPushButton('Browse')
        browse.clicked.connect(self._browse_repository)
        buttons.addWidget(browse)
        use = QPushButton('Use repository')
        use.clicked.connect(self._save_repository)
        buttons.addWidget(use)
        card.addLayout(buttons)
        self.repository_status = self._label('')
        card.addWidget(self.repository_status)

    def _open_install_guide(self, name):
        from arrow.providers.setup import get_provider_install_url
        QDesktopServices.openUrl(QUrl(get_provider_install_url(name)))

    def refresh_agents(self):
        if self._checking:
            self._refresh_pending = True
            return
        self._checking = True
        self.refresh_agents_button.setEnabled(False)
        for name, (label, button) in self.agent_rows.items():
            if name not in self._login_processes:
                label.setText('Checking installation and sign-in…')
                button.setEnabled(False)

        def check():
            from arrow.providers.setup import get_provider_setup_status
            statuses = [get_provider_setup_status(name) for name in self.agent_rows]
            try:
                self.agents_checked.emit(statuses)
            except RuntimeError:
                pass  # The application may close while a bounded probe runs.

        threading.Thread(target=check, daemon=True).start()

    def _apply_agent_statuses(self, statuses):
        self._checking = False
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_agents()
            return
        self.refresh_agents_button.setEnabled(True)
        for status in statuses:
            self._agent_statuses[status.name] = status
            label, button = self.agent_rows[status.name]
            if status.name in self._login_processes:
                continue
            state = ('Connected' if status.authenticated is True else 'Sign in required'
                     if status.installed and status.authenticated is False else 'Sign-in status unknown'
                     if status.installed else 'CLI not installed')
            label.setText(state if status.authenticated is True else f'{state} · {status.message}')
            button.setText('Reconnect' if status.authenticated else 'Connect')
            button.setEnabled(status.installed)

    def _connect_agent(self, name):
        from arrow.providers.setup import start_provider_login
        label, button = self.agent_rows[name]
        try:
            self._login_processes[name] = start_provider_login(name)
        except Exception as error:
            label.setText(str(error))
            return
        label.setText('Finish sign-in in your browser or CLI window. Connection will be checked when it closes.')
        button.setEnabled(False)
        self._login_timer.start()

    def _poll_logins(self):
        completed = [name for name, process in self._login_processes.items() if process.poll() is not None]
        for name in completed:
            del self._login_processes[name]
        if not self._login_processes:
            self._login_timer.stop()
        if completed:
            self.refresh_agents()

    def _browse_repository(self):
        path = QFileDialog.getExistingDirectory(self, 'Select project repository',
                                                settings.get_project_dir() or os.path.expanduser('~'))
        if path:
            self.repository_input.setText(path)
            self._save_repository()

    def _save_repository(self):
        path = os.path.abspath(os.path.expanduser(self.repository_input.text().strip()))
        if not self.repository_input.text().strip() or not os.path.isdir(path):
            self.repository_status.setText('Choose an existing project folder.')
            return
        try:
            settings.set_project_dir(path)
            self.repository_changed.emit(path)
        except OSError as error:
            self.repository_status.setText(str(error))
            return
        self.repository_input.setText(path)
        self.repository_status.setText('Repository selected. Open a capture card to send it to your connected agent.')

    def _build_general(self, layout):
        prefs = settings.get_ui_preferences()
        card = self._card(layout, 'Clipboard', 'ChatGPT may paste only text from a mixed clipboard. '
                          'Two-step copying attaches the image first, then copies the prompt when you are ready.')
        self.clipboard_combo = QComboBox()
        self.clipboard_combo.addItem('Two steps · image first, then prompt', 'two_step')
        self.clipboard_combo.addItem('Combined · for apps that accept image + text', 'combined')
        self.clipboard_combo.setCurrentIndex(self.clipboard_combo.findData(prefs['clipboard_mode']))
        card.addWidget(self.clipboard_combo)
        card = self._card(layout, 'Notch behavior', 'Keep your capture workflow in the same window.')
        self.auto_expand = QCheckBox('Automatically expand for capture updates')
        self.auto_expand.setChecked(prefs['auto_expand_capture'])
        self.keep_open = QCheckBox('Keep the notch expanded')
        self.keep_open.setChecked(prefs['keep_notch_open'])
        card.addWidget(self.auto_expand)
        card.addWidget(self.keep_open)
        save = QPushButton('Save preferences')
        save.setProperty('primary', True)
        save.clicked.connect(self._save_general)
        layout.addWidget(save)
        self.general_status = self._label('')
        layout.addWidget(self.general_status)

    def _save_general(self):
        try:
            settings.set_ui_preferences(clipboard_mode=self.clipboard_combo.currentData(),
                                        auto_expand_capture=self.auto_expand.isChecked(),
                                        keep_notch_open=self.keep_open.isChecked())
        except (OSError, ValueError) as error:
            self.general_status.setText(str(error))
            return
        self.preferences_changed.emit()
        self.general_status.setText('Preferences saved.')

    def select_tab(self, name):
        names = list(self.tab_buttons)
        self.pages.setCurrentIndex(names.index(name))
        for title, button in self.tab_buttons.items():
            button.setChecked(title == name)
        if name == 'Agents':
            self.refresh_agents()
