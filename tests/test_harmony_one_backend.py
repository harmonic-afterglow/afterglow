"""Harmony One: strict validation, lossless reading, and building from a project."""

from __future__ import annotations

import hashlib
import struct

import pytest

from afterglow import backends, ezhex, importer, payloads, remotes
from afterglow.backends.harmony_one import (
    activity_index, bitmap, command_index, drawing, font_index, glyph_codec,
    gspm, inventory, key_index, layout, named_index, records, resources, structures,
    ui_index)


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


def test_integrity_repair_writes_the_full_end_vector_and_checksum():
    payload = gspm_payload()
    repaired = gspm.seal(payload[:-6])

    assert gspm.validate(repaired)["ok"] is True
    assert repaired[7] == 0


def test_native_device_objects_keep_command_and_device_id_arithmetic():
    bodies, wrappers = structures.device_objects(3, 2, 100, 0x0FCA)

    assert wrappers == [101, 103]
    assert bodies == [
        b"\x02\x00\x03\x7d\x01\x03\x7c",
        b"\x02\xca\x0f\x75\x64\x00\x7f",
        b"\x02\x01\x03\x7d\x01\x03\x7c",
        b"\x02\xca\x0f\x75\x66\x00\x7f",
    ]


def test_glyph_mapping_selects_the_native_repertoire_not_one_fixed_suffix():
    seventy_seven = glyph_codec.resolve_mapping({code: {"shape"} for code in range(1, 78)})
    seventy_nine = glyph_codec.resolve_mapping({code: {"shape"} for code in range(1, 80)})

    assert glyph_codec.decode(b"\x3d\x4c", seventy_seven) == "VX"
    assert glyph_codec.encode("VX", seventy_seven) == b"\x3d\x4c"
    assert glyph_codec.decode(b"\x42\x40", seventy_nine) == "VX"
    assert glyph_codec.encode("VX", seventy_nine) == b"\x42\x40"


