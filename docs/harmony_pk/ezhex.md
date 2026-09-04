# The `.ezhex` container

An `.ezhex` file is an XML header followed by an opaque payload.

    <?xml version="1.0"?>
    <INFORMATION>                    header, CRLF-terminated lines
      ...
    </INFORMATION>
    <payload bytes>                  everything after the closing tag

## Header

The header declares the payload's length and integrity, and identifies the remote the
configuration is for.

| Element | Meaning |
|---|---|
| `BINARYDATASIZE` | Length of the payload in bytes |
| `CHECKSUM` | One byte: `0x69` XOR-reduced over the whole payload |
| `INTENDEDVERSION` | Identifies the target remote; contains the skin and architecture |

`SKIN` 61 and `ARCH` 15 identify the Harmony 900. Writing a configuration to a remote
whose skin does not match is what leaves a device unusable, so the check belongs before
the transfer, not after.

### Line endings are load-bearing

Header lines end in a **single** CRLF. A doubled one is rejected. This is one of two
places in the format where a byte-level detail that looks cosmetic is not; the other is
the install scripts, in [configuration.md](configuration.md).

## Payload

The payload is not part of the container format. Its first bytes identify which layout it
uses, and the two seen so far are unrelated:

| Magic | Layout |
|---|---|
| `PK\x03\x04` | A ZIP archive of a filesystem tree - Harmony 900/1000/1100 |
| `GSPM` | An indexed configuration - Harmony One |

A container carrying a tree does not make two remotes compatible; it means only that both
happen to use a ZIP.

## Reproducing a payload byte for byte

For the ZIP layout the remote does not merely require a *valid* archive. It requires the
one Logitech's tooling would have produced, because the entries are extracted onto the
remote's filesystem and the archive carries the metadata that extraction depends on:

* entry order,
* per-entry Unix file modes,
* stored versus deflated per entry,
* Info-ZIP local extra fields.

Round-tripping content alone therefore is not enough. Reading a configuration has to
record this metadata alongside the files if writing one is ever to produce something the
remote accepts.
