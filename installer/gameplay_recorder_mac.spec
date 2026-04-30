# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for macOS one-folder + .app bundle build.
# NOTE: Run from the repo root:  pyinstaller installer/gameplay_recorder_mac.spec --noconfirm
# UPX is disabled — Apple notarization does not support UPX-compressed binaries.

block_cipher = None

a = Analysis(
    ['../src/gameplay_recorder/__main__.py'],
    pathex=['../src'],
    binaries=[],
    datas=[
        ('../resources/ffmpeg', 'resources/ffmpeg'),
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
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='gameplay_recorder',
)

app = BUNDLE(
    coll,
    name='gameplay_recorder.app',
    icon=None,
    bundle_identifier='com.mariopradeses.gameplay_recorder',
)
