import sys
from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QPushButton

import arrow.ui.clipboard as clipboard
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


@pytest.mark.parametrize('mode', ['both', 'image'])
@pytest.mark.parametrize('image_format', [QImage.Format.Format_RGB32, QImage.Format.Format_ARGB32])
def test_windows_png_format_carries_all_pixels_and_unicode_prompt(tmp_path, monkeypatch, mode, image_format):
    app = QApplication.instance() or QApplication([])
    # Exercise construction of the Windows payload on every platform. The
    # separate native test below verifies the OS clipboard on Windows itself.
    monkeypatch.setattr(clipboard, 'sys', SimpleNamespace(platform='win32'), raising=False)
    image = QImage(3, 2, image_format)
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(x, y, QColor(20 + x * 50, 30 + y * 80, 200, 100 + x * 70))
    path = str(tmp_path / 'annotated.png')
    assert image.save(path)
    prompt = 'Move Café → 左側 📎\nKeep the label <button> & spacing.'

    copy_capture(prompt, path, mode=mode)

    mime = app.clipboard().mimeData()
    native_png = bytes(mime.data('application/x-qt-windows-mime;value="PNG"'))
    assert native_png.startswith(b'\x89PNG\r\n\x1a\n')
    assert native_png == bytes(mime.data('image/png'))
    pasted = QImage.fromData(native_png)
    assert pasted.size() == image.size()
    for y in range(image.height()):
        for x in range(image.width()):
            assert pasted.pixelColor(x, y) == image.pixelColor(x, y)
    assert not mime.hasUrls()
    if mode == 'both':
        assert mime.text() == prompt
    else:
        assert not mime.hasText()


def test_failed_png_encoding_preserves_previous_clipboard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    path = str(tmp_path / 'annotated.png')
    assert image.save(path)
    app.clipboard().setText('previous clipboard')
    monkeypatch.setattr(QImage, 'save', lambda *args: False)

    with pytest.raises(ValueError, match='encode'):
        copy_capture('new prompt', path)

    assert app.clipboard().text() == 'previous clipboard'


@pytest.mark.skipif(sys.platform != 'win32', reason='Requires the native Windows clipboard')
def test_native_windows_clipboard_exposes_png_and_unicode_text(tmp_path):
    import ctypes
    from ctypes import wintypes

    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'windows':
        pytest.skip('Requires the Windows Qt platform plugin')
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor('#e23d45'))
    path = str(tmp_path / 'annotated.png')
    assert image.save(path)
    prompt = 'Café → 左側 📎\nSecond line'
    copy_capture(prompt, path)
    app.processEvents()

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    png_format = user32.RegisterClipboardFormatW('PNG')
    assert png_format
    assert user32.IsClipboardFormatAvailable(png_format)
    assert user32.IsClipboardFormatAvailable(13)  # CF_UNICODETEXT
    assert user32.OpenClipboard(None), ctypes.get_last_error()
    try:
        def read_native(format_id):
            handle = user32.GetClipboardData(format_id)
            assert handle, ctypes.get_last_error()
            pointer = kernel32.GlobalLock(handle)
            assert pointer, ctypes.get_last_error()
            try:
                return ctypes.string_at(pointer, kernel32.GlobalSize(handle))
            finally:
                kernel32.GlobalUnlock(handle)

        png = read_native(png_format)
        text = read_native(13).decode('utf-16-le').rstrip('\x00')
    finally:
        user32.CloseClipboard()
    assert QImage.fromData(png).pixelColor(0, 0) == QColor('#e23d45')
    assert text.replace('\r\n', '\n') == prompt


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
