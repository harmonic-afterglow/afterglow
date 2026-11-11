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

# libconcord's closure reaches Heimdal Kerberos (libcurl -> LDAP -> SASL -> GSSAPI), which
# needs libcrypt.so.1. PyInstaller leaves libcrypt out as part of glibc, but systems on
# libxcrypt have only libcrypt.so.2 - Arch without libxcrypt-compat - and the bundled
# libconcord would not load there. So it is bundled, copied out under its SONAME.
rm -rf /tmp/bundle-extra && mkdir -p /tmp/bundle-extra
cp -L "$(ldconfig -p | awk '$1 == "libcrypt.so.1" {print $NF; exit}')" \
  /tmp/bundle-extra/libcrypt.so.1

AFTERGLOW_BUNDLE_LIBCONCORD=/tmp/libconcord-install/lib/libconcord.so.6.0.0 \
AFTERGLOW_BUNDLE_EXTRA=/tmp/bundle-extra/libcrypt.so.1 \
  pyinstaller --noconfirm packaging/afterglow.spec

# Everything libconcord loads, followed through the bundle, is in the bundle or is glibc's
# own: a library left to "the system" that a system may lack is how libcrypt.so.1 broke
# the bundle on Arch, reported as "libconcord was not found".
python3 - dist/afterglow <<'CLOSURE'
import pathlib, re, subprocess, sys
root = next(pathlib.Path(sys.argv[1]).rglob("libconcord.so*")).parent
glibc = re.compile(r"^(libc|libm|libdl|libpthread|librt|libresolv|libutil|libanl|"
                   r"ld-linux[-\w]*)\.so")
seen, todo, missing = set(), [next(root.glob("libconcord.so*")).name], []
while todo:
    name = todo.pop()
    if name in seen:
        continue
    seen.add(name)
    if glibc.match(name):
        continue
    path = root / name
    if not path.exists():
        missing.append(name)
        continue
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    todo += re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)
if missing:
    sys.exit(f"libconcord needs what the bundle lacks: {', '.join(sorted(missing))}")
print(f"libconcord's closure is bundled: {len(seen)} libraries")
CLOSURE

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
