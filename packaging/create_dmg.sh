#!/usr/bin/env bash
set -euo pipefail
mkdir -p release
APP=$(find dist -maxdepth 1 -name "*.app" -print -quit)
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "missing app bundle: $APP" >&2
  exit 1
fi
# G2: the licence material ships visibly next to the app inside the disk image (it also
# travels inside the bundle, but a reviewer should not have to dig for it).
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
cp LICENSE THIRD_PARTY_NOTICES.md "$STAGE/"
cp -R licenses "$STAGE/licenses"
hdiutil create -volname "Photo Guard" -srcfolder "$STAGE" -ov -format UDZO "release/PhotoGuard-macOS-arm64.dmg"
