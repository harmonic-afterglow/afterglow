"""Harmony One starts with strict read-only validation and lossless preservation."""

from __future__ import annotations

import struct

import pytest

from afterglow import backends, ezhex, importer, payloads, remotes
from afterglow.backends.harmony_one import (
    activity_index,
    command_index,
    differential,
    gspm,
    inventory,
    key_index,
    named_index,
    ui_index,
)


def gspm_payload(size=0x300) -> bytes:
    payload = bytearray(size)
    payload[:4] = gspm.MAGIC
    marker = size - 4
    struct.pack_into("<II", payload, 4, gspm.BASE + marker, gspm.HEADER_CONSTANT)
    section_offsets = iter(range(0x100, 0x100 + 0x10 * 19, 0x10))
    sections = []
    for index in range(gspm.SECTION_COUNT):
        relative = None if index == gspm.ABSENT_SECTION else next(section_offsets)
        sections.append(relative)
        pointer = 0 if relative is None else gspm.BASE + relative
        struct.pack_into("<I", payload, 0x0C + index * 4, pointer)
    payload[gspm.BUTTON_MAP_OFFSET:gspm.BUTTON_MAP_OFFSET + 5] = gspm.BUTTON_MAP_MAGIC

    object_table = sections[11]
    assert object_table is not None
    struct.pack_into("<H", payload, object_table, 3)
    payload[object_table + 2:object_table + 5] = (gspm.BASE + 0x80).to_bytes(3, "little")
    payload[object_table + 5:object_table + 8] = (gspm.BASE + 0x90).to_bytes(3, "little")
    payload[object_table + 8:object_table + 11] = (gspm.BASE + 0xA0).to_bytes(3, "little")
    payload[0x80:0x87] = b"\x02\x01\x00\x10\xe7\x03\x75"
    payload[0x90:0x94] = b"\x01\x00\x00\x10"
    payload[0xA0:0xA7] = b"\x02\x00\x00\x7d\x01\x00\x7c"

    command, waveform, hold = 0x230, 0x260, 0x280
    section5 = sections[5]
    assert section5 is not None
    subtable = section5 + 4
    payload[section5] = 1
    payload[section5 + 1:section5 + 4] = (gspm.BASE + subtable).to_bytes(3, "little")
    payload[subtable] = 0
    struct.pack_into("<H", payload, subtable + 1, 1)
    payload[subtable + 3:subtable + 6] = (gspm.BASE + command + 11).to_bytes(
        3, "little")
    payload[command] = 1
    payload[command + 5:command + 8] = (26315).to_bytes(3, "little")
    payload[command + 8:command + 11] = (26315 // 2).to_bytes(3, "little")
    payload[command + 11] = 1
    payload[command + 12:command + 15] = (gspm.BASE + command + 4).to_bytes(3, "little")
    payload[command + 15] = 2
    payload[command + 16:command + 19] = (gspm.BASE + waveform).to_bytes(3, "little")
    payload[command + 19:command + 22] = (gspm.BASE + hold).to_bytes(3, "little")
    struct.pack_into("<6H", payload, waveform,
                     inventory.LEAD_IN, 17233, 0x8000 | 560, 20000, 20000, 1)
    struct.pack_into("<4H", payload, hold, 0x8000 | 560, 20000, 20000, 1)

    screen_index = sections[6]
    assert screen_index is not None
    trailer, slot, key_register, program = 0x200, 0x210, 0x220, 0x225
    struct.pack_into("<H", payload, screen_index, 1)
    payload[screen_index + 2] = 0
    payload[screen_index + 3:screen_index + 6] = (
        gspm.BASE + trailer).to_bytes(3, "little")
    payload[trailer] = 0
    payload[trailer + 1:trailer + 4] = (gspm.BASE + 0x80).to_bytes(3, "little")
    struct.pack_into("<H", payload, trailer + 4, 1)
    payload[trailer + 6:trailer + 9] = (gspm.BASE + slot).to_bytes(3, "little")
    payload[slot] = 4
    payload[slot + 1:slot + 4] = (gspm.BASE + key_register).to_bytes(3, "little")
    payload[slot + 4:slot + 7] = (gspm.BASE + program).to_bytes(3, "little")
    payload[key_register:key_register + 5] = b"\x01\xb0\x02\x00\x7f"
    payload[program] = 0
    payload[marker:marker + 4] = b"PTYY"
    checksum_offset = marker - 2
    payload[checksum_offset:marker] = bytes(gspm.checksum(payload, checksum_offset))
    return bytes(payload)


def gspm_payload_with_device_menu() -> bytes:
    payload = bytearray(gspm_payload(0x500))
    screen_index = 0x160
    menu_trailer, menu_slot, menu_keys, menu_program = 0x300, 0x310, 0x320, 0x330
    device_trailer, device_slot, device_keys, device_program = 0x340, 0x350, 0x360, 0x370

    struct.pack_into("<H", payload, screen_index, 2)
    payload[screen_index + 2] = 0
    payload[screen_index + 3:screen_index + 9] = b"".join(
        (gspm.BASE + offset).to_bytes(3, "little")
        for offset in (menu_trailer, device_trailer)
    )
    for trailer, slot in ((menu_trailer, menu_slot), (device_trailer, device_slot)):
        payload[trailer] = 0
        payload[trailer + 1:trailer + 4] = (gspm.BASE + 0x80).to_bytes(3, "little")
        struct.pack_into("<H", payload, trailer + 4, 1)
        payload[trailer + 6:trailer + 9] = (gspm.BASE + slot).to_bytes(3, "little")
    for slot, keys, program in (
            (menu_slot, menu_keys, menu_program),
            (device_slot, device_keys, device_program)):
        payload[slot] = 0
        payload[slot + 1:slot + 4] = (gspm.BASE + keys).to_bytes(3, "little")
        payload[slot + 4:slot + 7] = (gspm.BASE + program).to_bytes(3, "little")

    # Object 1 opens screen 1; object 2 remains the command object owned by section 5.
    payload[0x90:0x94] = b"\x01\x01\x00\x7e"
    payload[menu_keys:menu_keys + 5] = b"\x01\xb0\x01\x00\x7f"
    payload[device_keys:device_keys + 5] = b"\x01\xb0\x02\x00\x7f"
    payload[device_program] = 0

    prologue, line_one, line_two = 0x3B0, 0x3C0, 0x3D0
    payload[prologue] = 0x17
    payload[line_one:line_one + 3] = b"\x11\x12\x00"
    payload[line_two:line_two + 3] = b"\x13\x14\x00"
    payload[menu_program:menu_program + 17] = (
        b"\x16" + (gspm.BASE + prologue).to_bytes(3, "little")
        + b"\x04\x3f\x33" + (gspm.BASE + line_one).to_bytes(3, "little")
        + b"\x04\x3f\x3f" + (gspm.BASE + line_two).to_bytes(3, "little")
        + b"\x00"
    )

    # Section 19: one touch template with one self-checked row zone.
    template, zone = 0x380, 0x390
    payload[0x220:0x224] = b"\x01" + (gspm.BASE + template).to_bytes(3, "little")
    payload[template:template + 4] = b"\x01" + (gspm.BASE + zone).to_bytes(3, "little")
    struct.pack_into("<HHHHB", payload, zone, 1000, 1000, 3000, 500, 0x30)
    payload[zone + 9:zone + 12] = (gspm.BASE + zone).to_bytes(3, "little")

    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    return bytes(payload)


def gspm_payload_with_activity() -> bytes:
    payload = bytearray(gspm_payload_with_device_menu())
    # Give section 14 exactly the measured 8 + 3*n bytes for one property.
    struct.pack_into("<I", payload, 0x0C + 4 * 15, gspm.BASE + 0x1DB)

    # Add object 3: the activity ENTER hook sets property 0 to value 1.
    struct.pack_into("<H", payload, 0x1A0, 4)
    payload[0x1A2:0x1AE] = b"".join(
        (gspm.BASE + offset).to_bytes(3, "little")
        for offset in (0x80, 0x90, 0xA0, 0xB0)
    )
    payload[0xB0:0xB4] = b"\x01\x01\x00\x80"

    # Section 10 has one short-form context whose ENTER key reaches object 3.
    payload[0x190:0x194] = b"\x01" + (gspm.BASE + 0x410).to_bytes(3, "little")
    payload[0x410:0x415] = b"\x01\x01\x03\x00\x7f"

    # Property 0 transitions to value 1 by executing command object 2.
    struct.pack_into("<H", payload, 0x1D0, 1)
    payload[0x1D2:0x1D8] = bytes(6)
    payload[0x1D8:0x1DB] = (gspm.BASE + 0x420).to_bytes(3, "little")
    struct.pack_into("<HHH", payload, 0x420, 0, 1, 1)
    payload[0x426] = 0
    struct.pack_into("<BHHHB", payload, 0x427, 0, 0xFFFE, 1, 2, 0x7F)

    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    return bytes(payload)


def test_a_measured_arch_12_image_passes_native_validation():
    payload = gspm_payload()

    report = gspm.validate(payload)

    assert report["ok"] is True
    assert report["validator"] == "harmony-one/gspm-structural"
    assert report["sections"] == 19
    assert report["preserved_bytes"] == len(payload)


def test_an_odd_checksum_span_ignores_its_unpaired_final_byte():
    payload = bytearray(gspm_payload(0x301))
    checksum_offset = len(payload) - 6
    assert checksum_offset % 2
    payload[checksum_offset - 1] ^= 0xFF

    assert gspm.validate(bytes(payload))["ok"] is True


def test_native_command_ownership_is_derived_from_indexes_not_byte_scans():
    report = inventory.inspect(gspm_payload())

    assert report["objects"] == {
        "objects": 3,
        "atoms": 5,
        "opcodes": 4,
        "reference_opcodes": [0x10, 0x7C, 0x7D],
    }
    assert report["commands"]["commands"] == 1
    assert report["commands"]["repeating_commands"] == 1
    assert report["commands"]["record_offsets"] == [0x230]
    assert report["keys"]["counts"] == {
        "screens": 1,
        "slots": 1,
        "key_registers": 1,
        "entries": 1,
        "command_bindings": 1,
        "page_bindings": 0,
        "other_class_bindings": 0,
    }
    assert report["keys"]["rejected"] == {}
    assert report["ownership"]["counts"] == {
        "devices": 1,
        "declared_commands": 1,
        "decoded_commands": 1,
        "portable_waveform_commands": 1,
        "release_commands": 0,
        "command_objects": 1,
        "duplicate_command_objects": 0,
    }
    owned = report["ownership"]["devices"][0]["commands"][0]
    assert owned["command_id"] == 0
    assert owned["device_ids"] == [1]
    assert {phase: wave["offset"] for phase, wave in owned["waveforms"].items()} == {
        "press": 0x260,
        "hold": 0x280,
    }


def test_screen_key_registers_resolve_through_objects_to_indexed_commands():
    report = key_index.inspect(gspm_payload())

    assert report["bindings"] == [{
        "screen": 0,
        "slot": 0,
        "template": 4,
        "key_code": 0xB0,
        "object_index": 2,
        "command_id": 0,
        "device_ids": [1],
        "target_pages": [],
        "key_register_offset": 0x220,
        "program_offset": 0x225,
    }]

    devices = command_index.portable_devices(
        command_index.inspect(gspm_payload()), report)
    evidence = devices[0]["signals"]["Command 00"]["native"]["harmony-one"]
    assert evidence["key_bindings"] == report["bindings"]


def test_a_multi_command_key_action_is_counted_instead_of_flattened():
    original = gspm_payload()
    ownership = command_index.inspect(original)
    payload = bytearray(original)
    payload[0xA0:0xAA] = b"\x03\x00\x00\x7d\x01\x00\x7c\x01\x00\x7d"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = key_index.inspect(bytes(payload), ownership)

    assert report["counts"]["command_bindings"] == 0
    assert report["rejected"] == {"ambiguous_command_action": 1}


def test_multiline_device_labels_are_owned_by_their_navigation_zone():
    payload = gspm_payload_with_device_menu()
    ownership = command_index.inspect(payload)

    report = ui_index.device_menus(payload, ownership)

    assert report["counts"] == {
        "candidate_menus": 1,
        "replica_menus": 1,
        "replica_rows": 1,
        "owned_devices": 1,
        "native_only_rows": 0,
    }
    assert report["rejected"] == {}
    assert report["devices"] == [{
        "device_index": 0,
        "glyph_lines": ["1112", "1314"],
        "target_screen": 1,
        "occurrences": 1,
    }]

    devices = command_index.portable_devices(
        ownership, key_index.inspect(payload, ownership), report)
    assert devices[0]["native"]["harmony-one"]["menu"] == {
        "glyph_lines": ["1112", "1314"],
        "target_screen": 1,
        "occurrences": 1,
    }


def test_touch_zone_self_pointers_are_required_to_close():
    payload = bytearray(gspm_payload_with_device_menu())
    payload[0x390 + 9:0x390 + 12] = (gspm.BASE + 0x391).to_bytes(3, "little")
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    with pytest.raises(ValueError, match="self-pointer does not close"):
        ui_index.touch_templates(bytes(payload))


def test_font_glyph_shapes_ignore_the_literal_palette():
    first = b"\x04\x82\x02\xff\xff\xff\xff\x80\x82\x02\x00\x00\x00\x00\x00"
    second = b"\x04\x82\x02\x12\x34\x56\x78\x80\x82\x02\xab\xcd\xef\x01\x00"

    assert ui_index._glyph_shape(first, 0)["shape"] == \
        ui_index._glyph_shape(second, 0)["shape"]


def test_drawing_walks_follow_shared_prologue_calls():
    report = ui_index.drawing_inventory(gspm_payload_with_device_menu())

    assert report["rejected"] == {}
    assert report["counts"]["blocks"] == 3
    assert report["counts"]["text_uses"] == 2


def test_mode_zero_bitmap_resources_are_bounded_by_their_dimensions():
    payload = b"\x00\x02\x00\x01" + b"\x12\x34\x56\x78"

    assert ui_index._bitmap_resource(payload, 0) == {
        "offset": 0, "mode": 0, "width": 2, "height": 1, "size": 8,
    }


def test_activity_enter_hooks_resolve_state_transitions_to_indexed_commands():
    payload = gspm_payload_with_activity()

    report = activity_index.inspect(payload, command_index.inspect(payload))

    assert report["counts"] == {
        "contexts": 1,
        "context_rows": 1,
        "engine_properties": 1,
        "engine_transitions": 1,
        "activities": 1,
        "determined_activities": 1,
        "menu_activities": 0,
        "mixed_device_screens": 0,
        "engine_commands": 1,
        "physical_context_rows": 1,
        "editable_physical_context_rows": 0,
    }
    assert report["rejected"] == {}
    assert report["activities"][0]["command_ids"] == [0]
    assert report["activities"][0]["device_indices"] == [0]
    assert report["activities"][0]["writes"] == [{
        "hook": "enter",
        "property_id": 0,
        "property_name": None,
        "value": 1,
        "limit": 1,
        "transition_count": 1,
        "command_ids": [0],
        "device_indices": [0],
    }]


def test_long_activity_contexts_retain_their_row_flags():
    payload = bytearray(gspm_payload_with_activity())
    payload[0x410:0x417] = b"\x00\x01\xa5\x01\x03\x00\x7f"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    context = activity_index.contexts(bytes(payload))[0]

    assert context["form"] == "long"
    assert context["rows"] == [{
        "index": 0,
        "offset": 0x412,
        "flags": 0xA5,
        "key_code": 0x01,
        "operand": 3,
        "category": 0x7F,
    }]


def test_physical_context_rows_are_editable_only_when_the_command_is_indexed():
    payload = bytearray(gspm_payload_with_activity())
    payload[0x410:0x415] = b"\x01\x88\x02\x00\x7f"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = activity_index.physical_contexts(
        bytes(payload), command_index.inspect(bytes(payload)))

    assert report["counts"] == {"contexts": 1, "rows": 1, "editable_rows": 1}
    row = report["contexts"][0]["rows"][0]
    assert row["shape"] == "direct"
    assert row["command_id"] == 0
    assert row["device_id"] == 1
    assert row["editable"] is True


def test_section_zero_names_are_owned_by_a_contiguous_closed_chain():
    payload = bytearray(gspm_payload())
    payload[0x100:0x110] = (
        b"\xed\xfe\x0e\x00\x00"
        b"\xa7\x06\x00\x01\x00\x00\x00XY"
        b"\xef\xbe"
    )
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = named_index.inspect(bytes(payload))

    assert report["counts"] == {
        "records": 1, "containers": 0, "leaves": 1, "other_types": 0,
    }
    assert report["rejected"] == {}
    assert named_index.leaf_names(report) == {0: "XY"}


def test_section_zero_names_are_not_limited_to_word_characters():
    payload = bytearray(gspm_payload(0x320))
    name = b"Game Console (With DVD)_Power_2"
    length = 4 + len(name)
    section = (
        b"\xed\xfe" + (3 + 3 + length + 2).to_bytes(3, "little")
        + b"\xa7" + length.to_bytes(2, "little")
        + b"\x01\x00\x2b\x00" + name + b"\xef\xbe"
    )
    # Move every following section equally so section 0 ends at the terminator.
    delta = len(section) - 0x10
    for index in range(1, gspm.SECTION_COUNT):
        if index == gspm.ABSENT_SECTION:
            continue
        field = 0x0C + 4 * index
        struct.pack_into("<I", payload, field, struct.unpack_from("<I", payload, field)[0] + delta)
    payload[0x100:0x100 + len(section)] = section
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    assert named_index.leaf_names(named_index.inspect(bytes(payload))) == {
        0x2B: "Game Console (With DVD)_Power_2",
    }


def test_owned_native_commands_become_portable_press_and_repeat_waveforms():
    report = command_index.inspect(gspm_payload())

    devices = command_index.portable_devices(report)

    assert len(devices) == 1
    assert devices[0]["label"] == "Harmony One device 0"
    signal = devices[0]["signals"]["Command 00"]
    assert signal["kind"] == "waveform"
    assert signal["carrier_hz"] == 38001
    assert signal["sections"] == {"intro_pulses": 2, "repeat_pulses": 2}
    assert signal["pulses_us"] == [560, -40000, 560, -40000]
    assert signal["native"]["harmony-one"]["entry_us"] == 50000


def test_a_zero_terminated_third_record_pointer_becomes_a_release_phase():
    payload = bytearray(gspm_payload())
    release = 0x290
    payload[0x230 + 22:0x230 + 25] = (gspm.BASE + release).to_bytes(3, "little")
    struct.pack_into("<4H", payload, release,
                     0x8000 | 9000, 4500, 0x8000 | 560, 0)
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = command_index.inspect(bytes(payload))
    signal = command_index.portable_devices(report)[0]["signals"]["Command 00"]

    assert report["counts"]["release_commands"] == 1
    assert signal["kind"] == "waveform"
    assert signal["sections"] == {
        "intro_pulses": 2,
        "repeat_pulses": 2,
        "release_pulses": 3,
    }
    assert signal["pulses_us"][-3:] == [9000, -4500, 560]
    assert signal["native"]["harmony-one"]["waveform_offsets"]["release"] == release


def test_a_release_pointer_without_its_zero_sentinel_is_rejected():
    payload = struct.pack("<3H", 0x8000 | 9000, 4500, 0x8000 | 560)

    with pytest.raises(ValueError, match="no zero terminator"):
        command_index._decode_release_waveform(payload, 0)


def test_differential_audit_distinguishes_storage_from_on_air_equivalence():
    payload = bytearray(gspm_payload())
    # The donor form may retain two adjacent marks. Portable meaning coalesces them,
    # and lowering emits one mark of their summed duration.
    struct.pack_into("<7H", payload, 0x260,
                     inventory.LEAD_IN, 17233, 0x8000 | 280, 0x8000 | 280,
                     20000, 20000, 1)
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = differential.audit(bytes(payload))

    assert report == {
        "counts": {
            "commands": 1,
            "portable": 1,
            "opaque": 0,
            "byte_exact": 0,
            "waveform_equivalent": 1,
            "mismatch": 0,
        },
        "failures": [],
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.__setitem__(slice(0, 4), b"TPTP"), "magic"),
        (lambda value: struct.pack_into("<I", value, 4, gspm.BASE + 0x100), "end vector"),
        (lambda value: struct.pack_into("<I", value, 8, 0x1400), "header constant"),
        (lambda value: value.__setitem__(0x63, 0), "LWJL7"),
        (lambda value: value.__setitem__(0x80, 1), "checksum mismatch"),
        (lambda value: struct.pack_into("<I", value, 0x0C, 0xFFFFFF), "section 0"),
    ],
)
def test_a_structurally_invalid_image_is_rejected(change, message):
    payload = bytearray(gspm_payload())
    change(payload)
    if message != "checksum mismatch":
        marker = len(payload) - 4
        payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    with pytest.raises(ValueError, match=message):
        gspm.validate(bytes(payload))


