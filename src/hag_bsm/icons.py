"""Read basic facts about an icon file without decoding the whole image."""

import struct
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".icns", ".webp")


@dataclass
class IconInfo:
    path: Path
    exists: bool
    kind: str = ""          # png, ico, svg, jpeg, icns, webp, unknown
    width: int = 0
    height: int = 0
    error: str = ""


def inspect_icon(path_str: str) -> IconInfo:
    path = Path(path_str)
    if not path.is_file():
        return IconInfo(path, False, error="The icon file was not found.")
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError as exc:
        return IconInfo(path, True, error=f"The icon file could not be read: {exc.strerror or exc}")

    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24 and head[12:16] == b"IHDR":
        w, h = struct.unpack(">II", head[16:24])
        return IconInfo(path, True, "png", w, h)
    if head[:4] == b"\x00\x00\x01\x00" and len(head) >= 8:
        # ICO: report the first image's size (0 encodes 256).
        w, h = head[6] or 256, head[7] or 256
        return IconInfo(path, True, "ico", w, h)
    if head[:3] == b"\xff\xd8\xff":
        return IconInfo(path, True, "jpeg")
    if head[:4] == b"icns":
        return IconInfo(path, True, "icns")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return IconInfo(path, True, "webp")
    if b"<svg" in head or path.suffix.lower() == ".svg":
        return IconInfo(path, True, "svg")
    return IconInfo(path, True, "unknown")
