# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for noaises — local-first AI companion.

Build with:  python packaging/build.py
Or directly:  pyinstaller --clean --noconfirm packaging/noaises.spec
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

REPO_ROOT = Path(SPECPATH).parent
SRC_DIR = REPO_ROOT / "src"

# ── Collect native-library packages ──
# Each returns (datas, binaries, hiddenimports)

packages_to_collect = [
    "ctranslate2",
    "azure.cognitiveservices.speech",
    "sounddevice",
    "webview",
    "claude_agent_sdk",
]

all_datas = []
all_binaries = []
all_hiddenimports = []

for pkg in packages_to_collect:
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
        all_datas += datas
        all_binaries += binaries
        all_hiddenimports += hiddenimports
    except Exception as e:
        print(f"Warning: could not collect {pkg}: {e}")

# ── Hidden imports ──
all_hiddenimports += collect_submodules("noaises")
all_hiddenimports += [
    "faster_whisper",
    "pydantic",
    "pydantic_settings",
    "mcp",
    "anthropic",
    "dotenv",
    "numpy",
    "mss",
]
# tomllib is stdlib in 3.11+, but declare it for safety
if sys.version_info >= (3, 11):
    all_hiddenimports.append("tomllib")

# ── Data files ──
all_datas += [
    # Surface web assets
    (str(SRC_DIR / "noaises" / "surface" / "web"), "noaises/surface/web"),
    # Config files
    (str(REPO_ROOT / "config"), "config"),
]

# ── Analysis ──
a = Analysis(
    [str(REPO_ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC_DIR)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[str(REPO_ROOT / "packaging" / "hooks")],
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
    name="noaises",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # keep console for voice/debug output
    icon=str(REPO_ROOT / "packaging" / "icons" / "noaises.ico")
    if (REPO_ROOT / "packaging" / "icons" / "noaises.ico").exists()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="noaises",
)

# ── macOS .app bundle ──
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="noaises.app",
        icon=str(REPO_ROOT / "packaging" / "icons" / "noaises.icns")
        if (REPO_ROOT / "packaging" / "icons" / "noaises.icns").exists()
        else None,
        bundle_identifier="com.noaises.companion",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSMicrophoneUsageDescription": "noaises needs microphone access for voice interaction.",
            "NSHighResolutionCapable": True,
        },
    )
