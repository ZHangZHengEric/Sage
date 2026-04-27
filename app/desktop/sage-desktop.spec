# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Sage desktop sidecar.

This file is the single source of truth for the PyInstaller bundle.
`app/desktop/scripts/build.sh` invokes `pyinstaller sage-desktop.spec`
instead of passing CLI flags. Behaviour is parameterised via env vars:

  SAGE_PYI_MODE     release | debug  (default: release)
                      release => strip=True; on Windows, sidecar EXE is built
                        without a console (no black terminal window)
                      debug   => strip=False; on Windows, console is kept for logs
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


# --- mode ---
_MODE = os.environ.get("SAGE_PYI_MODE", "release").lower()
_STRIP = _MODE == "release"
# Windows: release sidecar should not pop a console when Tauri spawns it; debug keeps one.
# macOS/Linux: unchanged (stdio/Tauri behavior; no extra terminal window in typical use).
_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    _CONSOLE = _MODE != "release"
else:
    _CONSOLE = True


# --- collect deps that PyInstaller cannot trace statically ---
datas = []
binaries = []

# `sagents.tool.impl.__init__` uses lazy `__getattr__` for tool modules,
# so the static tracer never reaches the @tool decorators. Collect the
# whole `sagents` tree so every tool/skill module ends up in the PYZ.
hiddenimports = [
    "aiosqlite",
    "greenlet",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "certifi",
    "croniter",
    "scrapling",
    "scrapling.fetchers",
    "apify_fingerprint_datapoints",
    "browserforge",
    "undetected_playwright",
]
hiddenimports += collect_submodules("sagents")
hiddenimports += collect_submodules("sagents.tool.impl")
hiddenimports += collect_submodules("sagents.skill")

for _pkg in (
    "certifi",
    "croniter",
    "scrapling",
    "apify_fingerprint_datapoints",
    "browserforge",
    "undetected_playwright",
):
    _datas, _bins, _hidden = collect_all(_pkg)
    datas += _datas
    binaries += _bins
    hiddenimports += _hidden


# Modules safe to drop to keep the bundle small. `distutils` intentionally
# kept (excluding it breaks undetected_playwright on some versions).
excludes = [
    # browserforge ships an injector that is incompatible with the version
    # of undetected_playwright we vendor; let our own copy win.
    "browserforge.injectors.undetected_playwright",
    "tkinter",
    "unittest",
    "email.test",
    "test",
    "tests",
    "setuptools",
    "xmlrpc",
    "IPython",
    "notebook",
]


a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sage-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=_STRIP,
    upx=False,
    console=_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=_STRIP,
    upx=False,
    upx_exclude=[],
    name="sage-desktop",
)
