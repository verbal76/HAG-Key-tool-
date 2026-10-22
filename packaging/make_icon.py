"""Render assets/app.ico (multi-size, PNG-compressed entries) from the in-code icon drawing.

Run: python packaging/make_icon.py
"""

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from hag_bsm.ui.appicon import render  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    render(size).save(buf, "PNG")
    return bytes(buf.data())


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 (needed for QPixmap)
    images = [png_bytes(s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, img in zip(SIZES, images):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    (out / "app.ico").write_bytes(header + entries + data)
    (out / "app.png").write_bytes(images[-1])
    print(f"Wrote {out / 'app.ico'}")


if __name__ == "__main__":
    main()
