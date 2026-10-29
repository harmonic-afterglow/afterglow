#!/usr/bin/env bash
# Wrap PyInstaller's one-folder Linux build (dist/afterglow/) as an AppImage:
# dist/afterglow-linux-<arch>.AppImage, for the machine's own architecture.
#
#   packaging/linux/build-appimage.sh
#
# build-bundle.sh runs it after PyInstaller. The tool and the runtime it embeds are pinned
# by checksum: both come from one project's releases, and the runtime is the first code
# that runs when the AppImage is started. The runtime is the static type-2 one, so a
# system without libfuse2 - Ubuntu 22.04 and later as installed - still starts it, and one
# without FUSE at all can run it with --appimage-extract-and-run.
set -euxo pipefail

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)
    TOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
    RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d ;;
  aarch64)
    TOOL_SHA256=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158
    RUNTIME_SHA256=00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444 ;;
  *) echo "no AppImage for $ARCH"; exit 1 ;;
esac
TOOL_VERSION=1.9.1
RUNTIME_VERSION=20251108

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fetch() {  # url sha256 destination
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}
fetch "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-$ARCH.AppImage" \
  "$TOOL_SHA256" "$WORK/appimagetool"
fetch "https://github.com/AppImage/type2-runtime/releases/download/$RUNTIME_VERSION/runtime-$ARCH" \
  "$RUNTIME_SHA256" "$WORK/runtime"
chmod +x "$WORK/appimagetool"

# The AppDir: the one-folder build under usr/lib, a launcher, a menu entry and the icon.
APPDIR="$WORK/Afterglow.AppDir"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a "$ROOT/dist/afterglow" "$APPDIR/usr/lib/afterglow"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/afterglow/afterglow" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/usr/share/applications/afterglow.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Afterglow
Comment=Set up a Logitech Harmony remote
Exec=afterglow
Icon=afterglow
Categories=Utility;
Terminal=false
EOF
cp "$ROOT/src/afterglow/branding/afterglow-icon.svg" \
   "$APPDIR/usr/share/icons/hicolor/scalable/apps/afterglow.svg"
ln -s usr/share/applications/afterglow.desktop "$APPDIR/afterglow.desktop"
ln -s usr/share/icons/hicolor/scalable/apps/afterglow.svg "$APPDIR/afterglow.svg"
ln -s afterglow.svg "$APPDIR/.DirIcon"

# appimagetool is itself an AppImage; a container has no FUSE to mount it with.
OUT="$ROOT/dist/afterglow-linux-$ARCH.AppImage"
ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 \
  "$WORK/appimagetool" --no-appstream --runtime-file "$WORK/runtime" "$APPDIR" "$OUT"
ls -l "$OUT"
