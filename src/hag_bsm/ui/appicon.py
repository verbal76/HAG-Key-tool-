"""The application icon, drawn in code so no binary artwork is needed at runtime: an attic roof with a key."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def render(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1e2128"))
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 12 * s, 12 * s)
    roof = QPainterPath()
    roof.moveTo(10 * s, 34 * s)
    roof.lineTo(32 * s, 12 * s)
    roof.lineTo(54 * s, 34 * s)
    p.setPen(QPen(QColor("#e8833a"), 6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(roof)
    p.setPen(QPen(QColor("#e6e8ee"), 4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawEllipse(QPointF(24 * s, 40 * s), 6 * s, 6 * s)
    p.drawLine(QPointF(30 * s, 40 * s), QPointF(48 * s, 40 * s))
    p.drawLine(QPointF(42 * s, 40 * s), QPointF(42 * s, 46 * s))
    p.drawLine(QPointF(47 * s, 40 * s), QPointF(47 * s, 45 * s))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render(size))
    return icon
