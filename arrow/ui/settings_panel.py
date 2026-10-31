"""Settings and CLI connection controls embedded in the notch."""

import json
import logging
import os
import threading

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arrow.storage import settings

log = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    close_requested = pyqtSignal()
    repository_changed = pyqtSignal(str)
    preferences_changed = pyqtSignal()
    agents_checked = pyqtSignal(object)
    agent_check_failed = pyqtSignal(str)
    voice_model_finished = pyqtSignal(str)
    voice_model_progress = pyqtSignal(object)
    mcp_checked = pyqtSignal(str, object)
    update_checked = pyqtSignal(object)

    def __init__(self, save_capture, parent=None):
        super().__init__(parent)
        self._save_capture_callback = save_capture
        self._checking = False
        self._refresh_pending = False
        self._agent_statuses = {}
        self._login_processes = {}
        self._mcp_busy = set()
        self._voice_installing = False
        self._voice_cancel = threading.Event()
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
        self.agent_check_failed.connect(self._show_agent_check_failure)
        self.voice_model_finished.connect(self._voice_model_complete)
        self.voice_model_progress.connect(self._show_voice_progress)
        self.mcp_checked.connect(self._apply_mcp_status)
        self.update_checked.connect(self._show_update_result)
        QApplication.instance().aboutToQuit.connect(self._voice_cancel.set)
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
        for title, value in [('Auto · Hindi / English', 'auto'), ('English (India)', 'en-IN'), ('Hindi (India)', 'hi-IN'), ('English (US)', 'en-US')]:
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
        voice = self._card(layout, 'On-device voice',
                           'Audio is transcribed locally using Whisper. Download the multilingual model once '
                           '(about 150 MB); recording and recognition never upload audio. You can also type in the overlay.')
        from arrow.speech.offline import voice_model_ready
        self.voice_model_status = self._label('Model installed · ready for offline use' if voice_model_ready()
                                              else 'Voice model not installed. Typed captures work without it.')
        voice.addWidget(self.voice_model_status)
        self.voice_model_button = QPushButton('Repair voice model' if voice_model_ready() else 'Download voice model')
        self.voice_model_button.clicked.connect(self._install_voice_model)
        voice.addWidget(self.voice_model_button)
        self.voice_progress = QProgressBar()
        self.voice_progress.setRange(0, 100)
        self.voice_progress.hide()
        voice.addWidget(self.voice_progress)
        self.voice_cancel_button = QPushButton('Cancel download')
        self.voice_cancel_button.clicked.connect(self._cancel_voice_download)
        self.voice_cancel_button.hide()
        voice.addWidget(self.voice_cancel_button)

    def _install_voice_model(self):
        if self._voice_installing:
            return
        self._voice_installing = True
        self._voice_cancel.clear()
        self.voice_model_button.setEnabled(False)
        self.voice_cancel_button.show()
        self.voice_cancel_button.setEnabled(True)
        self.voice_progress.setRange(0, 0)
        self.voice_progress.show()
        self.voice_model_status.setText('Downloading public model files… No recordings are sent. You can keep using typed captures.')

        def install():
            try:
                from arrow.speech.offline import install_voice_model
                install_voice_model(force=True, progress=self.voice_model_progress.emit, cancel_event=self._voice_cancel)
                message = 'Model installed · ready for offline voice'
            except Exception as error:
                message = f'Model setup failed: {error}. Retry or use typed captures.'
            try:
                self.voice_model_finished.emit(message)
            except RuntimeError:
                pass
        threading.Thread(target=install, daemon=True).start()

    def _cancel_voice_download(self):
        self._voice_cancel.set()
        self.voice_cancel_button.setEnabled(False)
        self.voice_model_status.setText('Cancelling download… Existing installed model will be preserved.')

    def _show_voice_progress(self, progress):
        if self._voice_cancel.is_set():
            return
        downloaded, total = progress.get('downloaded_bytes', 0), progress.get('total_bytes')
        if total:
            self.voice_progress.setRange(0, 100)
            self.voice_progress.setValue(min(100, int(downloaded * 100 / total)))
        self.voice_model_status.setText(
            f"{progress.get('phase', 'downloading').title()} · {downloaded / 1024**2:.1f} MB"
            + (f' / {total / 1024**2:.1f} MB' if total else ''))

    def _voice_model_complete(self, message):
        self._voice_installing = False
        self.voice_cancel_button.hide()
        self.voice_progress.hide()
        from arrow.speech.offline import voice_model_ready
        self.voice_model_button.setText('Repair voice model' if voice_model_ready() else 'Download voice model')
        self.voice_model_button.setEnabled(True)
        self.voice_model_status.setText(message)

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
        self.mcp_rows = {}
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
            mcp_status = self._label('MCP: not checked. Account sign-in is separate.')
            card.addWidget(mcp_status)
            mcp_buttons = QHBoxLayout()
            configure = QPushButton('Set up Arrow MCP')
            configure.clicked.connect(lambda checked=False, provider=name: self._check_mcp(provider, configure=True))
            test = QPushButton('Test MCP')
            test.clicked.connect(lambda checked=False, provider=name: self._check_mcp(provider))
            mcp_buttons.addWidget(configure)
            mcp_buttons.addWidget(test)
            card.addLayout(mcp_buttons)
            self.mcp_rows[name] = (mcp_status, configure, test)
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

        card = self._card(layout, 'Local MCP and REST',
                          'Connect another compatible agent to Arrow on this device. '
                          'Keep Arrow running. Connection settings include a local access token, not a cloud API key.')
        self.endpoint_status = self._label('')
        card.addWidget(self.endpoint_status)
        self.copy_mcp_button = QPushButton('Copy MCP connection JSON')
        self.copy_mcp_button.clicked.connect(self._copy_mcp_connection)
        card.addWidget(self.copy_mcp_button)

    def _refresh_endpoint(self):
        server = getattr(self.window(), '_server', None)
        active = server is not None and getattr(server, '_running', False)
        self.copy_mcp_button.setEnabled(active)
        self.endpoint_status.setText(
            f'MCP: {server.base_url}/mcp\nREST: {server.base_url}/api/captures' if active
            else 'Local server is unavailable. Restart Arrow to reconnect.')
        return server if active else None

    def _copy_mcp_connection(self):
        server = self._refresh_endpoint()
        if server is None:
            return
        from arrow.server.server import app
        try:
            token = app.config['TOKEN_MANAGER'].get_or_create()
            config = {'mcpServers': {'arrow': {'type': 'http', 'url': server.base_url + '/mcp',
                                             'headers': {'Authorization': 'Bearer ' + token}}}}
            QApplication.clipboard().setText(json.dumps(config, indent=2))
            self.endpoint_status.setText('Connection JSON copied. Add it to your MCP client configuration. '
                                         'Only share it with local clients you want to grant access.')
        except OSError as error:
            self.endpoint_status.setText(f'Could not read local connection settings: {error}')

    def _open_install_guide(self, name):
        from arrow.providers.setup import get_provider_install_url
        QDesktopServices.openUrl(QUrl(get_provider_install_url(name)))

    def _check_mcp(self, name, configure=False):
        if name in self._mcp_busy:
            return
        self._mcp_busy.add(name)
        label, setup, test = self.mcp_rows[name]
        setup.setEnabled(False)
        test.setEnabled(False)
        label.setText('MCP: configuring and checking local protocol…' if configure else 'MCP: checking registration and local protocol…')
        def check():
            from arrow.providers.connection import ProviderMCPStatus, configure_provider_mcp, probe_provider_mcp
            try:
                result = configure_provider_mcp(name) if configure else probe_provider_mcp(name)
                if configure and result.registered:
                    result = probe_provider_mcp(name)
            except Exception:
                result = ProviderMCPStatus(name, False, None, None, 'MCP setup could not be checked. Retry after updating the CLI.')
            try:
                self.mcp_checked.emit(name, result)
            except RuntimeError:
                pass
        threading.Thread(target=check, daemon=True).start()

    def _apply_mcp_status(self, name, result):
        self._mcp_busy.discard(name)
        label, setup, test = self.mcp_rows[name]
        setup.setEnabled(True)
        test.setEnabled(True)
        registered = 'registered' if result.registered else 'not registered' if result.registered is False else 'registration unknown'
        protocol = 'local protocol verified' if result.protocol_verified else 'local protocol not verified'
        label.setText(f'MCP: {registered} · {protocol}. {result.message}')

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
            statuses = []
            for name in self.agent_rows:
                try:
                    statuses.append(get_provider_setup_status(name))
                except Exception as error:
                    # Do not expose credential-store output in labels or logs.
                    log.warning('Connection check failed for %s (%s)', name, type(error).__name__)
                    try:
                        self.agent_check_failed.emit(name)
                    except RuntimeError:
                        return
            try:
                self.agents_checked.emit(statuses)
            except RuntimeError:
                pass  # The application may close while a bounded probe runs.

        threading.Thread(target=check, daemon=True).start()

    def _show_agent_check_failure(self, name):
        if name in self._login_processes:
            return
        label, button = self.agent_rows[name]
        label.setText('Could not check connection. Refresh to retry.')
        previous = self._agent_statuses.get(name)
        button.setEnabled(bool(previous and previous.installed))

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
            state = ('CLI signed in' if status.authenticated is True else 'Sign in required'
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
        from arrow.launcher import app_version
        card = self._card(layout, 'App updates', f'Installed version: {app_version()}. Check public releases when you choose.')
        self.update_status = self._label('')
        card.addWidget(self.update_status)
        self.update_button = QPushButton('Check for updates')
        self.update_button.clicked.connect(self._check_updates)
        card.addWidget(self.update_button)
        self.release_button = QPushButton('Open public releases')
        self._release_url = 'https://github.com/Anmol2k5/arrow-annotate/releases'
        self.release_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._release_url)))
        card.addWidget(self.release_button)

    def _check_updates(self):
        self.update_button.setEnabled(False)
        self.update_status.setText('Checking official GitHub releases…')
        def check():
            from arrow.core.updates import UpdateCheckError, check_for_update
            from arrow.launcher import app_version
            try:
                result = check_for_update(app_version())
            except UpdateCheckError as error:
                result = str(error)
            try:
                self.update_checked.emit(result)
            except RuntimeError:
                pass
        threading.Thread(target=check, daemon=True).start()

    def _show_update_result(self, result):
        self.update_button.setEnabled(True)
        if isinstance(result, str):
            self.update_status.setText(result)
            return
        self._release_url = result.url
        self.update_status.setText(f'Update {result.version} is available. Open the release page to review and download.'
                                  if result.available else 'You are on the latest stable release.')

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
            self._refresh_endpoint()
            self.refresh_agents()
