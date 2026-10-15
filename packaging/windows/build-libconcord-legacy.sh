#!/usr/bin/env bash
# Cross-compile libconcord for the legacy Windows build (Windows 7 SP1 and later).
#
#     packaging/windows/build-libconcord-legacy.sh i686|x86_64 <output dir>
#
# Runs on Ubuntu 22.04 (the bundle workflow runs it in that container; locally,
# `podman run --rm -v "$PWD:/src" -w /src ubuntu:22.04 packaging/windows/...`).
#
# ## Why not MSYS2, like the regular Windows build
#
# MSYS2 dropped Windows 7 and 8.0 in 2023 and has stopped building 32-bit packages, so
# its libusb, hidapi, libzip and curl are neither 32-bit nor safe to load on 7: anything
# rebuilt since may call a Windows 8 function, and the DLL then refuses to load with
# "The procedure entry point ... could not be located". So here every dependency is built
# from a pinned source release with `_WIN32_WINNT=0x0601` (Windows 7), and linked
# **statically** into a single `libconcord-6.dll`. Only Windows' own DLLs are left to
# import, which `win7check.py` then checks one by one.
#
# Ubuntu 22.04's mingw-w64 uses the win32 thread model, and libconcord starts no threads,
# but its USB link times things with `clock_gettime`, which MinGW keeps in
# libwinpthread - so that is linked in statically as well.
set -euo pipefail

ARCH="${1:?usage: $0 i686|x86_64 <output dir>}"
OUT="$(mkdir -p "${2:?usage: $0 i686|x86_64 <output dir>}" && cd "$2" && pwd)"
HOST="${ARCH}-w64-mingw32"
HERE="$(cd "$(dirname "$0")" && pwd)"
CONCORDANCE_REPO="${CONCORDANCE_REPO:-https://github.com/harmonic-afterglow/concordance}"
CONCORDANCE_REF="${CONCORDANCE_REF:-usbnet-link}"
WORK="${WORK:-/tmp/libconcord-legacy-$ARCH}"
PREFIX="$WORK/prefix"
JOBS="$(nproc)"

# name|version|url|sha256
SOURCES=(
  "zlib|1.3.2|https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.gz|bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16"
  "libusb|1.0.30|https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2|fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf"
  "hidapi|0.15.0|https://github.com/libusb/hidapi/archive/refs/tags/hidapi-0.15.0.tar.gz|5d84dec684c27b97b921d2f3b73218cb773cf4ea915caee317ac8fc73cef8136"
  "libzip|1.12.1|https://github.com/nih-at/libzip/releases/download/v1.12.1/libzip-1.12.1.tar.xz|c40062022a1963c80573d48f6070792297cecd7c6bffe3aefcac0d8b9bee8913"
  "curl|8.23.0|https://curl.se/download/curl-8.23.0.tar.xz|8dadd7d2536a314f982ad05a651b713f426bf7d02cc2c76cffb9796f2218e6c5"
)

if [ "$(id -u)" = 0 ] && command -v apt-get > /dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates curl xz-utils bzip2 git make cmake pkg-config \
    autoconf automake libtool \
    gcc-mingw-w64-i686 g++-mingw-w64-i686 gcc-mingw-w64-x86-64 > /dev/null
fi

# Windows 7 feature level for every header, and the GCC runtime linked in statically.
export CPPFLAGS="-D_WIN32_WINNT=0x0601 -DWINVER=0x0601 -I$PREFIX/include"
export CFLAGS="-O2"
export CXXFLAGS="-O2 -std=c++11"
export LDFLAGS="-L$PREFIX/lib -static-libgcc -static-libstdc++"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

mkdir -p "$WORK/src" "$PREFIX"
cat > "$WORK/toolchain.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_C_COMPILER ${HOST}-gcc)
set(CMAKE_CXX_COMPILER ${HOST}-g++)
set(CMAKE_RC_COMPILER ${HOST}-windres)
set(CMAKE_FIND_ROOT_PATH ${PREFIX} /usr/${HOST})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF
CMAKE=(cmake -G "Unix Makefiles" -DCMAKE_TOOLCHAIN_FILE="$WORK/toolchain.cmake"
       -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release
       -DBUILD_SHARED_LIBS=OFF -DCMAKE_C_FLAGS="$CPPFLAGS $CFLAGS")

