from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from arrow.ui.notch import ScreenshotThumbnail


def test_chatgpt_copy_guides_image_then_prompt_without_timed_clipboard_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv('ARROW_HOME', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    path = str(tmp_path / 'annotated.png')
    image = QImage(20, 30, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    image.save(path)
    card = ScreenshotThumbnail(path, change_request={
        'raw_user_request': 'Move this here', 'normalized_intent': 'move_element',
    })
    card._copy_request()
    mime = app.clipboard().mimeData()
    assert mime.hasImage() and not mime.hasText()
    assert 'paste' in card._action_status.text().lower()
    assert 'prompt' in card._combined_copy_button.text().lower()
    card._change_request['raw_user_request'] = 'Move this lower instead'
    card._copy_request()
    assert not app.clipboard().mimeData().hasImage()
    assert 'Move this lower instead' in app.clipboard().text()
    assert card._combined_copy_button.text() == 'Copy image + prompt'
    card.close()
