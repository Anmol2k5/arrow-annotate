"""Explicit, transient microphone testing inside Capture settings."""

import threading
import uuid

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arrow.speech.microphone import list_input_devices
from arrow.storage.settings import get_microphone_selection, set_microphone_selection
from arrow.ui.voice_input import VoiceInput


class MicrophonePanel(QWidget):
    devices_loaded = pyqtSignal(object, str)

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.can_start_test = lambda: True
        self._voice = None
        self._capture_id = None
        self._state = 'idle'
        self._refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.device_combo = QComboBox()
        self.device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device_combo.setMinimumContentsLength(16)
        self.device_combo.addItem('System default', None)
        saved = get_microphone_selection()
        if saved:
            self.device_combo.addItem(f'{saved["name"]} ({saved["host_api"]}) · saved', saved)
            self.device_combo.setCurrentIndex(1)
        layout.addWidget(self.device_combo)
        row = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh microphones')
        self.refresh_button.clicked.connect(self._refresh_devices)
        self.save_button = QPushButton('Use microphone')
        self.save_button.clicked.connect(self._save_device)
        row.addWidget(self.refresh_button)
        row.addWidget(self.save_button)
        layout.addLayout(row)
        self.level_meter = QProgressBar()
        self.level_meter.setRange(0, 100)
        self.level_meter.setValue(0)
        self.level_meter.setFormat('Input level: %p%')
        self.level_meter.setStyleSheet('QProgressBar { background: #09090b; color: #d4d4d8; '
                                      'border: 1px solid #3f3f46; border-radius: 6px; '
                                      'text-align: center; min-height: 18px; } '
                                      'QProgressBar::chunk { background: #a78bfa; border-radius: 5px; }')
        layout.addWidget(self.level_meter)
        row = QHBoxLayout()
        self.test_button = QPushButton('Test microphone')
        self.test_button.clicked.connect(self._start_test)
        self.stop_button = QPushButton('Stop and transcribe')
        self.stop_button.clicked.connect(self._finish_test)
        self.cancel_button = QPushButton('Cancel test')
        self.cancel_button.clicked.connect(self.cancel_test)
        for button in (self.test_button, self.stop_button, self.cancel_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status_label = QLabel('Refresh to choose an input, or test the system default. '
                                   'Test audio and text are never saved or sent.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.transcript_view = QPlainTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setMaximumHeight(90)
        self.transcript_view.setPlaceholderText('Your local test transcript appears here. Speak Hindi, English, or both.')
        self.transcript_view.setStyleSheet('background: #09090b; color: #fafafa; border: 1px solid #3f3f46; '
                                          'border-radius: 8px; padding: 6px;')
        layout.addWidget(self.transcript_view)
        self._record_timer = self._timer(10_000, self._finish_test)
        self._opening_timer = self._timer(8_000, lambda: self._timeout('Microphone did not open. Check the input and Windows microphone access.'))
        self._decode_timer = self._timer(60_000, lambda: self._timeout('Local recognition took too long. Retry or repair the voice model.'))
        self.devices_loaded.connect(self._apply_devices)
        QApplication.instance().aboutToQuit.connect(self.cancel_test)
        self._buttons()

    def _timer(self, milliseconds, callback):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(milliseconds)
        timer.timeout.connect(callback)
        return timer

    def _buttons(self):
        idle = self._state == 'idle'
        for control in (self.device_combo, self.save_button, self.refresh_button, self.test_button):
            control.setEnabled(idle and not self._refreshing)
        self.stop_button.setEnabled(self._state == 'recording')
        self.cancel_button.setEnabled(not idle)

    def _refresh_devices(self):
        if self._refreshing or self._state != 'idle':
            return
        self._refreshing = True
        self.status_label.setText('Looking for microphone inputs…')
        self._buttons()
        def work():
            try:
                devices, error = list_input_devices(), ''
            except Exception:
                devices, error = [], 'Could not list inputs. Check Windows sound settings and microphone access, then retry.'
            try:
                self.devices_loaded.emit(devices, error)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _apply_devices(self, devices, error):
        selection = self.device_combo.currentData()
        self.device_combo.clear()
        self.device_combo.addItem('System default', None)
        found = not selection
        for device in devices:
            value = {'name': device['name'], 'host_api': device['host_api']}
            ambiguous = device.get('ambiguous', False)
            label = f'{value["name"]} ({value["host_api"]})'
            self.device_combo.addItem(label + (' · ambiguous; use system default' if ambiguous else ''), value)
            index = self.device_combo.count() - 1
            if ambiguous:
                self.device_combo.model().item(index).setEnabled(False)
            if value == selection and not ambiguous:
                self.device_combo.setCurrentIndex(index)
                found = True
        if not found:
            self.device_combo.addItem(f'{selection["name"]} ({selection["host_api"]}) · unavailable', selection)
            self.device_combo.setCurrentIndex(self.device_combo.count() - 1)
        self._refreshing = False
        self.status_label.setText(error or ('Inputs refreshed. Test before saving your choice.' if devices
                                           else 'No microphone inputs found. Check Windows sound settings and microphone access.'))
        self._buttons()

    def _save_device(self):
        try:
            set_microphone_selection(self.device_combo.currentData())
        except (OSError, ValueError):
            self.status_label.setText('Could not save the input. Check the selection and data-folder access, then retry.')
            return
        self.status_label.setText('Microphone selection saved for future captures.')

    def _start_test(self):
        if self._state != 'idle' or self._refreshing:
            return
        if not self.can_start_test():
            self.status_label.setText('Finish or cancel your current capture before testing the microphone.')
            return
        self._capture_id = 'microphone-test-' + uuid.uuid4().hex
        self._state = 'opening'
        self.transcript_view.clear()
        self.level_meter.setValue(0)
        self.status_label.setText('Opening microphone… Wait for Recording before speaking.')
        voice = VoiceInput(self.language(), microphone_selection=self.device_combo.currentData(), max_recording_seconds=10)
        self._voice = voice
        voice.phase_changed.connect(self._phase)
        voice.audio_level.connect(self._level)
        voice.finished.connect(self._finished)
        self._buttons()
        self._opening_timer.start()
        voice.start_listening(self._capture_id)

    def _phase(self, phase, capture_id):
        if capture_id != self._capture_id:
            return
        if phase == 'recording':
            self._opening_timer.stop()
            self._state = phase
            self.status_label.setText('Recording… Speak normally. Stop when finished; the test stops after 10 seconds.')
            self._record_timer.start()
        elif phase == 'transcribing':
            self._record_timer.stop()
            self._opening_timer.stop()
            self._state = phase
            self.status_label.setText('Transcribing locally… No audio is uploaded.')
            self._decode_timer.start()
        self._buttons()

    def _level(self, level, capture_id):
        if capture_id == self._capture_id:
            bounded = max(0., min(1., level))
            self.level_meter.setValue(max(1, round(bounded * 100)) if bounded else 0)

    def _finish_test(self):
        if self._voice is None or self._state != 'recording':
            return
        self._record_timer.stop()
        self._state = 'finishing'
        self.status_label.setText('Finishing recording…')
        self._decode_timer.start()
        self._voice.finish_listening()
        self._buttons()

    def _finished(self, text, error, capture_id):
        if capture_id != self._capture_id:
            return
        self._stop_timers()
        self._state, self._voice, self._capture_id = 'idle', None, None
        self.transcript_view.setPlainText(text)
        self.status_label.setText(error or 'Local transcript ready. Check that it matches what you said; '
                                 'automatic recognition may use Hindi or English script.')
        self._buttons()

    def _stop_timers(self):
        for timer in (self._record_timer, self._opening_timer, self._decode_timer):
            timer.stop()

    def cancel_test(self):
        self._stop_timers()
        voice = self._voice
        self._state, self._voice, self._capture_id = 'idle', None, None
        if voice is not None:
            voice.stop_listening()
            self.level_meter.setValue(0)
            self.status_label.setText('Microphone test cancelled. Nothing was saved or sent.')
        self._buttons()

    def _timeout(self, message):
        self.cancel_test()
        self.status_label.setText(message)

    def hideEvent(self, event):
        self.cancel_test()
        super().hideEvent(event)