fetch() {  # name -> unpacked source directory on stdout
  local entry name version url sum file
  for entry in "${SOURCES[@]}"; do
    IFS='|' read -r name version url sum <<< "$entry"
    [ "$name" = "$1" ] || continue
    file="$WORK/src/$(basename "$url")"
    [ -f "$file" ] || curl -fsSL --retry 3 -o "$file" "$url"
    echo "$sum  $file" | sha256sum -c --quiet - >&2
    rm -rf "$WORK/src/$name"; mkdir "$WORK/src/$name"
    tar -xf "$file" -C "$WORK/src/$name" --strip-components=1
    echo "$WORK/src/$name"
    return
  done
  echo "no source named $1" >&2; exit 1
}

echo "== zlib"
src="$(fetch zlib)"
"${CMAKE[@]}" -S "$src" -B "$src/build" -DZLIB_BUILD_SHARED=OFF -DZLIB_BUILD_TESTING=OFF \
  > /dev/null
cmake --build "$src/build" -j"$JOBS" > /dev/null
cmake --install "$src/build" > /dev/null
# zlib names its static archive differently by version and generator; libzip and curl
# look for libz.a.
for candidate in "$PREFIX"/lib/libzs.a "$PREFIX"/lib/libzlibstatic.a; do
  [ -f "$candidate" ] && [ ! -f "$PREFIX/lib/libz.a" ] && cp "$candidate" "$PREFIX/lib/libz.a"
