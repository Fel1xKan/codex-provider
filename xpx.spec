# -*- mode: python ; coding: utf-8 -*-

import sys

APP_ICON = (
    'assets/icons/codex-provider.icns'
    if sys.platform == 'darwin'
    else 'assets/icons/codex-provider.ico'
)

a = Analysis(
    ['src/cli/xpx.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('data/model-catalog.json', 'data'),
    ],
    hiddenimports=[
        'yaml',
        'tomlkit',
        'json5',
        'cryptography',
        'sqlite3',
        'lib.common',
        'lib.common.oscrypt',
        'lib.xpx',
        'lib.xpx.store',
        'lib.xpx.models',
        'lib.xpx.adapters',
        'lib.xpx.commands',
        'lib.xpx.accounts',
    ],
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
    name='xpx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
)