def test_import_accounts_for_every_opaque_byte_and_preserves_the_payload(tmp_path):
    profile = remotes.get("harmony-one")
    payload = gspm_payload()
    source = tmp_path / "source"
    payloads.get(profile.payload).unpack(payload, source)

    result = backends.for_profile(profile).import_project(source, profile, {})

    assert payloads.get(profile.payload).build(source) == payload
    assert result.project["settings"]["remote"] == "harmony-one"
    assert len(result.project["devices"]) == 1
    assert result.preservation["mode"] == "opaque-native-payload"
    assert result.preservation["validation"]["ok"] is True
    assert result.rejected == {
        "native_objects": 2,
        "native_commands": 0,
        "native_payload_bytes": len(payload),
    }
    assert result.warnings


def test_the_shared_import_facade_retains_backend_evidence(tmp_path):
    profile = remotes.get("harmony-one")
    payload = gspm_payload()
    source = tmp_path / "source"
    payloads.get(profile.payload).unpack(payload, source)
    (source / ".ezhex_header").write_bytes(ezhex.header_for_profile(profile))

    result = importer.import_result(source)

    assert result.project["settings"]["remote"] == "harmony-one"
    assert result.preservation["validation"]["ok"] is True
    assert importer.build_project(source) == result.project


def test_the_read_only_backend_refuses_to_author(tmp_path):
    profile = remotes.get("harmony-one")

    with pytest.raises(NotImplementedError, match="authoring is not implemented"):
        backends.for_profile(profile).build_project({}, profile, None)
