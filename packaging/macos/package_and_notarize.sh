#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:?Usage: package_and_notarize.sh <app-path> <dmg-path> [volume-name]}"
DMG_PATH="${2:?Usage: package_and_notarize.sh <app-path> <dmg-path> [volume-name]}"
VOLUME_NAME="${3:-CurveMole}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Application bundle not found: $APP_PATH" >&2
  exit 1
fi

create_dmg() {
  local stage_dir
  stage_dir="$(mktemp -d)"
  ditto "$APP_PATH" "$stage_dir/CurveMole.app"

  for attempt in 1 2 3; do
    if hdiutil create \
      -volname "$VOLUME_NAME" \
      -srcfolder "$stage_dir" \
      -ov -format UDZO \
      "$DMG_PATH"; then
      rm -rf "$stage_dir"
      return 0
    fi
    echo "hdiutil create failed (attempt ${attempt}/3); cleaning up before retry."
    hdiutil detach "/Volumes/$VOLUME_NAME" -force >/dev/null 2>&1 || true
    rm -f "$DMG_PATH"
    sleep $((attempt * 5))
  done

  rm -rf "$stage_dir"
  echo "hdiutil create failed after 3 attempts." >&2
  return 1
}

required_secrets=(
  MACOS_CERTIFICATE
  MACOS_CERTIFICATE_PASSWORD
  APPLE_ID
  APPLE_APP_SPECIFIC_PASSWORD
  APPLE_TEAM_ID
)
missing=()
for name in "${required_secrets[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done

# Keep development builds usable even before the maintainer adds Apple credentials.
# Release builds become Gatekeeper-clean automatically as soon as all five secrets
# are present in the repository Actions secrets.
if (( ${#missing[@]} > 0 )); then
  echo "::warning::Apple signing/notarization is disabled; missing GitHub Actions secrets: ${missing[*]}"
  create_dmg
  echo "Created unsigned macOS package: $DMG_PATH"
  exit 0
fi

work_dir="$(mktemp -d)"
certificate_path="$work_dir/developer-id.p12"
keychain_path="$work_dir/curvemole-signing.keychain-db"
keychain_password="$(openssl rand -hex 24)"

cleanup() {
  security delete-keychain "$keychain_path" >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT

# Decode with Python to avoid BSD/GNU base64 flag differences between runners.
python3 - <<'PY'
import base64
import os
from pathlib import Path

Path(os.environ["CERTIFICATE_PATH"]).write_bytes(
    base64.b64decode(os.environ["MACOS_CERTIFICATE"], validate=True)
)
PY

security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 21600 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
security import "$certificate_path" \
  -k "$keychain_path" \
  -P "$MACOS_CERTIFICATE_PASSWORD" \
  -A -t cert -f pkcs12
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s -k "$keychain_password" \
  "$keychain_path"
security list-keychains -d user -s "$keychain_path"
security default-keychain -d user -s "$keychain_path"

signing_identity="$(
  security find-identity -v -p codesigning "$keychain_path" \
    | awk -F'"' '/Developer ID Application/ {print $2; exit}'
)"
if [[ -z "$signing_identity" ]]; then
  echo "No 'Developer ID Application' identity was found in MACOS_CERTIFICATE." >&2
  exit 1
fi

echo "Using Apple signing identity: $signing_identity"

# Re-sign the complete PyInstaller bundle with hardened runtime and a trusted
# timestamp. PyInstaller may ad-hoc sign nested Mach-O files during collection;
# --deep replaces those signatures consistently with the Developer ID identity.
codesign \
  --force \
  --deep \
  --options runtime \
  --timestamp \
  --sign "$signing_identity" \
  "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

# Notarize and staple the .app itself so it remains Gatekeeper-verifiable even
# after it has been copied out of the disk image or the Mac is temporarily offline.
app_archive="$work_dir/CurveMole.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$app_archive"
xcrun notarytool submit "$app_archive" \
  --apple-id "$APPLE_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait
xcrun stapler staple "$APP_PATH"
xcrun stapler validate "$APP_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH"

create_dmg

# Sign, notarize, and staple the final transport container as well.
codesign --force --timestamp --sign "$signing_identity" "$DMG_PATH"
codesign --verify --verbose=2 "$DMG_PATH"
xcrun notarytool submit "$DMG_PATH" \
  --apple-id "$APPLE_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG_PATH"

echo "Created signed and notarized macOS package: $DMG_PATH"
