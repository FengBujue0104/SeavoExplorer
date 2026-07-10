# -*- mode: python ; coding: utf-8 -*-

import os
import sys


PROJECT_ROOT = os.path.abspath(SPECPATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from build_support import (
    APP_NAME,
    DATA_FILES,
    EXCLUDED_MODULES,
    HIDDEN_IMPORTS,
    audit_binary_entries,
    configure_spec_environment,
    write_version_info_file,
)


BUILD_MODE = os.environ.get('SEAVO_BUILD_MODE', 'onefile').strip().lower()
if BUILD_MODE not in ('onefile', 'onedir'):
    raise SystemExit('SEAVO_BUILD_MODE 只允许 onefile 或 onedir')

configure_spec_environment()
VERSION_INFO = write_version_info_file()


a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, source), destination)
        for source, destination in DATA_FILES
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)

# PyInstaller 会沿 PATH 搜索 DLL；这里在生成产物前拒绝工作区、Python 与 Windows
# 系统目录之外的二进制来源，防止第三方程序自带 DLL 混入分发包。
audit_binary_entries(a.binaries)

pyz = PYZ(a.pure)

exe_options = {
    'name': APP_NAME,
    'debug': False,
    'bootloader_ignore_signals': False,
    'strip': False,
    'upx': False,
    'console': False,
    'disable_windowed_traceback': False,
    'argv_emulation': False,
    'target_arch': None,
    'codesign_identity': None,
    'entitlements_file': None,
    'icon': os.path.join(PROJECT_ROOT, 'favicon.ico'),
    'version': VERSION_INFO,
}

if BUILD_MODE == 'onefile':
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **exe_options,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        contents_directory='_internal',
        **exe_options,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
