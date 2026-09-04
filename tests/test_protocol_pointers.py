"""A protocol block moves, and only its pointers may move with it.

Each block is generated at the position it will occupy, and a few 16-bit fields inside it
hold absolute positions that have to be rewritten when it lands somewhere else. Which
fields those are is a property of the protocol, measured by finding the same block in two
configurations at different positions and seeing which bytes differ by the gap.

For four protocols that was never done. Their fields were copied from the NEC block and
flagged `"pointers": "assumed"`, and five of NEC's seven are ordinary data in a 36.2 kHz
block. Relocating it therefore rewrote real bytes: a zero at offset 23 became 65489, a
30 at offset 9 became 65519. The configuration built, verified and flashed - and the
remote froze and rebooted the moment a device using that protocol transmitted.

The check that catches it is cheap: a field called a pointer has to end up pointing into
its own block. If it does not, it was never a pointer.
"""
import struct

import pytest

from afterglow.backends.harmony_pk import protocol_json


def specs():
    return protocol_json.catalog()


@pytest.mark.parametrize("block_id", sorted(specs()))
def test_declared_pointers_point_into_the_block(block_id):
    """At several positions, not just one - a wrong field can look right at the position
    the block happened to be measured at."""
    spec = specs()[block_id]
    for position in (10, 64, 160, 512):
        block = protocol_json.block(block_id, position)
        for offset in spec.get("pointer_fields") or ():
            if offset + 1 >= len(block):
                continue
            value = struct.unpack_from("<H", block, offset)[0]
            assert position <= value <= position + len(block), (
                f"{block_id}: offset {offset} holds {value} with the block at "
                f"{position}-{position + len(block)}; that is data, not a pointer, and "
                "relocating it corrupts the block")


@pytest.mark.parametrize("block_id", sorted(specs()))
def test_moving_a_block_changes_nothing_but_its_pointers(block_id):
    """The whole contract. Anything else that changes is data being rewritten."""
    here = protocol_json.block(block_id, 64)
    there = protocol_json.block(block_id, 160)
    changed = {i for i in range(len(here)) if here[i] != there[i]}
    allowed = set()
    for offset in specs()[block_id].get("pointer_fields") or ():
        allowed |= {offset, offset + 1}
    assert changed <= allowed, (
        f"{block_id}: moving it rewrote {sorted(changed - allowed)}, which are not "
        "pointer fields")


def test_a_block_that_lies_about_its_pointers_is_refused():
    """The guard itself, since every shipped protocol now passes it."""
    spec = dict(specs()["a7b8a0e6c639"])
    spec["pointer_fields"] = list(spec["pointer_fields"]) + [30]
    with pytest.raises(ValueError, match="not a pointer|do not point"):
        protocol_json.encode(spec, 160)


def test_the_generated_rc6_block_has_the_fields_the_donors_agree_on():
    """Both formerly duplicated donor entries moved only fields 7, 19 and 21."""
    assert list(protocol_json.pointer_fields("6bd42e0eea79")) == [7, 19, 21]
    assert "bfd45b094543" not in specs()


def test_no_protocol_still_claims_the_nec_fields_by_assumption():
    """Copying one protocol's layout onto another is what caused this."""
    for block_id, spec in specs().items():
        if spec.get("pointers") == "assumed":
            pytest.fail(f"{block_id} still has assumed pointer fields")


def test_importer_and_vm_agree_on_which_blocks_are_usable(configs):
    """A checker must not be stricter than the runtime it models.

    Two failures this guards, both found in a real configuration:

    * block 4 of `my-remote.ezhex` was refused for carrying a non-zero alphabet pointer
      on an element with a zero-size alphabet, while all 40 of its commands execute
      cleanly in `ir_vm`. An element that reads no symbols never dereferences that
      pointer, so it is vestigial; it is now nulled rather than treated as fatal.
    * one unusable block aborted the entire import, so a seven-block config yielded
      nothing instead of six working devices - the strict policy applied to the small
      failure and the lenient one to the large.

    The assertion is the invariant, not the specific blocks: every block the VM can run
    must materialize, and a block it cannot run may be refused but must not raise.
    """
    import contextlib
    import io
    import collections
    import tempfile
    import xml.etree.ElementTree as ET
    from pathlib import Path as _Path

    from afterglow import ezhex
    from afterglow.backends.harmony_pk import importer, irproto, ir_vm, protocol_json

    checked = 0
    for config in configs:
        tree = _Path(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            ezhex.unpack(str(config), str(tree))
        proto = tree / "userconfig" / "IrProto.bin"
        xml = tree / "userconfig" / "UserConfiguration.xml"
        if not proto.is_file() or not xml.is_file():
            continue
        payload = irproto.read_payload(str(proto))
        blocks, starts = irproto.parse_proto(payload)
        per = collections.defaultdict(list)
        for command in ET.parse(xml).getroot().iter("Command"):
            data = command.find("Data")
            if data is None:
                continue
            index, code = data.find("Protocol"), data.find("Code")
            if index is not None and code is not None:
                per[index.text.strip()].append(code.text.strip())

        # Importing must never raise, whatever the blocks contain.
        with contextlib.redirect_stdout(io.StringIO()):
            importer.protocol_table(str(tree))

        for index, (block, position) in enumerate(zip(blocks, starts)):
            runs = 0
            for code in per.get(str(index), []):
                try:
                    ir_vm.simulate_transmission(payload, code)
                    runs += 1
                except ir_vm.IrVmError:
                    pass
            if not runs:
                continue                      # the VM cannot run it; refusal is allowed
            checked += 1
            protocol_json.extract_definition(
                block, payload, position, name=f"block {index}")
    if not checked:
        pytest.skip("no real configuration with runnable protocol blocks")
