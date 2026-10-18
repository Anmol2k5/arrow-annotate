"""Image and text clipboard payloads for capture cards."""
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication


def copy_capture(prompt: str, image_path: str, mode: str = 'both') -> None:
    if mode not in ('both', 'image', 'text'):
        raise ValueError('Unknown clipboard mode')
    mime = QMimeData()
    if mode != 'text':
        image = QImage(image_path)
        if image.isNull():
            raise ValueError('Annotated screenshot is missing or unreadable. Try Prompt only.')
        # Qt supplies the native Windows bitmap format; PNG retains the exact
        # image for applications that request an explicit MIME type.
        mime.setImageData(image)
        png = QByteArray()
        buffer = QBuffer(png)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        buffer.close()
        mime.setData('image/png', png)
    if mode != 'image':
        mime.setText(prompt)
    QApplication.clipboard().setMimeData(mime)
