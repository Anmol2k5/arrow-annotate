"""Image and text clipboard payloads for capture cards."""
import sys

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication


def copy_capture(prompt: str, image_path: str, mode: str = 'both') -> None:
    """Offer actual image/text formats; the receiving app decides what to paste."""
    if mode not in ('both', 'image', 'text'):
        raise ValueError('Unknown clipboard mode')
    mime = QMimeData()
    if mode != 'text':
        image = QImage(image_path)
        if image.isNull():
            raise ValueError('Annotated screenshot is missing or unreadable. Try Prompt only.')
        # Qt supplies the native bitmap alongside a lossless PNG representation.
        mime.setImageData(image)
        png = QByteArray()
        buffer = QBuffer(png)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise ValueError('Could not encode the screenshot for the clipboard.')
        encoded = image.save(buffer, 'PNG')
        buffer.close()
        if not encoded:
            raise ValueError('Could not encode the screenshot for the clipboard.')
        mime.setData('image/png', png)
        if sys.platform == 'win32':
            # Qt's Windows image converter offers registered "PNG" only for
            # alpha images. RGB screenshots otherwise get DIB; "image/png" is
            # a separate registered format. This documented Qt MIME mapping
            # explicitly supplies the native PNG bytes for RGB images too.
            mime.setData('application/x-qt-windows-mime;value="PNG"', png)
    if mode != 'image':
        mime.setText(prompt)
    QApplication.clipboard().setMimeData(mime)
