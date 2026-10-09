# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller: un único ExaPyme.exe, sin consola.
# Uso:  pyinstaller ExaPyme.spec --noconfirm --clean   (lo hace construir.ps1)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ExaPyme",
    icon="recursos/micomercio.ico",
    console=False,
    upx=False,
    debug=False,
    strip=False,
    disable_windowed_traceback=False,
)
