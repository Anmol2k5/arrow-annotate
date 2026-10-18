"""Capture shortcut and speech recognition preferences."""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from arrow.storage.settings import DEFAULT_CAPTURE_SHORTCUT, DEFAULT_SPEECH_LANGUAGE


class CaptureSettingsDialog(QDialog):
    def __init__(self, shortcut: str, language: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Capture settings')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        instructions = QLabel('Hold your shortcut to record your instructions. '
                              'Release any shortcut key to finish speaking and annotate the capture.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        form = QFormLayout()
        self.shortcut_input = QLineEdit(shortcut)
        self.shortcut_input.setPlaceholderText('ctrl+space or ctrl+shift')
        form.addRow('Capture shortcut', self.shortcut_input)
        self.language_combo = QComboBox()
        self.language_combo.addItem('English (India)', 'en-IN')
        self.language_combo.addItem('Hindi (India)', 'hi-IN')
        self.language_combo.addItem('English (United States)', 'en-US')
        index = self.language_combo.findData(language)
        self.language_combo.setCurrentIndex(max(0, index))
        form.addRow('Speech language', self.language_combo)
        layout.addLayout(form)

        hint = QLabel('Modifier-only shortcuts such as Ctrl+Shift are supported. '
                      'Fn is usually handled by keyboard firmware and cannot be reliably detected; '
                      'use Ctrl, Alt, Shift, or Windows/Command instead. Esc and Enter are reserved '
                      'for cancelling and finishing captures.')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        defaults = QPushButton('Restore defaults')
        defaults.clicked.connect(self._restore_defaults)
        layout.addWidget(defaults)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _restore_defaults(self):
        self.shortcut_input.setText(DEFAULT_CAPTURE_SHORTCUT)
        self.language_combo.setCurrentIndex(self.language_combo.findData(DEFAULT_SPEECH_LANGUAGE))

    def values(self) -> tuple[str, str]:
        return self.shortcut_input.text().strip(), self.language_combo.currentData()
