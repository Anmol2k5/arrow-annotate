from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QPushButton

from arrow.ui.clipboard import copy_capture
from arrow.ui.notch import ScreenshotThumbnail


def test_copy_carries_actual_annotated_pixels_and_prompt(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(10, 20, QImage.Format.Format_RGB32)
    image.fill(QColor('#e23d45'))
    path = str(tmp_path / 'annotated.png')
    assert image.save(path)
    copy_capture('Move the circled button', path)
    mime = app.clipboard().mimeData()
    assert mime.hasImage() and mime.hasText()
    assert mime.text() == 'Move the circled button'
    assert 'Screenshot:' not in mime.text()
    assert bytes(mime.data('image/png')).startswith(b'\x89PNG')
    pasted = QImage.fromData(mime.data('image/png'))
    assert pasted.size() == image.size()
    assert pasted.pixelColor(0, 0) == QColor('#e23d45')


def test_explicit_copy_modes_support_apps_that_choose_one_format(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor('blue'))
    path = str(tmp_path / 'shot.png')
    image.save(path)
    copy_capture('prompt', path, mode='image')
    assert app.clipboard().mimeData().hasImage()
    assert not app.clipboard().mimeData().hasText()
    copy_capture('prompt', path, mode='text')
    assert app.clipboard().text() == 'prompt'
    assert not app.clipboard().mimeData().hasImage()


def test_thumbnail_preserves_whole_image_and_all_actions_fit(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(100, 200, QImage.Format.Format_RGB32)
    image.fill(QColor('blue'))
    path = str(tmp_path / 'shot.png')
    image.save(path)
    card = ScreenshotThumbnail(path, change_request={'raw_user_request': 'move this', 'normalized_intent': 'unknown'})
    card.show()
    app.processEvents()
    pixmap = card._img_label.pixmap()
    assert pixmap.height() / pixmap.width() == 2  # no center crop
    buttons = {button.text(): button for button in card.findChildren(QPushButton)}
    assert {'Copy image + prompt', 'Image only', 'Prompt only'} <= buttons.keys()
    for button in buttons.values():
        bounds = button.mapTo(card, button.rect().topLeft())
        assert bounds.x() >= 0 and bounds.x() + button.width() <= card.width()
    card.close()
