# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("settings.sample.json", "."),
        *collect_data_files("pvporcupine"),
        *collect_data_files("RealtimeSTT"),
        *collect_data_files("openwakeword"),
    ],
    hiddenimports=[
        "openai",
        "google.genai",
        "RealtimeSTT",
        "pvporcupine",
    ],
    hookspath=["pyinstaller_hooks"],
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
    name="speaki",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="speaki",
)
