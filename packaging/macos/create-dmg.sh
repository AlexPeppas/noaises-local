#!/usr/bin/env bash
# Create a macOS .dmg installer from the PyInstaller .app bundle.
#
# Prerequisites:
#   brew install create-dmg
#
# Usage:
#   1. Build with PyInstaller first:  uv run python packaging/build.py
#   2. Run this script:               bash packaging/macos/create-dmg.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_PATH="$REPO_ROOT/dist/noaises.app"
DMG_OUTPUT="$REPO_ROOT/dist/noaises-0.1.0.dmg"
ICON_PATH="$REPO_ROOT/packaging/icons/noaises.icns"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run 'uv run python packaging/build.py' first."
    exit 1
fi

# Remove old DMG if it exists
rm -f "$DMG_OUTPUT"

DMG_ARGS=(
    --volname "noaises"
    --window-pos 200 120
    --window-size 600 400
    --icon-size 100
    --icon "noaises.app" 175 190
    --hide-extension "noaises.app"
    --app-drop-link 425 190
)

# Add volume icon if it exists
if [ -f "$ICON_PATH" ]; then
    DMG_ARGS+=(--volicon "$ICON_PATH")
fi

echo "Creating DMG..."
create-dmg "${DMG_ARGS[@]}" "$DMG_OUTPUT" "$APP_PATH"

echo "DMG created: $DMG_OUTPUT"
