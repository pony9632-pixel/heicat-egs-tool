# -*- mode: python ; coding: utf-8 -*-
"""
黑貓宅急便工具 — PyInstaller spec
用法：pyinstaller 黑貓宅急便工具.spec --clean   （在 repo 根目錄執行）
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
SRC  = ROOT / "黑貓主程式"

block_cipher = None

a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(SRC / "config.yaml.example"),   "."),
        (str(SRC / "EPBReportQuery.class"),  "."),
    ],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        "yaml",
        "requests",
        "pypdf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "PyQt5", "wx"],
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
    name="黑貓宅急便工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="黑貓宅急便工具",
)

app = BUNDLE(
    coll,
    name="黑貓宅急便工具.app",
    icon=str(ROOT / "packaging" / "icon.icns"),
    bundle_identifier="com.studioa.heicat",
    info_plist={
        "CFBundleShortVersionString": "2.4.2",
        "CFBundleVersion":            "2.4.2",
        "NSHighResolutionCapable":    True,
        "NSRequiresAquaSystemAppearance": False,
        "LSMinimumSystemVersion":     "11.0",
        "CFBundleDisplayName":        "黑貓宅急便工具",
    },
)
