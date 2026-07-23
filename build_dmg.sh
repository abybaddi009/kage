#!/usr/bin/env bash
# Build Alt-Tabber.app and package it into a .dmg using uv + PyInstaller.
#
# Usage:
#   ./build_dmg.sh            # build + package, clean dist/
#   ./build_dmg.sh --no-clean # skip cleaning dist/
#
set -euo pipefail

APP_NAME="Alt-Tabber"
BUNDLE_ID="dev.baddi.abhishek.AltTabber"
SPEC="AltTabber.spec"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT_DIR"

CLEAN=1
if [[ "${1:-}" == "--no-clean" ]]; then
  CLEAN=0
fi

echo "==> Building ${APP_NAME}.app with PyInstaller (via uv)"
if [[ "$CLEAN" -eq 1 ]]; then
  rm -rf build dist
  uv run pyinstaller --noconfirm --clean "$SPEC"
else
  uv run pyinstaller --noconfirm "$SPEC"
fi

APP_PATH="dist/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "error: ${APP_PATH} was not created" >&2
  exit 1
fi

# Stamp the bundle identifier on the Info.plist so the .dmg carries the
# canonical reverse-DNS id even if the spec's value drifted.
echo "==> Setting CFBundleIdentifier to ${BUNDLE_ID}"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" \
  "${APP_PATH}/Contents/Info.plist"

DMG_NAME="${APP_NAME}-${VERSION:-0.1.0}.dmg"
DMG_PATH="dist/${DMG_NAME}"
rm -f "$DMG_PATH"

echo "==> Creating ${DMG_NAME}"
# Create a read-write DMG, copy the app, then convert to a compressed
# read-only image for distribution.
STAGING_DIR="$(mktemp -d -t alttabber_dmg)"
trap 'rm -rf "$STAGING_DIR"' EXIT

cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

RW_DMG="$(mktemp -u -t alttabber_rw).dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING_DIR" \
  -fs HFS+ -size 200m "$RW_DMG" -quiet
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 \
  -o "$DMG_PATH" -quiet
rm -f "$RW_DMG"

echo "==> Done: ${DMG_PATH}"
