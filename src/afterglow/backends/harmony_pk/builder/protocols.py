"""Resolve Harmony PK IrProto blocks and their runtime indexes.

Each command names its protocol by content-addressed block ID. The *index* it transmits
(the Code's first byte and XML ``Protocol`` value) is positional and therefore a
build-time decision, never part of a device's identity. Older Afterglow records assigned
one block to a whole device; that remains a read-side fallback, but the native format is
per command and mixed-protocol devices must stay mixed.

A fresh IrProto is assembled from the distinct blocks the commands use, with NEC forced
to index 0 so NEC codes keep byte0 = 00.
"""
from .codes import SYNTHESIZABLE_PROTOCOLS

NEC_ID = "a7b8a0e6c639"
SAMSUNG_ID = "e8f716b9ee19"
# Old project files stored runtime indexes as the protocol. Accept them as a migration
# convenience only; the index is never the block's identity.
LEGACY_PROTOCOLS = {0: NEC_ID, 1: SAMSUNG_ID}


def _canonical_block(reference, spec):
    if isinstance(reference, int):
        try:
            return LEGACY_PROTOCOLS[reference]
        except KeyError as exc:
            raise ValueError(
                f"Device {spec.get('label', spec.get('id', '?'))!r} uses unsupported "
                f"legacy protocol index {reference}.") from exc
    if not isinstance(reference, str) or len(reference) != 12:
        raise ValueError(
            f"Device {spec.get('label', spec.get('id', '?'))!r} has invalid protocol "
            f"block ID {reference!r}.")
    return reference


def validate(specs):
    """Check every command names a usable block and record the resolved mapping.

    A donor-only block cannot have its commands generated, so such a device must bring
    real captured codes; refusing here is what stops us shipping plausible-but-wrong IR.
    """
    for spec in specs:
        from .. import ssir
        raw_codes = spec.get("raw_codes") or {}
        explicit = spec.get("command_protocols") or {}
        command_names = list(dict.fromkeys(
            [command[0] for command in spec.get("commands") or []] + list(raw_codes)))
        unknown = set(explicit) - set(command_names)
        if unknown:
            raise ValueError(
                f"Device {spec.get('label', spec.get('id', '?'))!r} assigns protocols "
                f"to unknown commands: {', '.join(sorted(unknown))}")

        resolved = {}
        for name in command_names:
            code = raw_codes.get(name)
            if code and ssir.is_raw(code):
                resolved[name] = None
                continue
            if code and name not in explicit and spec.get("protocol") is None:
                raise ValueError(
                    f"Command {name!r} on device "
                    f"{spec.get('label', spec.get('id', '?'))!r} has a native Code but "
                    "no known protocol block. Import it again from the configuration "
                    "that contains the block.")

            reference = explicit.get(name, spec.get("protocol", NEC_ID))
            if reference is None:
                if code:
                    raise ValueError(
                        f"Command {name!r} on device "
                        f"{spec.get('label', spec.get('id', '?'))!r} has a native Code "
                        "but no known protocol block. Import it again from the "
                        "configuration that contains the block.")
                raise ValueError(
                    f"Command {name!r} on device "
                    f"{spec.get('label', spec.get('id', '?'))!r} has no protocol block")
            block_id = _canonical_block(reference, spec)
            # Non-synthesizable blocks need their real per-command native Code. We do
            # not know how to manufacture arbitrary command framing from table cells.
            if SYNTHESIZABLE_PROTOCOLS.get(block_id) is None and not code:
                raise ValueError(
                    f"Protocol block {block_id} is donor-only: command {name!r} on "
                    f"device {spec.get('label', spec.get('id', '?'))!r} must supply its "
                    "raw Code (its command framing can't be generated).")
            resolved[name] = block_id

        spec["_command_block_ids"] = resolved
        distinct = {block_id for block_id in resolved.values() if block_id is not None}
        # Compatibility for code that only asks whether this is a single-block device.
        spec["_block_id"] = next(iter(distinct)) if len(distinct) == 1 else None


def resolve(specs):
    """Assign each command its runtime protocol index, and return the block order.

    Every config assembles a fresh IrProto from the library: NEC is forced to index 0 so
    NEC codes keep byte0 = 00, and the rest follow in first-use order. Blocks are
    generated at the position they will occupy (see this backend's protocol_json module),
    which is exact for every protocol in the catalogue, so an existing config's IrProto
    never has to be preserved verbatim.
    """
    block_order = []
    for spec in specs:
        for block_id in spec["_command_block_ids"].values():
            if block_id is not None and block_id not in block_order:
                block_order.append(block_id)
    if NEC_ID in block_order:
        block_order.remove(NEC_ID)
        block_order.insert(0, NEC_ID)
    if len(block_order) > 0x100:
        raise ValueError("Harmony PK Codes can address at most 256 protocol blocks")
    index_of = {block_id: i for i, block_id in enumerate(block_order)}
    for spec in specs:
        spec["_command_proto_idx"] = {
            name: index_of[block_id]
            for name, block_id in spec["_command_block_ids"].items()
            if block_id is not None
        }
        # Read-side compatibility for older helpers and tests. A mixed device has no
        # meaningful device-wide index, so zero is only a harmless placeholder there.
        spec["_proto_idx"] = index_of.get(spec["_block_id"], 0)
    return block_order
