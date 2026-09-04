# Identifying a remote

Every configuration declares which remote it is for, and every remote reports the same
identity over USB. Writing a configuration to a remote whose identity does not match is
the one operation that can leave hardware unusable, so the two are compared before any
transfer.

## Where the identity comes from

Out of the container header's `<INTENDEDVERSION>` block for a file, and from
libconcord's `get_identity` for an attached remote. They carry the same fields:

| Field | Source in the header | Meaning |
|---|---|---|
| `arch` | `<PROTOCOL>` | Architecture family |
| `skin` | `<SKIN>` | Model id |
| `flash` | | Flash chip identifier |
| `board` | | Board revision |

The Harmony 900 is `arch` 15, `skin` 61.

## The skin table

`library/remotes/models.json` maps skin id to model name and manufacturer. The table is
taken from Concordance's `libconcord/remote_info.h` (GPL-3.0) and covers far more remotes
than this project supports - it exists so that an unrecognised remote can be *named* in an
error message rather than reported as a bare number.

Being in that table is not a claim of support.

## Profile status

A remote is only usable for building if a profile ships for it, and profiles carry a
status:

| Status | Meaning |
|---|---|
| verified | A configuration has been written to one and it booted |
| untested | The identity is known, but nothing has ever been written to one |

An `untested` profile can read and inspect; writing is refused. A configuration that is
wrong on a remote nobody has tested means bricking hardware that can no longer be
recovered from a vendor server, so the default is no.

**Only the Harmony 900 is verified.** The 1000 and 1100 store configurations the same way
and have donor evidence, but neither has been flashed. The 880, 890 and 76x use a
different architecture and nothing in these documents applies to them.

## Adding a remote

A profile is data, not code: a JSON file in `library/remotes/`. What is genuinely
required before marking one verified is a real flash and boot, not a clean build - a
configuration that assembles proves nothing about whether the remote will accept it.
