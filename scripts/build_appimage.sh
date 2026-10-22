#!/usr/bin/env bash
set -euo pipefail
ICON=$1
APPIMAGE=$2
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
