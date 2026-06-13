# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('favicon.ico', '.'), ('favicon_src.png', '.')],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtSvg', 'PyQt5.QtGui.QPixmap', 'PyQt5.QtGui.QImage', 'PyQt5.QtWidgets.QLabel', 'PyQt5.QtWidgets.QScrollArea', 'PyPDF2', 'openpyxl', 'docx', 'xlrd', 'olefile', 'rarfile', 'py7zr', 'cv2', 'numpy', 'PIL', 'subprocess', 'traceback'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
