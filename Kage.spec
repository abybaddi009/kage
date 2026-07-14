# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/kage/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/kage/assets/logo.png', 'kage/assets'),
        ('src/kage/assets/default.png', 'kage/assets'),
        ('src/kage/assets/thumbnails.png', 'kage/assets'),
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='Kage',
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
    icon=['assets/logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Kage',
)
app = BUNDLE(
    coll,
    name='Kage.app',
    icon='assets/logo.icns',
    bundle_identifier='dev.baddi.abhishek.Kage',
)
