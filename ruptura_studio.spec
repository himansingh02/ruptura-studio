# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RUPTURA Studio -> a single self-contained executable.
# Build:  pyinstaller ruptura_studio.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

# RUPTURA ships a compiled C-extension + data; PIL is pulled in by matplotlib's
# Tk toolbar and needs its tkinter bridge. Pull everything in for both.
for pkg in ("ruptura", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# matplotlib data files + the Tk backend + PIL's tkinter finder (toolbar icons)
datas += collect_data_files("matplotlib")
hiddenimports += ["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder"]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PySide2", "PySide6", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="RUPTURA-Studio",
    debug=False, strip=False, upx=False,
    console=False,            # GUI app, no terminal window
    onefile=True,
)
