"""One-off: generate icon.ico / icon.png for the packaged app."""
import os
from PySide6.QtGui import QPixmap, QPainter, QColor, QGuiApplication
from PySide6.QtCore import Qt

_app = QGuiApplication([])  # required before any QPixmap/QPainter use

pix = QPixmap(256, 256)
pix.fill(Qt.transparent)
p = QPainter(pix)
p.setRenderHint(QPainter.Antialiasing, True)
p.setPen(Qt.NoPen)
for frac, col in ((0.46, "#2b7bff"), (0.32, "#39e639"), (0.17, "#ff2020")):
    r = 256 * frac
    p.setBrush(QColor(col))
    p.drawEllipse(int(128 - r), int(128 - r), int(2 * r), int(2 * r))
p.end()
print("ico:", pix.save("icon.ico", "ICO"), "png:", pix.save("icon.png", "PNG"))
print("size:", os.path.getsize("icon.ico") if os.path.exists("icon.ico") else "none")