def test_glyph_mapping_refuses_an_unknown_repertoire():
    report = glyph_codec.resolve_mapping({code: {"shape"} for code in range(1, 79)})

    assert report["error"] == "unsupported Harmony One glyph repertoire: 78"
    with pytest.raises(ValueError, match="unresolved codes"):
        glyph_codec.decode(b"\x07", report)


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

    report["devices"][0].update({
        "label_lines": ["Media", "Center PC"],
        "label": "Media Center PC",
    })
    devices = command_index.portable_devices(
        ownership, key_index.inspect(payload, ownership), report)
    assert devices[0]["label"] == "Media Center PC"
    assert devices[0]["native"]["harmony-one"]["menu"] == {
        "glyph_lines": ["1112", "1314"],
        "label_lines": ["Media", "Center PC"],
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
    # mode, then width and height as u16s, then two bytes a pixel
    payload = b"\x00\x02\x00\x01\x00" + b"\x12\x34\x56\x78"

    assert ui_index._bitmap_resource(payload, 0) == {
        "offset": 0, "mode": 0, "width": 2, "height": 1, "size": 9,
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
        "state_only_activities": 0,
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


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.__setitem__(slice(0, 4), b"TPTP"), "magic"),
        (lambda value: struct.pack_into("<I", value, 4, gspm.BASE + 0x100), "end vector"),
        (lambda value: struct.pack_into("<I", value, 8, 0x1400), "header constant"),
        (lambda value: value.__setitem__(0x63, 0), "LWJL"),
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
    assert result.preservation["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result.preservation["validation"]["ok"] is True
    assert importer.build_project(source) == result.project


def test_the_backend_builds_a_project_into_an_ezhex_the_app_identifies(tmp_path):
    # From the project alone: the generator's image, wrapped with a header written from the
    # profile, which identifies the file as a Harmony One again when it is read.
    from afterglow import ezhex
    from afterglow.backends.contracts import BuildContext

    profile = remotes.get("harmony-one")
    logged = []
    context = BuildContext(root=tmp_path, log=logged.append,
                           find_scaffold=lambda _id, _root: None)
    project = {"devices": [], "activities": [], "settings": {"out_file": "mine"}}
    result = backends.for_profile(profile).build_project(project, profile, context)
    assert result.artifact == tmp_path / "mine.EZHex"
    raw = result.artifact.read_bytes()
    header, start, size, checksum = ezhex._split(raw)
    assert remotes.identify(header).id == "harmony-one"
    assert checksum == ezhex.checksum(raw[start:start + size])
    gspm.validate(raw[start:start + size])
    # and a theme that is not a scaffold folder is refused by name
    with pytest.raises(ValueError, match="theme"):
        backends.for_profile(profile).build_project(
            {**project, "settings": {"theme_folder": str(tmp_path)}}, profile, context)


def test_screen_index_records_rebuild_the_shape_they_were_read_from():
    payload = gspm_payload()
    start = gspm.section_ranges(payload)[6][0]
    screens = ui_index.screen_slots(payload)
    trailer = screens[0]["trailer_offset"]
    slot = screens[0]["slots"][0]

    index = structures.screen_index([trailer])
    header = int.from_bytes(payload[trailer + 1:trailer + 4], "little") - gspm.BASE
    rebuilt_trailer = structures.screen_trailer(payload[trailer], header, [slot["offset"]])
    rebuilt_slot = structures.screen_slot(
        slot["template"], slot["key_register_offset"], slot["program_offset"])

    assert index == payload[start:start + len(index)]
    assert rebuilt_trailer == payload[trailer:trailer + len(rebuilt_trailer)]
    assert rebuilt_slot == payload[slot["offset"]:slot["offset"] + 7]


def test_a_slot_that_opens_another_screen_is_not_offered_as_a_clone_source():
    sources = resources.command_screen_sources(gspm_payload_with_device_menu())

    assert [(source["screen"], source["slot"]) for source in sources] == [(1, 0)]


def gspm_payload_with_command_screen(paged: bool = False) -> bytes:
    """A screen whose slot draws two labelled buttons, with a font and touch zones."""
    payload = bytearray(gspm_payload(0x2000))
    glyphs, font, frame = 0x400, 0x600, 0x700
    prologue, program, template, keys = 0xB00, 0xB10, 0xC00, 0xC80

    # Section 7: one font whose 71 one-pixel glyphs give the image a proved repertoire.
    for code in range(71):
        payload[glyphs + 5 * code:glyphs + 5 * code + 5] = b"\x01\x01\x00\x00\x00"
    payload[font] = 12
    struct.pack_into("<H", payload, font + 1, 71)
    for code in range(71):
        payload[font + 3 + 3 * code:font + 6 + 3 * code] = (
            gspm.BASE + glyphs + 5 * code).to_bytes(3, "little")
    struct.pack_into("<H", payload, 0x170, 1)
    payload[0x172:0x175] = (gspm.BASE + font).to_bytes(3, "little")

    # One 20x24 mode-0 button frame, shared by both buttons as the donors share theirs.
    payload[frame:frame + 4] = bytes([0, 20, 0, 24])
    if paged:
        # A title at (6,4) and a page total at (23,18), as a paged screen states them.
        head = (b"\x10\x00" + b"\x05\x06\x04\x01\x00"
                + b"\x05\x17\x12\x12\x00" + b"\x17")
        payload[prologue:prologue + len(head)] = head
    else:
        payload[prologue] = 0x17

    # Section 19: one template with a content zone per button, in reading order.
    payload[0x220:0x224] = b"\x01" + (gspm.BASE + template).to_bytes(3, "little")
    payload[template] = 2
    for index, (zone, tag, x, y) in enumerate(
            ((0xC10, 0x31, 100, 900), (0xC20, 0x30, 900, 900))):
        payload[template + 1 + 3 * index:template + 4 + 3 * index] = (
            gspm.BASE + zone).to_bytes(3, "little")
        struct.pack_into("<HHHHB", payload, zone, x, 500, y, 500, tag)
        payload[zone + 9:zone + 12] = (gspm.BASE + zone).to_bytes(3, "little")

    body = b"\x16" + (gspm.BASE + prologue).to_bytes(3, "little")
    for index, (x, glyph) in enumerate(((6, 0x01), (40, 0x02))):
        body += b"\x02" + bytes([x, 10]) + (gspm.BASE + frame).to_bytes(3, "little")
        if not index:
            body += b"\x10\x00"
        body += b"\x05" + bytes([x + 9, 30, glyph]) + b"\x00"
    body += b"\x12\x00\x00\x00"
    if paged:
        body += b"\x05\x0d\x12\x12\x00"  # the page number "1" at (13, 18)
    body += b"\x00"
    payload[program:program + len(body)] = body

    # Point the existing screen's only slot at that program and both touch keys.
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    screens = ui_index.screen_slots(bytes(payload))
    slot = screens[0]["slots"][0]["offset"]
    payload[slot] = 0
    payload[slot + 4:slot + 7] = (gspm.BASE + program).to_bytes(3, "little")
    # Section 19 begins where gspm_payload put its key register, so move it clear.
    payload[slot + 1:slot + 4] = (gspm.BASE + keys).to_bytes(3, "little")
    payload[keys:keys + 9] = b"\x02\xb0\x02\x00\x7f\xb1\x02\x00\x7f"

    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    return bytes(payload)


def _install_fonts(payload: bytearray) -> tuple[int, int]:
    """Append a complete font and a sparse one, as a real image carries them."""
    glyphs = len(payload)
    for _code in range(71):
        payload += b"\x01\x01\x00\x00\x00"
    fonts = []
    for sparse in (False, True):
        fonts.append(len(payload))
        payload += bytes([12]) + (71).to_bytes(2, "little")
        for code in range(71):
            # The sparse font omits N, as a real menu font omits every character its
            # own labels never needed.
            blank = sparse and code + 1 == 0x3C
            payload += (0 if blank else gspm.BASE + glyphs + 5 * code).to_bytes(
                3, "little")
    struct.pack_into("<H", payload, 0x170, 2)
    for index, font in enumerate(fonts):
        payload[0x172 + 3 * index:0x175 + 3 * index] = (
            gspm.BASE + font).to_bytes(3, "little")
    return tuple(fonts)


def gspm_payload_with_menu_replicas() -> bytes:
    """Two agreeing Devices-menu replicas whose single row opens the device screen."""
    base = gspm_payload_with_device_menu()
    at = int.from_bytes(base[4:8], "little") - gspm.BASE - 2
    payload = bytearray(base[:at])
    _install_fonts(payload)

    prologue = int.from_bytes(payload[0x330 + 1:0x330 + 4], "little") - gspm.BASE
    label = b"\x08\x3f"  # "TV" in the 71-code repertoire
    body = (b"\x16" + (gspm.BASE + prologue).to_bytes(3, "little")
            + b"\x10\x01" + b"\x05\x3f\x39" + label + b"\x00" + b"\x00")

    screens = []
    # Both donors hold every key register in section 9; put these there too.
    section9 = struct.unpack_from("<I", payload, 0x0C + 4 * 9)[0] - gspm.BASE
    for replica in range(2):
        program = len(payload)
        payload += body
        keys = section9 + 5 * replica
        payload[keys:keys + 5] = b"\x01\xb0\x01\x00\x7f"
        slot = len(payload)
        payload += (b"\x00" + (gspm.BASE + keys).to_bytes(3, "little")
                    + (gspm.BASE + program).to_bytes(3, "little"))
        trailer = len(payload)
        payload += (b"\x00" + (gspm.BASE + 0x80).to_bytes(3, "little")
                    + (1).to_bytes(2, "little") + (gspm.BASE + slot).to_bytes(3, "little"))
        screens.append(trailer)

    # Screen 0 and 2 are the replicas; screen 1 stays the device command screen.
    device_trailer = int.from_bytes(payload[0x163 + 3:0x163 + 6], "little") - gspm.BASE
    struct.pack_into("<H", payload, 0x160, 3)
    for ordinal, trailer in enumerate((screens[0], device_trailer, screens[1])):
        payload[0x163 + 3 * ordinal:0x166 + 3 * ordinal] = (
            gspm.BASE + trailer).to_bytes(3, "little")
    return gspm.seal(bytes(payload))


def gspm_payload_with_activity_menu() -> bytes:
    """One Activities-menu row, drawn like a device row but starting an activity."""
    base = gspm_payload_with_command_screen(paged=True)
    at = int.from_bytes(base[4:8], "little") - gspm.BASE - 2
    payload = bytearray(base[:at])

    table = struct.unpack_from("<I", payload, 0x0C + 4 * 11)[0] - gspm.BASE
    action = len(payload)
    payload += b"\x01\x02\xff\x1f"      # start activity 2
    struct.pack_into("<H", payload, table, 4)
    payload[table + 11:table + 14] = (gspm.BASE + action).to_bytes(3, "little")

    frame = gspm.BASE + next(
        item["target"] for item in ui_index.drawing_program(
            base, ui_index.screen_slots(base)[0]["slots"][0]["program_offset"]
        )["instructions"] if item["opcode"] == "bitmap")
    program = len(payload)
    payload += (b"\x16" + (gspm.BASE + 0xB00).to_bytes(3, "little")
                + b"\x02\x06\x26" + frame.to_bytes(3, "little")
                + b"\x10\x00" + b"\x05\x3f\x39\x08\x3f\x00"   # "TY" in row 0
                + b"\x02\x06\x5c" + frame.to_bytes(3, "little")
                + b"\x05\x3f\x6f\x25\x34\x00"                # "OK" in row 1
                + b"\x12\x00\x00\x00" + b"\x00")
    # Row 0 starts an activity; row 1 opens a screen, so removing row 0 leaves a page.
    # The register goes in section 9, where every donor keeps them.
    keys = struct.unpack_from("<I", payload, 0x0C + 4 * 9)[0] - gspm.BASE
    payload[keys:keys + 9] = b"\x02\xb1\x03\x00\x7f\xb0\x01\x00\x7f"
    slot = len(payload)
    payload += (b"\x00" + (gspm.BASE + keys).to_bytes(3, "little")
                + (gspm.BASE + program).to_bytes(3, "little"))
    trailer = len(payload)
    payload += (b"\x00" + (gspm.BASE + 0x80).to_bytes(3, "little")
                + (1).to_bytes(2, "little") + (gspm.BASE + slot).to_bytes(3, "little"))
    struct.pack_into("<H", payload, 0x160, 2)
    payload[0x166:0x169] = (gspm.BASE + trailer).to_bytes(3, "little")

    # Three section-10 contexts, so the activity ordinal the row names exists.
    section10 = struct.unpack_from("<I", payload, 0x0C + 4 * 10)[0] - gspm.BASE
    payload[section10] = 3
    for ordinal in range(3):
        body = len(payload)
        payload += b"\x01\xa5\x00\x00\x00"
        payload[section10 + 1 + 3 * ordinal:section10 + 4 + 3 * ordinal] = (
            gspm.BASE + body).to_bytes(3, "little")
    return gspm.seal(bytes(payload))


def test_an_activity_row_is_owned_by_the_activity_it_starts():
    payload = gspm_payload_with_activity_menu()

    report = ui_index.activity_rows(payload)

    assert report["counts"] == {"screens": 1, "rows": 1, "activities": 1}
    assert report["rejected"] == {}
    assert report["rows"][0]["activity"] == 2
    assert report["rows"][0]["screen"] == 1
    assert report["rows"][0]["key_code"] == 0xB1


def test_the_drawing_encoder_is_the_readers_exact_inverse():
    payload = gspm_payload_with_command_screen(paged=True)
    slot = ui_index.screen_slots(payload)[0]["slots"][0]

    blocks = drawing.program_blocks(payload, [slot["program_offset"]])

    assert set(blocks) == {slot["program_offset"], 0xB00}
    for offset, instructions in blocks.items():
        body = drawing.encode_program(instructions)
        assert body == payload[offset:offset + len(body)]


def test_every_drawing_opcode_round_trips():
    shapes = [
        {"opcode": "end"},
        {"opcode": "return"},
        {"opcode": "call", "target": 0x100},
        {"opcode": "jump", "target": 0x110},
        {"opcode": "attribute", "value": 9},
        {"opcode": "bitmap", "x": 6, "y": 38, "target": 0x120},
        {"opcode": "text", "x": 29, "y": 58, "target": 0x130},
        {"opcode": "inline_text", "x": 29, "y": 58, "glyphs": "0102"},
        {"opcode": "atom", "operand": 0x0102, "category": 0x73},
        {"opcode": "rectangle", "x": 1, "y": 2, "width": 3, "height": 4, "color": 0x1234},
        {"opcode": "switch", "selector": 37,
         "cases": [(0, 0x140), (1, 0x150)], "ranges": [(2, 3, 0x160)]},
    ]
    payload = bytearray(gspm_payload(0x2000))
    at = 0x900
    for shape in shapes:
        body = drawing.encode(shape)
        payload[at:at + len(body)] = body
        at += len(body)
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    # Read each shape from its own address, because several of them stop the reader.
    at = 0x900
    for shape in shapes:
        item = ui_index.drawing_program(bytes(payload), at)["instructions"][0]
        assert item["opcode"] == shape["opcode"]
        assert drawing.encode(item) == drawing.encode(shape)
        at += len(drawing.encode(shape))


def test_relocating_a_program_moves_addresses_it_owns_and_no_others():
    instructions = [
        {"opcode": "call", "target": 0x100},
        {"opcode": "bitmap", "x": 0, "y": 0, "target": 0x200},
        {"opcode": "switch", "selector": 1,
         "cases": [(0, 0x100)], "ranges": [(1, 2, 0x300)]},
        {"opcode": "end"},
    ]

    moved = drawing.relocated(instructions, {0x100: 0x900, 0x300: 0xA00})

    assert moved[0]["target"] == 0x900
    assert moved[1]["target"] == 0x200
    assert moved[2]["cases"] == [(0, 0x900)]
    assert moved[2]["ranges"] == [(1, 2, 0xA00)]


def test_a_program_that_does_not_terminate_is_not_emitted():
    with pytest.raises(ValueError, match="must finish at end, return or jump"):
        drawing.encode_program([{"opcode": "attribute", "value": 1}])


def test_the_whole_program_graph_can_be_laid_out_somewhere_else():
    payload = gspm_payload_with_command_screen(paged=True)
    roots = [slot["program_offset"]
             for screen in ui_index.screen_slots(payload) for slot in screen["slots"]]
    blocks = drawing.program_blocks(payload, roots)

    at = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    body, mapping = drawing.lay_out(blocks, at)
    image = gspm.seal(payload[:at] + body)

    # The map names every block, and also the glyph bytes of every inline text, because
    # a `text` instruction's target is always another instruction's inline payload
    # rather than a string of its own. Those entries are what keep the sharing alive
    # across a layout, so they are part of the contract, not noise.
    inline = {
        item["offset"] + 3
        for instructions in blocks.values() for item in instructions
        if item["opcode"] == "inline_text"
    }
    assert set(mapping) == set(blocks) | inline
    assert inline.isdisjoint(blocks)
    for old, new_at in ((old, mapping[old]) for old in blocks):
        read = ui_index.drawing_program(image, new_at)["instructions"]
        assert [item["opcode"] for item in read] == [
            item["opcode"] for item in blocks[old]]
        # every internal reference now names the block's new home
        for item in read:
            if item["opcode"] in ("call", "jump"):
                assert item["target"] in mapping.values()


def test_a_context_rebuilds_the_bytes_it_was_read_from():
    payload = gspm_payload_with_activity_menu()

    for context in activity_index.contexts(payload):
        body = structures.context_record(context)
        assert body == payload[context["offset"]:context["offset"] + len(body)]


def test_a_slot_that_binds_no_key_still_has_a_register():
    assert structures.key_register([]) == b"\x00\x00"
    # A screen's own button map is a 55-row register, so 39 was never a format rule.
    assert len(structures.key_register([(index, 0, 0x7F) for index in range(55)])) == 221
    with pytest.raises(ValueError, match="at most 255 entries"):
        structures.key_register([(index % 256, 0, 0x7F) for index in range(256)])


def test_a_text_pointer_follows_the_inline_glyphs_it_shares():
    """`text` never names a string of its own, so a layout must carry the sharing.

    Every one of the 1,028 text targets across the four donors is the inline payload of
    an `inline_text` instruction, content and all. If a layout did not map those
    addresses, each pointer would have to be redirected to a private copy and the image
    would grow a string pool the format does not have.
    """
    payload = gspm_payload_with_command_screen(paged=True)
    roots = [slot["program_offset"]
             for screen in ui_index.screen_slots(payload) for slot in screen["slots"]]
    blocks = drawing.program_blocks(payload, roots)

    # find an inline text and the address its glyph bytes live at
    root = next(offset for offset, block in sorted(blocks.items())
                if any(item["opcode"] == "inline_text" for item in block))
    cursor, shared, glyphs = root, None, None
    for item in blocks[root]:
        if item["opcode"] == "inline_text" and shared is None:
            shared, glyphs = cursor + 3, item["glyphs"]
        cursor += len(drawing.encode(item))
    assert shared is not None
    assert payload[shared:shared + len(glyphs) // 2].hex() == glyphs

    # a second block draws the same string through a pointer instead of inline
    borrower = max(blocks) + max(1, len(drawing.encode_program(blocks[max(blocks)])))
    blocks[borrower] = [
        {"offset": borrower, "opcode": "text", "x": 3, "y": 4, "target": shared},
        {"offset": borrower + 6, "opcode": "end"},
    ]

    at = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    body, mapping = drawing.lay_out(blocks, at)
    image = gspm.seal(payload[:at] + body)

    assert shared in mapping, "the layout must name the glyph bytes, not only the block"
    moved = ui_index.drawing_program(image, mapping[borrower])["instructions"][0]
    assert moved["opcode"] == "text"
    assert moved["target"] == mapping[shared]
    # and the glyphs really are there, still inside the block that carries them inline
    assert image[moved["target"]:moved["target"] + len(glyphs) // 2].hex() == glyphs
    assert mapping[root] < moved["target"] < mapping[root] + len(
        drawing.encode_program(blocks[root]))


def test_the_catalogue_names_the_parts_an_image_agrees_on():
    payload = gspm_payload_with_command_screen(paged=True)

    found = resources.catalogue(payload)

    assert found["fonts"][resources.BUTTON_FONT_ROLE] == 0
    assert found["fonts"][resources.TITLE_FONT_ROLE] == 0
    assert found["background"] is None
    assert sorted(found["button_frames"]) == [(6, 10), (40, 10)]
    assert found["page_templates"] == {2: 0}
    assert found["counts"]["command_pages"] == 1


def test_a_disagreeing_image_yields_no_resource_rather_than_a_guess():
    payload = bytearray(gspm_payload_with_command_screen(paged=True))
    slot = ui_index.screen_slots(bytes(payload))[0]["slots"][0]
    program = ui_index.drawing_program(bytes(payload), slot["program_offset"])
    frame = next(item for item in program["instructions"] if item["opcode"] == "bitmap")
    # Point one button frame somewhere else and the position stops being agreed.
    payload[frame["offset"] + 3:frame["offset"] + 6] = (
        gspm.BASE + 0x800).to_bytes(3, "little")
    payload[0x800:0x804] = bytes([0, 20, 0, 24])
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    found = resources.catalogue(bytes(payload))

    assert (6, 10) in found["button_frames"]
    assert found["button_frames"][(6, 10)] == 0x800


def test_the_flat_command_index_groups_every_command_by_its_device():
    body = structures.command_flat_index([[0x100, 0x200], [0x300]])

    head = structures.command_index_head()
    assert len(head) == structures.COMMAND_INDEX_HEAD_SIZE
    assert body.startswith(head)
    assert body[len(head):] == (
        # every run opens with a zero byte, the first included
        b"\x00" + (2).to_bytes(2, "little")
        + (gspm.BASE + 0x100 + 11).to_bytes(3, "little")
        + (gspm.BASE + 0x200 + 11).to_bytes(3, "little")
        + b"\x00" + (1).to_bytes(2, "little")
        + (gspm.BASE + 0x300 + 11).to_bytes(3, "little"))


def test_a_configuration_with_no_devices_has_only_the_key_table():
    assert structures.command_flat_index([]) == structures.command_index_head()


def test_a_flat_command_index_refuses_more_devices_than_the_format_holds():
    with pytest.raises(ValueError, match="at most 255 devices"):
        structures.command_flat_index([[]] * 256)


def test_the_build_stamp_round_trips_through_its_markers():
    body = structures.stamp(26, 35, 22, 22, 7, 2023, 3)

    assert body.startswith(structures.STAMP_PREFIX)
    assert body.endswith(structures.STAMP_SUFFIX)
    assert len(body) == 14

    payload = bytearray(gspm_payload(0x2000))
    start = struct.unpack_from("<I", payload, 0x0C + 4 * 3)[0] - gspm.BASE
    # Section 3 runs to wherever section 4 begins, so put section 4 right after it.
    struct.pack_into("<I", payload, 0x0C + 4 * 4, gspm.BASE + start + len(body))
    payload[start:start + len(body)] = body
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    read = structures.read_stamp(bytes(payload))
    assert read["year"] == 2023 and read["month"] == 7 and read["day"] == 22
    assert (read["hour"], read["minute"], read["second"]) == (22, 35, 26)
    assert read["weekday"] == 3
    assert read["weekday_agrees"] is True
    assert read["in_range"] is True


def test_a_stamp_outside_its_measured_ranges_is_refused():
    with pytest.raises(ValueError, match="month is outside"):
        structures.stamp(0, 0, 0, 1, 13, 2023)
    with pytest.raises(ValueError, match="hour is outside"):
        structures.stamp(0, 0, 24, 1, 1, 2023)


def test_the_factory_repertoire_reads_the_messages_it_was_derived_from():
    report = glyph_codec.resolve_mapping({code: {"shape"} for code in range(1, 47)})

    assert report["repertoire"] == 46
    assert glyph_codec.decode(bytes([3, 4, 5, 6, 4, 5, 7, 8, 9, 10, 11, 6, 8]),
                              report) == "Go to Website"
    assert glyph_codec.encode("Battery", report) is not None
    # Every established layout starts with the same two codes, which is what makes the
    # firmware table corroborate the ones derived from household images.
    for size in sorted(glyph_codec.REPERTOIRES):
        assert glyph_codec.REPERTOIRES[size][1] == "H"
        assert glyph_codec.REPERTOIRES[size][2] == "y"


def test_a_font_counts_its_glyphs_in_whichever_header_resolves():
    payload = gspm_payload_with_menu_replicas()

    table = font_index.fonts(payload)

    assert [font["layout"] for font in table] == [font_index.WIDE_COUNT] * len(table)
    assert {font["slots"] for font in table} == {71}


def test_a_font_whose_count_resolves_no_way_is_refused():
    payload = bytearray(gspm_payload_with_menu_replicas())
    start = gspm.section_ranges(bytes(payload))[7][0]
    offset = int.from_bytes(payload[start + 2:start + 5], "little") - gspm.BASE
    # Point the first glyph slot outside the image under either reading.
    payload[offset + 1:offset + 3] = b"\xff\xff"
    payload[offset + 3:offset + 6] = b"\xff\xff\xff"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    with pytest.raises(ValueError, match="no glyph count that resolves"):
        font_index.fonts(bytes(payload))


def test_a_display_colour_survives_the_trip_through_the_screen_format():
    for colour in ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255)):
        packed = bitmap.to_rgb565(colour)
        assert 0 <= packed <= 0xFFFF
        back = bitmap.from_rgb565(packed)
        # Five and six bit channels cannot hold every byte, but the ends are exact.
        assert all(abs(a - b) <= 4 for a, b in zip(colour, back))
    with pytest.raises(ValueError, match="red channel must be a byte"):
        bitmap.to_rgb565((256, 0, 0))


def test_a_stored_picture_rebuilds_the_bytes_it_was_read_from():
    payload = bytearray(gspm_payload(0x4000))
    rows = [[(255, 0, 0), (0, 255, 0)], [(0, 0, 255), (255, 255, 255)]]
    body = bitmap.encode(rows, mode=bitmap.RAW)
    payload[0x900:0x900 + len(body)] = body
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    read = bitmap.decode(bytes(payload), 0x900)

    assert read["mode"] == bitmap.RAW
    assert (read["width"], read["height"]) == (2, 2)
    assert bitmap.encode(read["rows"], mode=bitmap.RAW) == body


def test_a_picture_with_undrawn_pixels_must_be_run_encoded():
    rows = [[(255, 0, 0), None], [None, (0, 0, 255)]]

    body = bitmap.encode(rows)

    assert body[0] == bitmap.RUNS
    with pytest.raises(ValueError, match="cannot store every pixel"):
        bitmap.encode(rows, mode=bitmap.RAW)


def test_a_run_encoded_picture_leaves_its_last_row_unseparated():
    payload = bytearray(gspm_payload(0x4000))
    rows = [[(255, 0, 0), None], [None, (0, 0, 255)]]
    body = bitmap.encode(rows, mode=bitmap.RUNS)
    # One separator for the first row, then the picture terminator.
    assert body.count(bytes([bitmap.ROW_END])) >= 1
    assert body[-1] == bitmap.PICTURE_END
    assert body[-2] != bitmap.ROW_END

    payload[0x900:0x900 + len(body)] = body
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    read = bitmap.decode(bytes(payload), 0x900)
    assert read["rows"] == rows


def test_a_picture_larger_than_the_display_is_refused():
    with pytest.raises(ValueError, match="at most 176x220"):
        bitmap.encode([[(0, 0, 0)] * 177])


def test_both_picture_encodings_share_a_five_byte_header_and_big_endian_pixels():
    # Donor pictures stored whole sit exactly 5 + 2 * width * height apart. Read with a
    # four-byte header they had looked little-endian, and generated ones came out a byte
    # short, their last byte taken from whatever followed.
    colour = (255, 128, 0)
    rows = [[colour, None]]

    raw = bitmap.encode([[colour, colour]], mode=bitmap.RAW)
    runs = bitmap.encode(rows, mode=bitmap.RUNS)

    word = bitmap.to_rgb565(colour).to_bytes(2, "big")
    assert raw[:5] == bytes([bitmap.RAW, 2, 0, 1, 0])
    assert raw[5:] == word * 2
    assert bitmap.decode(raw, 0)["size"] == len(raw) == 9
    # header, then the run length, then the pixel
    assert runs[:5] == bytes([bitmap.RUNS, 2, 0, 1, 0])
    assert runs[6:8] == word


def test_a_picture_is_not_padded_to_a_64_kib_window():
    # A backdrop stored whole is larger than the window, so the rule cannot apply to
    # pictures; the donors put 15 to 19 of them across a boundary in every image.
    out = bytearray(b"\x00" * 16)
    body = bitmap.encode([[(1, 2, 3)] * 4] * 4, mode=bitmap.RAW)

    at = layout.place_picture(out, body)

    assert at == 16
    assert bytes(out[at:at + len(body)]) == body


def test_a_rebuilt_command_record_keeps_the_bytes_it_opened_with():
    # The donors open records with 0, 1, 4, 5, 6, 7 and one with 2f 81, so the opening
    # bytes are carried rather than rebuilt from a flag this backend knows.
    body = records.command_record(
        0x100, 0x200, None, 26315, 26315 // 2, prefix=bytes.fromhex("2f81000000"))

    assert body[:5] == bytes.fromhex("2f81000000")
    with pytest.raises(ValueError, match="opens with 5 bytes"):
        records.command_record(0x100, 0x200, None, 26315, 26315 // 2, prefix=b"\x01")


def test_an_empty_name_chain_is_read_the_way_the_factory_writes_one():
    """A chain with no records declares zero, not the five bytes it occupies.

    The configuration a Harmony One ships with - `Region_3.EZHex` in firmware 54.2.5 -
    writes `ed fe 00 00 00 ef be` there, and the remote runs it. A reader that computed
    the length and insisted on it would refuse the vendor's own image, which is a gate
    stricter than the runtime it protects.
    """
    payload = bytearray(gspm_payload(0x320))
    section = b"\xed\xfe\x00\x00\x00\xef\xbe"
    delta = len(section) - 0x10
    for index in range(1, gspm.SECTION_COUNT):
        if index == gspm.ABSENT_SECTION:
            continue
        field = 0x0C + 4 * index
        struct.pack_into(
            "<I", payload, field, struct.unpack_from("<I", payload, field)[0] + delta)
    payload[0x100:0x100 + len(section)] = section
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    report = named_index.inspect(bytes(payload))

    assert report["counts"]["records"] == 0
    assert named_index.leaf_names(report) == {}


def test_section_fourteen_splits_into_clock_platform_and_household():
    payload = gspm_payload_with_activity_menu()

    shape = activity_index.engine_shape(payload)

    assert len(shape["clock"]) <= activity_index.CLOCK_PROPERTIES
    assert shape["counts"]["ambiguous"] == 0
    for record in shape["clock"]:
        assert record["transitions"] == [] or all(
            row["from"] == activity_index.ANY_STATE for row in record["transitions"])


def test_a_household_property_drives_at_most_one_device():
    """Every household record that sends anything sends it to exactly one device.

    5, 8, 11 and 5 records across the four donors, never two devices in one record, which
    is what makes a property a device's own state rather than an activity's.
    """
    payload = gspm_payload_with_activity_menu()

    shape = activity_index.engine_shape(payload)

    for property_id, devices in shape["driven"].items():
        assert len(devices) <= 1, f"property {property_id} drives {devices}"


def test_a_configuration_with_no_activities_names_no_current_one():
    payload = gspm_payload_with_activity_menu()

    assert activity_index.current_activity(payload, 0) is None


def test_an_activity_that_drives_nothing_is_named_rather_than_left_unresolved():
    """All Off writes state and sends nothing, which is a fact rather than a failure.

    In every donor one context reaches no command: it writes eight properties, none of
    them one that drives a device, and its set is always a subset of what a real activity
    writes. Reporting that as undetermined confuses "this backend could not follow it"
    with "it genuinely drives nothing", and its command path is not in section 14.
    """
    payload = gspm_payload_with_activity_menu()

    report = activity_index.inspect(payload)

    counts = report["counts"]
    assert counts["determined_activities"] + counts["state_only_activities"] == (
        counts["activities"])
    for activity in report["activities"]:
        assert not (activity["determined"] and activity["state_only"])


def test_all_off_is_every_driving_property_returning_to_zero():
    """The All Off context stores no commands because it does not need to.

    Every property that drives a device has exactly one transition to state zero and that
    transition carries a command - 5, 8, 11 and 5 properties across the four donors,
    without exception - so turning everything off is driving each of them to zero. A
    driving property with no way back to zero would leave a device on, which is why that
    is reported rather than assumed away.
    """
    payload = gspm_payload_with_activity_menu()

    report = activity_index.all_off(payload)

    assert report["properties_without_an_off"] == []
    for property_id, item in report["properties"].items():
        assert item["command_ids"], f"property {property_id} cannot be turned off"
        if item["power_toggle"]:
            assert item["limit"] == 1
    assert report["command_ids"] == sorted(set(report["command_ids"]))
