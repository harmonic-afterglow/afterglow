#!/usr/bin/env bash
# Build libconcord for a macOS bundle, for a chosen oldest macOS.
#
#     packaging/macos/build-libconcord.sh <oldest macOS, e.g. 10.13 or 11.0> <output dir>
#
# Needs Xcode's command line tools, cmake, and autoconf/automake/libtool/pkg-config (from
# Homebrew - they only run during the build, nothing of theirs ends up in the result).
#
# ## Why not Homebrew's libraries
#
# The first macOS bundles linked libconcord against Homebrew's libusb, hidapi and libzip.
# Homebrew builds every bottle for the macOS it was poured on, and libzip pulled in zstd
# built the same way: the "macOS 11" bundle carried libraries marked for 14 and 15, and
# would not start on anything older. So here each dependency is built from a pinned
# source release with `MACOSX_DEPLOYMENT_TARGET` set, and linked **statically** into one
# `libconcord.6.dylib`. zlib and curl are the system's own, which every macOS has.
# `minos.py` then checks the finished app, file by file.
set -euo pipefail

TARGET="${1:?usage: $0 <oldest macOS> <output dir>}"
OUT="$(mkdir -p "${2:?usage: $0 <oldest macOS> <output dir>}" && cd "$2" && pwd)"
CONCORDANCE_REPO="${CONCORDANCE_REPO:-https://github.com/harmonic-afterglow/concordance}"
CONCORDANCE_REF="${CONCORDANCE_REF:-usbnet-link}"
WORK="${WORK:-/tmp/libconcord-macos-$TARGET}"
PREFIX="$WORK/prefix"
JOBS="$(sysctl -n hw.ncpu)"

# name|version|url|sha256 - the same releases as the legacy Windows build.
SOURCES=(
  "libusb|1.0.30|https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2|fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf"
  "hidapi|0.15.0|https://github.com/libusb/hidapi/archive/refs/tags/hidapi-0.15.0.tar.gz|5d84dec684c27b97b921d2f3b73218cb773cf4ea915caee317ac8fc73cef8136"
  "libzip|1.12.1|https://github.com/nih-at/libzip/releases/download/v1.12.1/libzip-1.12.1.tar.xz|c40062022a1963c80573d48f6070792297cecd7c6bffe3aefcac0d8b9bee8913"
)

export MACOSX_DEPLOYMENT_TARGET="$TARGET"
export CPPFLAGS="-I$PREFIX/include"
export CFLAGS="-O2 -mmacosx-version-min=$TARGET"
export CXXFLAGS="-O2 -std=c++11 -mmacosx-version-min=$TARGET"
export LDFLAGS="-L$PREFIX/lib -mmacosx-version-min=$TARGET"
# Only our own .pc files: Homebrew's would quietly bring its libraries back.
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

mkdir -p "$WORK/src" "$PREFIX"
CMAKE=(cmake -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release
       -DBUILD_SHARED_LIBS=OFF -DCMAKE_OSX_DEPLOYMENT_TARGET="$TARGET"
       -DCMAKE_PREFIX_PATH="$PREFIX" -DCMAKE_FIND_FRAMEWORK=LAST
       -DCMAKE_IGNORE_PREFIX_PATH="/opt/homebrew;/usr/local")

fetch() {  # name -> unpacked source directory on stdout
  local entry name version url sum file
  for entry in "${SOURCES[@]}"; do
    IFS='|' read -r name version url sum <<< "$entry"
    [ "$name" = "$1" ] || continue
    file="$WORK/src/$(basename "$url")"
    [ -f "$file" ] || curl -fsSL --retry 3 -o "$file" "$url"
    echo "$sum  $file" | shasum -a 256 -c --quiet - >&2
    rm -rf "${WORK:?}/src/$name"; mkdir "$WORK/src/$name"
    tar -xf "$file" -C "$WORK/src/$name" --strip-components=1
    echo "$WORK/src/$name"
    return
  done
  echo "no source named $1" >&2; exit 1
}

echo "== libusb"
src="$(fetch libusb)"
(cd "$src" && ./configure --prefix="$PREFIX" --enable-static --disable-shared \
   --disable-examples-build --disable-tests-build > /dev/null \
 && make -j"$JOBS" > /dev/null && make install > /dev/null)

echo "== hidapi"
src="$(fetch hidapi)"
"${CMAKE[@]}" -S "$src" -B "$src/build" -DHIDAPI_BUILD_HIDTEST=OFF > /dev/null
cmake --build "$src/build" -j"$JOBS" > /dev/null
cmake --install "$src/build" > /dev/null
[ -f "$PREFIX/lib/libhidapi.a" ]

echo "== libzip"
src="$(fetch libzip)"
# Only deflate, against the system zlib: the remotes' archives use nothing else.
"${CMAKE[@]}" -S "$src" -B "$src/build" \
  -DENABLE_COMMONCRYPTO=OFF -DENABLE_GNUTLS=OFF -DENABLE_MBEDTLS=OFF \
  -DENABLE_OPENSSL=OFF -DENABLE_WINDOWS_CRYPTO=OFF -DENABLE_BZIP2=OFF \
  -DENABLE_LZMA=OFF -DENABLE_ZSTD=OFF -DBUILD_TOOLS=OFF -DBUILD_REGRESS=OFF \
  -DBUILD_OSSFUZZ=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOC=OFF > /dev/null
cmake --build "$src/build" -j"$JOBS" > /dev/null
cmake --install "$src/build" > /dev/null

echo "== libconcord"
rm -rf "$WORK/concordance"
git clone -q --depth 1 --branch "$CONCORDANCE_REF" "$CONCORDANCE_REPO" "$WORK/concordance"
git -C "$WORK/concordance" rev-parse HEAD > "$OUT/libconcord-commit"
cd "$WORK/concordance/libconcord"
mkdir -p m4
autoreconf --install --force > /dev/null 2>&1
# The system curl has no .pc file to find, so it is named directly - and CURL_CFLAGS
# must not be empty, or configure takes it as unset and asks pkg-config anyway. The
# static libraries' frameworks go in LIBS, since a non-static pkg-config query leaves
# them out.
CURL_CFLAGS="-DAFTERGLOW_SYSTEM_CURL" CURL_LIBS="-lcurl" \
LIBS="-lz -framework IOKit -framework CoreFoundation -framework Security -framework AppKit" \
  ./configure --prefix="$WORK/libconcord-install" --disable-static --enable-shared \
  --disable-mime-update --with-usbnet-link=yes | tee "$WORK/configure.log" > /dev/null
grep -q "over USB (libusb-1.0): yes" "$WORK/configure.log"
make -j"$JOBS" > /dev/null
make install > /dev/null

cp "$WORK/libconcord-install/lib/libconcord.6.dylib" "$OUT/"
# Its own install name, so PyInstaller does not go looking for the build directory.
install_name_tool -id "@rpath/libconcord.6.dylib" "$OUT/libconcord.6.dylib"
# Changing it voids the ad-hoc signature, and arm64 will not load unsigned code.
codesign --force --sign - "$OUT/libconcord.6.dylib"
echo "built $OUT/libconcord.6.dylib from $(cat "$OUT/libconcord-commit")"
otool -L "$OUT/libconcord.6.dylib"
if otool -L "$OUT/libconcord.6.dylib" | tail -n +2 \
     | grep -vE "^[[:space:]]+(/usr/lib/|/System/Library/|@rpath/libconcord)"; then
  echo "libconcord links something that is not part of macOS"; exit 1
fi