done
rm -f "$PREFIX"/lib/libz.dll.a "$PREFIX"/lib/libzlib.dll.a "$PREFIX"/bin/*.dll

echo "== libusb"
src="$(fetch libusb)"
(cd "$src" && ./configure --host="$HOST" --prefix="$PREFIX" --enable-static \
   --disable-shared --disable-examples-build --disable-tests-build > /dev/null \
 && make -j"$JOBS" > /dev/null && make install > /dev/null)

echo "== hidapi"
src="$(fetch hidapi)"
"${CMAKE[@]}" -S "$src" -B "$src/build" -DHIDAPI_BUILD_HIDTEST=OFF > /dev/null
cmake --build "$src/build" -j"$JOBS" > /dev/null
cmake --install "$src/build" > /dev/null
# libconcord's configure checks for `-lhidapi`.
[ -f "$PREFIX/lib/libhidapi.a" ] || cp "$PREFIX"/lib/libhidapi*.a "$PREFIX/lib/libhidapi.a"

echo "== libzip"
src="$(fetch libzip)"
# Only deflate: the remotes' archives use nothing else, and every optional codec or
# crypto backend is one more library to vet for Windows 7.
# Ubuntu 22.04's mingw-w64 headers predate `DWORD_MAX`, which libzip uses.
"${CMAKE[@]}" -S "$src" -B "$src/build" \
  -DCMAKE_C_FLAGS="$CPPFLAGS $CFLAGS -DDWORD_MAX=0xffffffffUL" \
  -DENABLE_COMMONCRYPTO=OFF -DENABLE_GNUTLS=OFF -DENABLE_MBEDTLS=OFF \
  -DENABLE_OPENSSL=OFF -DENABLE_WINDOWS_CRYPTO=OFF -DENABLE_BZIP2=OFF \
  -DENABLE_LZMA=OFF -DENABLE_ZSTD=OFF -DBUILD_TOOLS=OFF -DBUILD_REGRESS=OFF \
  -DBUILD_OSSFUZZ=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOC=OFF \
  -DZLIB_LIBRARY="$PREFIX/lib/libz.a" -DZLIB_INCLUDE_DIR="$PREFIX/include" > /dev/null
cmake --build "$src/build" -j"$JOBS" > /dev/null
cmake --install "$src/build" > /dev/null

echo "== curl"
src="$(fetch curl)"
# libconcord only posts to a web address, which nothing in Afterglow calls; it still
# has to link. HTTP(S) over Windows' own TLS (Schannel), nothing else.
(cd "$src" && ./configure --host="$HOST" --prefix="$PREFIX" --enable-static \
   --disable-shared --with-schannel --without-libpsl --without-brotli --without-zstd \
   --without-nghttp2 --without-libidn2 --without-libssh2 --disable-ldap \
   --disable-ldaps --disable-rtsp --disable-dict --disable-telnet --disable-tftp \
   --disable-pop3 --disable-imap --disable-smb --disable-smtp --disable-gopher \
   --disable-mqtt --disable-ftp --disable-file --disable-manual --disable-docs \
   --with-zlib="$PREFIX" > /dev/null \
 && make -j"$JOBS" > /dev/null && make install > /dev/null)

echo "== libconcord"
rm -rf "$WORK/concordance"
git clone -q --depth 1 --branch "$CONCORDANCE_REF" "$CONCORDANCE_REPO" "$WORK/concordance"
git -C "$WORK/concordance" rev-parse HEAD > "$OUT/libconcord-commit"
cd "$WORK/concordance/libconcord"
mkdir -p m4
autoreconf --install --force > /dev/null 2>&1
# libtool will not put a static archive into a DLL on Windows unless told the check is
# not needed (`pass_all`): it would drop them and build no DLL at all. The static
# libraries' own Windows dependencies go in LIBS, since nothing else names them.
# The static GCC runtime goes on the compiler itself: libtool drops `-static-libgcc` and
# `-static-libstdc++` from LDFLAGS without a word, and the DLL then needs
# libgcc_s_dw2-1.dll and libstdc++-6.dll beside it. libtool also adds its own
# `-lstdc++` for a C++ library, which `-static-libstdc++` cannot reach, so the static
# archive is named first in LIBS and leaves that one nothing to resolve.
lt_cv_deplibs_check_method=pass_all \
CC="${HOST}-gcc -static-libgcc" CXX="${HOST}-g++ -static-libgcc -static-libstdc++" \
CPPFLAGS="$CPPFLAGS -DCURL_STATICLIB -DZIP_STATIC" \
LIBS="$("${HOST}-g++" -print-file-name=libstdc++.a) /usr/$HOST/lib/libwinpthread.a -lz -lsetupapi -lhid -lcfgmgr32 -lws2_32 -lcrypt32 -lbcrypt -lsecur32 -liphlpapi -ladvapi32" \
  ./configure --host="$HOST" --prefix="$WORK/libconcord-install" --disable-static \
  --enable-shared --disable-mime-update --with-usbnet-link=yes | tee "$WORK/configure.log" \
  > /dev/null
grep -q "over USB (libusb-1.0): yes" "$WORK/configure.log"
make -j"$JOBS" > /dev/null
make install > /dev/null

cp "$WORK/libconcord-install/bin/libconcord-6.dll" "$OUT/"
"${HOST}-strip" --strip-unneeded "$OUT/libconcord-6.dll"
echo "built $OUT/libconcord-6.dll from $(cat "$OUT/libconcord-commit")"
"${HOST}-objdump" -p "$OUT/libconcord-6.dll" | grep "DLL Name" | sort -u

# The WinUSB helper, both architectures whatever ARCH is: a 32-bit Afterglow on 64-bit
# Windows 7 has to run the 64-bit one, since Windows refuses device installation from
# a 32-bit process there. See afterglow-winusb.c.
helper="$HERE/afterglow-winusb.c"
for target in i686:x86 x86_64:x64; do
  "${target%%:*}-w64-mingw32-gcc" -O2 -municode -static -D_WIN32_WINNT=0x0601 \
    -o "$OUT/afterglow-winusb-${target##*:}.exe" "$helper" -lsetupapi -lnewdev -lcfgmgr32
  "${target%%:*}-w64-mingw32-strip" "$OUT/afterglow-winusb-${target##*:}.exe"
done
ls -l "$OUT"
