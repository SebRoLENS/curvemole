#!/usr/bin/env bash
set -euo pipefail
ICON=$1
APPIMAGE=$2
LOCAL_COMMIT=${CURVEMOLE_LOCAL_COMMIT:-}
if [[ -n "$LOCAL_COMMIT" && ! "$LOCAL_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "CURVEMOLE_LOCAL_COMMIT must be a full Git commit SHA." >&2
  exit 2
fi
mkdir -p CurveMole.AppDir/usr/lib/curvemole
cp -a dist/CurveMole/. CurveMole.AppDir/usr/lib/curvemole/
cp packaging/linux/curvemole.desktop CurveMole.AppDir/curvemole.desktop
mkdir -p CurveMole.AppDir/usr/share/mime/packages
cp packaging/linux/curvemole.xml CurveMole.AppDir/usr/share/mime/packages/curvemole.xml
cp "$ICON" CurveMole.AppDir/curvemole.png
cp "$ICON" CurveMole.AppDir/.DirIcon
cat > CurveMole.AppDir/AppRun <<'EOF'
#!/bin/sh
APPDIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
EOF
if [[ -n "$LOCAL_COMMIT" ]]; then
  printf 'export CURVEMOLE_LOCAL_COMMIT=%s\n' "$LOCAL_COMMIT" >> CurveMole.AppDir/AppRun
fi
cat >> CurveMole.AppDir/AppRun <<'EOF'
exec "$APPDIR/usr/lib/curvemole/CurveMole" "$@"
EOF
chmod +x CurveMole.AppDir/AppRun
curl -L --fail --retry 3 \
  -o appimagetool-x86_64.AppImage \
  https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 \
  ./appimagetool-x86_64.AppImage --no-appstream CurveMole.AppDir "$APPIMAGE"
chmod +x "$APPIMAGE"
