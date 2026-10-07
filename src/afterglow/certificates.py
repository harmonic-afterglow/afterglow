"""HTTPS downloads trust what the operating system trusts.

Python's `ssl` verifies against OpenSSL's own certificate file, not the system's store.
The python.org interpreter the macOS app is built from ships none - its installer runs a
separate "Install Certificates" step - so inside the bundle every download failed with
CERTIFICATE_VERIFY_FAILED. `truststore` hands verification to the system instead: the
Keychain on macOS, the certificate store on Windows, the distribution's bundle on Linux.

Optional, like everything third-party outside the interface: without it Python's own
behaviour is unchanged, which is what a source checkout on Linux has always had.
"""
from __future__ import annotations


def use_system_store() -> bool:
    """Verify HTTPS against the system's certificates. False when that is not available."""
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True
