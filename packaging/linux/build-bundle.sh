#!/usr/bin/env bash
# Build the Linux AppImage on Ubuntu 20.04, so it runs there and on anything newer -
# for the machine's own architecture, x86_64 or aarch64.
#
# A bundle carries the system libraries of the machine it was built on, and those set
# its floor: built on Ubuntu 24.04 it needed glibc 2.38, and Ubuntu 22.04, Debian 12
# and Mint 21 could not start it. This runs inside an `ubuntu:20.04` container (glibc
# 2.31) - from CI, or locally:
#
#   podman run --rm -v "$PWD:/src" -w /src ubuntu:20.04 packaging/linux/build-bundle.sh
#
# Python is not the system's 3.8: uv installs a standalone 3.13 (glibc 2.17 and up).
# PyQt6 is 6.7.1, as on macOS: the last release whose aarch64 wheels need glibc 2.28,
# below 20.04's. Later ones need 2.39 there, which Ubuntu 22.04 and Debian 12 lack.
set -euxo pipefail
: "${CONCORDANCE_REPO:=https://github.com/harmonic-afterglow/concordance}"
: "${CONCORDANCE_REF:=usbnet-link}"
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl file git build-essential autoconf automake libtool pkg-config binutils \
  python3-pip \
  libusb-1.0-0-dev libzip-dev libcurl4-openssl-dev libhidapi-dev \
  libegl1 libgl1 libdbus-1-3 libfontconfig1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1

# libconcord from Afterglow's fork
rm -rf /tmp/concordance /tmp/libconcord-install
git clone --depth 1 --branch "$CONCORDANCE_REF" "$CONCORDANCE_REPO" /tmp/concordance
git -C /tmp/concordance rev-parse HEAD > /tmp/libconcord-commit
(cd /tmp/concordance/libconcord \
  && autoreconf --install --force \
  && ./configure --prefix=/tmp/libconcord-install \
  && make -j"$(nproc)" && make install)

# Python 3.13 and the application
python3 -m pip install --quiet "uv==0.9.*"
uv python install 3.13
rm -rf /tmp/venv
uv venv --python 3.13 /tmp/venv
. /tmp/venv/bin/activate
uv pip install -e ".[gui]" "PyQt6==6.7.1" pyinstaller

AFTERGLOW_BUNDLE_LIBCONCORD=/tmp/libconcord-install/lib/libconcord.so.6.0.0 \
  pyinstaller --noconfirm packaging/afterglow.spec

packaging/linux/build-appimage.sh

# What it needs of the system - the newest glibc symbol any bundled file asks for - and
# that the AppImage starts and finds libconcord without one. A container has no FUSE,
# so it runs extracted, as on a system without it.
ldd_max() { find "$1" -type f \( -name '*.so*' -o -perm -u+x \) -exec strings -a {} + \
  | grep -o 'GLIBC_2\.[0-9]*' | sort -t. -k2 -n | tail -1; }
echo "the bundle needs $(ldd_max dist/afterglow)"
APPIMAGE="$PWD/dist/afterglow-linux-$(uname -m).AppImage"
cd /tmp
env -i HOME="$HOME" PATH=/usr/bin:/bin "$APPIMAGE" --appimage-extract-and-run --self-check
env -i HOME="$HOME" PATH=/usr/bin:/bin "$APPIMAGE" --appimage-extract-and-run --concord-check
