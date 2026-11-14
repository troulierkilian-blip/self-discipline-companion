import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication
from companion.widgets import app_pixmap

app = QApplication([])
directory = Path(__file__).resolve().parents[1] / "assets"
directory.mkdir(exist_ok=True)
images = []
for size in (16, 32, 48, 128, 256):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    app_pixmap(size).save(buffer, "PNG")
    images.append((size, bytes(buffer.data())))
offset = 6 + 16 * len(images)
entries = []
for size, data in images:
    entries.append(struct.pack("<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(directory / "companion.ico").write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(data for _, data in images))
app_pixmap(256).save(str(directory / "companion.png"))
