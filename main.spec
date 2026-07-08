# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('favicon.ico', '.'), ('favicon_src.png', '.')],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtSvg', 'PyPDF2', 'openpyxl', 'docx', 'xlrd', 'olefile', 'cv2', 'numpy', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['rarfile', 'py7zr', 'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets', 'PyQt5.QtSql', 'PyQt5.QtBluetooth', 'PyQt5.QtNetwork', 'PyQt5.QtXml', 'PyQt5.QtTest', 'PyQt5.QtDBus', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets', 'matplotlib', 'scipy', 'tornado', 'notebook', 'IPython', 'jupyter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='主板项目文件浏览器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='favicon.ico',  # 使用favicon.ico作为应用图标
)
