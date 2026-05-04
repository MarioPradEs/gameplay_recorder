# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Windows one-folder build.
# NOTE: Run from the repo root:  pyinstaller installer/gameplay_recorder_win.spec --noconfirm

block_cipher = None

a = Analysis(
    [r'..\src\gameplay_recorder\__main__.py'],
    pathex=[r'..\src'],
    binaries=[],
    datas=[
        (r'..\resources\ffmpeg', 'resources/ffmpeg'),
        (r'..\resources\scrcpy', 'resources/scrcpy'),
    ],
    hiddenimports=[
        'adbutils',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gameplay_recorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='gameplay_recorder',
)
