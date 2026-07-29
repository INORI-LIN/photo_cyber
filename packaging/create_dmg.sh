#!/usr/bin/env bash
set -euo pipefail
mkdir -p release
APP=$(find dist -maxdepth 1 -name "*.app" -print -quit)
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "missing app bundle: $APP" >&2
  exit 1
fi
hdiutil create -volname "Photo Guard" -srcfolder "$APP" -ov -format UDZO "release/PhotoGuard-macOS-arm64.dmg"
