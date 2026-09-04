# PyInstaller build spec.
#
#     pip install pyinstaller
#     pyinstaller packaging/afterglow.spec
#
# Two things about this project make a naive `pyinstaller afterglow.py` produce an
# executable that starts and can do nothing at all.
#
# ## The registries are deliberately dynamic
#
# `afterglow.backends` and `afterglow.payloads` discover their members with
# `pkgutil.iter_modules` and load them with `import_module`, so a remote or a container
# format can be deleted from the source tree and everything else keeps working - there is
# a test for exactly that (`tests/test_removability.py`). Nothing imports
# `backends.harmony_pk.backend` or `payloads.pk` by name.
#
# PyInstaller finds modules by reading `import` statements. It therefore bundles neither,
# and `iter_modules` has no directory to walk inside a one-file archive, so the frozen
# application ends up with **no backends and no payloads**: it cannot open an `.ezhex` and
# cannot build one. `hiddenimports` below is the whole fix, and it has to be extended when
# a backend or payload is added. Keeping the list here rather than importing the modules
# in `__init__` preserves the removability property in the source tree.
#
# ## The shipped data is found by looking, not by counting
#
# `paths.root()` walks up from the package looking for a directory that holds `library`,
# `scaffolds` and `icons`. In a frozen build it asks the bundler first (`sys._MEIPASS`),
# so those three have to arrive together and keep their names.
#
# Note what is *not* here: protocol definitions. The application ships none. Every
# protocol comes from the IrProto blocks of the configuration being imported, or is
# generated from an archive record.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH).parent          # noqa: F821 - PyInstaller injects SPECPATH
PACKAGE = PROJECT / "src" / "afterglow"

hiddenimports = [
    # Every backend and payload, because the registries load them by name at runtime.
    *collect_submodules("afterglow.backends"),
    *collect_submodules("afterglow.payloads"),
]

datas = [
    (str(PACKAGE / "library"), "afterglow/library"),
    (str(PACKAGE / "scaffolds"), "afterglow/scaffolds"),
    (str(PACKAGE / "icons"), "afterglow/icons"),
    (str(PACKAGE / "branding"), "afterglow/branding"),
    # The Linux USB-RNDIS helper, its udev rule and the rule installer. `paths` copies
    # the set out to the user's own folder on demand, because a script that needs `sudo`
    # cannot usefully live in a mode-700 extraction directory that vanishes on exit.
    (str(PACKAGE / "linux"), "afterglow/linux"),
]

# ## libconcord
#
# Reaching the remote needs libconcord, loaded by name through `ctypes` - which
# PyInstaller cannot see, so it is never bundled by accident. `concord._load()` looks in
# `sys._MEIPASS` first, so a copy placed here is found.
#
# **Whether to bundle it is a per-platform judgement, not a default.**
#
# On Linux it links against 35 shared libraries: libzip, libcurl - and through it OpenSSL,
# krb5, nghttp2/3, ngtcp2, brotli, libssh2, libidn2, libpsl - plus libhidapi, libusb and
# **libudev**. PyInstaller would follow and bundle that whole closure. Two of them make
# that a bad trade: libudev talks to the host's running udev and a mismatched copy breaks
# the USB enumeration this exists to do, and OpenSSL shipped inside an application is a
# security-update problem the distribution otherwise solves. Ask for the distribution or
# AUR package instead; `concord.NotAvailable` already explains how, and everything except
# reading and writing the remote works without it.
#
# On Windows there is no package manager to defer to, so bundling `libconcord-6.dll` and
# its MinGW dependencies is the only practical route.
#
# Set `AFTERGLOW_BUNDLE_LIBCONCORD` to the library file to include it.
binaries = []
_libconcord = os.environ.get("AFTERGLOW_BUNDLE_LIBCONCORD")
if _libconcord:
    source = Path(_libconcord).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"AFTERGLOW_BUNDLE_LIBCONCORD is not a file: {source}")
    binaries.append((str(source), "."))

analysis = Analysis(                      # noqa: F821
    # NOT `afterglow.py`: PyInstaller puts the entry script in the extraction
    # directory and on `sys.path`, where a script named after the package shadows it -
    # `from afterglow import backends` then fails with "cannot import name".
    [str(PROJECT / "packaging" / "main.py")],
    pathex=[str(PROJECT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # The archive converter and the probe analyser are developer tools, not part of the
    # application, and pulling their dependencies in would grow the bundle for nothing.
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)                  # noqa: F821

exe = EXE(                                # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="afterglow",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    # The executable's own icon, as Explorer and the taskbar show it. Separate from the
    # window icon the application sets at runtime: this one is read from the file on
    # disk, before any of our code runs. PyInstaller ignores it off Windows.
    icon=str(PACKAGE / "branding" / "afterglow.ico"),
)
