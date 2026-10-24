# PyInstaller spec for the Windows build. Run from the repository root:
#   pyinstaller --noconfirm --clean packaging/hag_bsm.spec
# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from hag_bsm import __version__  # noqa: E402

ver = tuple(int(x) for x in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))

version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={ver}, prodvers={ver}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Hot Attic Games'),
      StringStruct('FileDescription', 'Hot Attic Games Build & Signing Manager'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'HotAtticBuildSigningManager'),
      StringStruct('LegalCopyright', 'Copyright (c) Hot Attic Games. All rights reserved.'),
      StringStruct('OriginalFilename', 'HotAtticBuildSigningManager.exe'),
      StringStruct('ProductName', 'Hot Attic Games Build & Signing Manager'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HotAtticBuildSigningManager",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(version_file),
)
