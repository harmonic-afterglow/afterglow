"""Harmony One starts with strict read-only validation and lossless preservation."""

from __future__ import annotations

import struct

import pytest

from afterglow import backends, ezhex, importer, payloads, remotes
from afterglow.backends.harmony_one import (
    activity_edit,
    activity_index,
    authoring,
    baseline,
    build,
    command_index,
    differential,
    font_index,
    glyph_codec,
    gspm,
    inventory,
    key_index,
    named_index,
    relocation,
    screen_program,
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


def test_a_section_insertion_map_preserves_every_old_byte_location():
    old = b"abcdef"
    new = b"abXYcdef"
    mapping = relocation.insertion_map(len(old), 2, 2)

    relocation.validate_map(old, new, mapping)

    assert mapping == ((0, 2, 0), (2, 6, 2))
    assert [relocation.map_offset(mapping, index) for index in range(len(old))] == [
        0, 1, 4, 5, 6, 7,
    ]


def test_a_relocation_map_rejects_an_undeclared_content_change():
    with pytest.raises(ValueError, match="does not reproduce"):
        relocation.validate_map(b"abcdef", b"abXdef", ((0, 6, 0),))


def test_the_relocation_pointer_census_uses_only_owned_structures():
    payload = gspm_payload()

    census = relocation.pointer_census(payload)
    affected = relocation.references_into(payload, gspm.section_ranges(payload))

    assert len(census) == 27
    assert {item["label"] for item in census
            if item["target"] == 0x220 and item["width"] == 3} == {
        "section 6 screen 0 slot 0 key register",
    }
    assert len(affected) == 23


def test_integrity_repair_writes_the_full_end_vector_and_checksum():
    payload = gspm_payload()
    repaired = relocation.repair_integrity(payload[:-6])

    assert gspm.validate(repaired)["ok"] is True
    assert repaired[7] == 0


def test_changed_ranges_are_compact_and_include_length_changes():
    assert relocation.changed_ranges(b"abc123", b"axc12XYZ") == [
        (1, 2), (5, 8),
    ]


def test_a_no_op_relocation_repairs_every_owned_affected_pointer():
    payload = gspm_payload()

    relocated, report = relocation.relocate(payload)

    assert gspm.validate(relocated)["ok"] is True
    assert report["repaired_pointers"] == 3
    assert report["old_size"] < report["new_size"]
    assert relocation.references_into(
        relocated,
        {index: tuple(values["old"])
         for index, values in report["sections"].items()},
    ) == []


def test_an_existing_object_table_entry_can_be_repointed_to_an_appended_clone():
    payload = gspm_payload()
    start10, end10 = gspm.section_ranges(payload)[10]
    clone = b"\x01\x34\x12\x75"

    relocated, report = relocation.relocate(
        payload, {10: payload[start10:end10] + clone},
        object_repoints={0: end10 - start10},
    )

    objects = command_index.objects(relocated)
    assert objects[0]["atoms"] == ((0x1234, 0x75),)
    assert report["repointed_objects"] == 1


def test_native_device_objects_keep_command_and_device_id_arithmetic():
    bodies, wrappers = authoring.device_objects(3, 2, 100, 0x0FCA)

    assert wrappers == [101, 103]
    assert bodies == [
        b"\x02\x00\x03\x7d\x01\x03\x7c",
        b"\x02\xca\x0f\x75\x64\x00\x7f",
        b"\x02\x01\x03\x7d\x01\x03\x7c",
        b"\x02\xca\x0f\x75\x66\x00\x7f",
    ]


def test_native_pages_use_the_measured_physical_key_order():
    entries = list(zip(authoring.PHYSICAL_KEY_ORDER, range(20, 26)))

    assert authoring.page(entries) == (
        b"\x06\xb2\x14\x00\x7f\xb3\x15\x00\x7f\xb0\x16\x00\x7f"
        b"\xb1\x17\x00\x7f\xb4\x18\x00\x7f\xb5\x19\x00\x7f"
    )


def test_section5_serializers_round_trip_the_indexed_command_layout():
    payload = gspm_payload()
    layout = authoring.section5_layout(payload)

    assert layout == [{
        "device_index": 0, "field": 0x151, "subtable": 0x154,
        "commands": [{"ordinal": 0, "field": 0x157, "record_offset": 0x230}],
    }]
    assert authoring.section5([0x154]) == payload[0x150:0x154]
    assert authoring.command_subtable([0x230]) == payload[0x154:0x15A]


def test_existing_page_keys_are_reassigned_by_cloning_their_wrapper():
    payload = bytearray(gspm_payload())
    payload[0x80:0x87] = b"\x02\xca\x0f\x75\x02\x00\x7f"
    payload[0x180:0x185] = b"\x01\xb2\x00\x00\x7f"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    original = bytes(payload)

    result, report = authoring.assign_keys(original, [(0, 0xB2, 0)])

    assert report["assignments"] == [{
        "page": 0, "key_code": 0xB2, "command_id": 0, "device_id": 1,
    }]
    assert authoring.page_command_map(original) == {(0, 0xB2): (0, 1)}
    assert authoring.page_command_map(result) == {(0, 0xB2): (0, 1)}
    assert gspm.validate(result)["ok"] is True


def test_existing_context_keys_are_reassigned_by_cloning_their_action():
    payload = bytearray(gspm_payload_with_activity())
    struct.pack_into("<H", payload, 0x412, 2)
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))
    payload = bytes(payload)
    before = authoring._physical_map(payload)
    key, (command_id, device_id) = next(iter(before.items()))

    result, report = authoring.assign_context_keys(
        payload, [(key[0], key[1], command_id)], device_ids=[device_id])

    assert report["assignments"] == [{
        "context": key[0], "row": key[1], "command_id": command_id,
        "device_id": device_id,
    }]
    assert authoring._physical_map(result) == before
    assert gspm.validate(result)["ok"] is True


def test_activity_property_values_are_changed_by_repointing_cloned_objects():
    payload = gspm_payload_with_activity()

    changed, report = activity_edit.edit_property(
        payload, 0, 0, operation="change", value=1, include_refresh=False)
    restored, _ = activity_edit.edit_property(
        changed, 0, 0, operation="change", value=1, include_refresh=False)

    assert report["repointed_objects"] == [3]
    assert activity_index.inspect(changed)["counts"] == activity_index.inspect(payload)["counts"]
    assert gspm.validate(restored)["ok"] is True


def test_activity_property_edits_reject_values_without_transitions():
    with pytest.raises(ValueError, match="no transition to value"):
        activity_edit.edit_property(
            gspm_payload_with_activity(), 0, 0, operation="change", value=0,
            include_refresh=False)


def test_activity_property_assignments_can_be_removed_and_added_back():
    payload = bytearray(gspm_payload_with_activity())
    payload[0xB0:0xB7] = b"\x02\x01\x00\x80\x34\x12\x07"
    marker = len(payload) - 4
    payload[marker - 2:marker] = bytes(gspm.checksum(payload, marker - 2))

    removed, report = activity_edit.edit_property(
        bytes(payload), 0, 0, operation="remove", include_refresh=False)
    restored, _ = activity_edit.edit_property(
        removed, 0, 0, operation="add", value=1, include_refresh=False)

    assert report["operation"] == "remove"
    assert activity_edit._locations(command_index.objects(removed), 3, 0) == []
    assert len(activity_edit._locations(command_index.objects(restored), 3, 0)) == 1


def test_a_new_command_device_extends_section5_and_owns_lowered_records():
    payload = gspm_payload()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]

    result, report = authoring.add_command_device(payload, [signal])

    ownership = command_index.inspect(result)
    assert report["device_index"] == 1
    assert report["wrapper_object_ids"] == [4]
    assert ownership["counts"]["devices"] == 2
    assert ownership["counts"]["decoded_commands"] == 2
    assert ownership["devices"][1]["commands"][0]["command_id"] == 0x100
    assert gspm.validate(result)["ok"] is True


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
    restored, evidence = baseline.load(result.project, profile)
    assert restored == payload
    assert evidence["sha256"] == result.preservation["sha256"]
    assert result.preservation["validation"]["ok"] is True
    assert importer.build_project(source) == result.project


def test_the_same_device_baseline_rejects_changed_source_bytes(tmp_path):
    profile = remotes.get("harmony-one")
    source = tmp_path / "source"
    payloads.get(profile.payload).unpack(gspm_payload(), source)
    project = backends.for_profile(profile).import_project(source, profile, {}).project
    (source / "payload.bin").write_bytes(gspm_payload(0x320))

    with pytest.raises(ValueError, match="bytes changed"):
        baseline.load(project, profile)


def test_the_read_only_backend_refuses_to_author(tmp_path):
    profile = remotes.get("harmony-one")

    # The build machinery exists and is tested; the safety gate is what keeps it shut.
    with pytest.raises(remotes.NotBuildable, match="read-only"):
        backends.for_profile(profile).build_project({}, profile, None)


def test_screen_index_records_rebuild_the_shape_they_were_read_from():
    payload = gspm_payload()
    start = gspm.section_ranges(payload)[6][0]
    screens = ui_index.screen_slots(payload)
    trailer = screens[0]["trailer_offset"]
    slot = screens[0]["slots"][0]

    index = authoring.screen_index([trailer])
    header = int.from_bytes(payload[trailer + 1:trailer + 4], "little") - gspm.BASE
    rebuilt_trailer = authoring.screen_trailer(payload[trailer], header, [slot["offset"]])
    rebuilt_slot = authoring.screen_slot(
        slot["template"], slot["key_register_offset"], slot["program_offset"])

    assert index == payload[start:start + len(index)]
    assert rebuilt_trailer == payload[trailer:trailer + len(rebuilt_trailer)]
    assert rebuilt_slot == payload[slot["offset"]:slot["offset"] + 7]


def test_a_slot_that_opens_another_screen_is_not_offered_as_a_clone_source():
    sources = authoring.command_screen_sources(gspm_payload_with_device_menu())

    assert [(source["screen"], source["slot"]) for source in sources] == [(1, 0)]


def test_a_cloned_command_screen_reaches_a_newly_allocated_device():
    payload = gspm_payload()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device_report = authoring.add_command_device(payload, [signal])
    source = authoring.command_screen_sources(with_device)[0]

    result, report = authoring.add_command_screen(
        with_device,
        [list(zip(source["command_key_codes"], device_report["wrapper_object_ids"]))],
        sources=[source],
    )

    before = key_index.inspect(with_device)
    after = key_index.inspect(result)
    added = [item for item in after["bindings"] if item["screen"] == report["screen"]]
    assert report["screen"] == before["counts"]["screens"]
    assert after["counts"]["screens"] == before["counts"]["screens"] + 1
    assert [item["command_id"] for item in added] == [0x100]
    assert [item["device_ids"] for item in added] == [[0x101]]
    assert report["navigation"] == "unreferenced"
    assert gspm.validate(result)["ok"] is True


def test_a_cloned_command_screen_keeps_the_source_template_and_artwork():
    payload = gspm_payload()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device_report = authoring.add_command_device(payload, [signal])
    source = authoring.command_screen_sources(with_device)[0]

    result, report = authoring.add_command_screen(
        with_device,
        [list(zip(source["command_key_codes"], device_report["wrapper_object_ids"]))],
        sources=[source],
    )

    clone = ui_index.screen_slots(result)[report["screen"]]["slots"][0]
    assert clone["template"] == source["template"]
    assert clone["program_offset"] == source["program_offset"]
    assert report["artwork"] == "cloned-from-source-screen"


def test_a_command_screen_clone_refuses_to_leave_a_key_on_the_source_device():
    payload = gspm_payload()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, _report = authoring.add_command_device(payload, [signal])
    source = authoring.command_screen_sources(with_device)[0]

    with pytest.raises(ValueError, match="must rebind every command key"):
        authoring.add_command_screen(with_device, [[]], sources=[source])


def test_a_command_screen_clone_refuses_an_object_outside_section_11():
    payload = gspm_payload()
    source = authoring.command_screen_sources(payload)[0]

    with pytest.raises(ValueError, match="objects outside section 11"):
        authoring.add_command_screen(
            payload, [[(source["command_key_codes"][0], 9999)]], sources=[source])


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


def test_label_lines_are_spaced_and_centred_the_way_the_native_producer_spaced_them():
    assert screen_program.line_offsets(1) == [20]
    assert screen_program.line_offsets(2) == [15, 26]
    assert screen_program.line_offsets(3) == [9, 20, 31]


def test_a_relabelled_program_keeps_every_instruction_it_was_not_asked_to_change():
    payload = gspm_payload_with_command_screen()
    slot = ui_index.screen_slots(payload)[0]["slots"][0]
    before = ui_index.drawing_program(payload, slot["program_offset"])

    rendered = screen_program.render(payload, slot["program_offset"], ["A", "B"])

    at = int.from_bytes(payload[4:8], "little") - gspm.BASE - 2
    probe = relocation.repair_integrity(payload[:at] + rendered)
    after = ui_index.drawing_program(probe, at)
    assert [item["opcode"] for item in after["instructions"]] == [
        item["opcode"] for item in before["instructions"]]
    assert [item.get("target") for item in after["instructions"]] == [
        item.get("target") for item in before["instructions"]]
    assert screen_program.labelled(probe, at) == [["A"], ["B"]]


def test_a_label_wider_than_its_button_frame_is_refused_not_drawn_over_it():
    payload = gspm_payload_with_command_screen()
    slot = ui_index.screen_slots(payload)[0]["slots"][0]

    with pytest.raises(ValueError, match="does not fit the 20 pixel button frame"):
        screen_program.render(payload, slot["program_offset"], ["A" * 21, "B"])


def test_a_label_is_refused_when_the_image_has_no_glyph_for_a_character():
    payload = gspm_payload_with_command_screen()
    slot = ui_index.screen_slots(payload)[0]["slots"][0]

    with pytest.raises(ValueError, match="not established for this image"):
        screen_program.render(payload, slot["program_offset"], ["é", "B"])


def test_buttons_are_ordered_by_touch_geometry_not_key_register_order():
    payload = gspm_payload_with_command_screen()

    assert screen_program.key_button_order(payload, 0, [0xB0, 0xB1]) == [0xB1, 0xB0]


def test_a_relabelled_command_screen_names_the_commands_it_actually_fires():
    payload = gspm_payload_with_command_screen()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device = authoring.add_command_device(payload, [signal, signal])
    source = authoring.command_screen_sources(with_device)[0]
    order = screen_program.key_button_order(
        with_device, source["template"], sorted(source["command_key_codes"]))

    result, report = authoring.add_command_screen(
        with_device,
        [list(zip(source["command_key_codes"], device["wrapper_object_ids"]))],
        sources=[source],
        labels=[dict(zip(order, ["A", "B"]))],
    )

    assert report["artwork"] == "relabelled-clone"
    assert screen_program.labelled(result, report["program_offsets"][0]) == [["A"], ["B"]]
    assert screen_program.labelled(result, source["program_offset"]) == [["H"], ["y"]]
    assert gspm.validate(result)["ok"] is True


def test_a_relabelled_command_screen_requires_a_label_for_every_rebound_key():
    payload = gspm_payload_with_command_screen()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device = authoring.add_command_device(payload, [signal, signal])
    source = authoring.command_screen_sources(with_device)[0]

    with pytest.raises(ValueError, match="must label every rebound key"):
        authoring.add_command_screen(
            with_device,
            [list(zip(source["command_key_codes"], device["wrapper_object_ids"]))],
            sources=[source],
            labels=[{source["command_key_codes"][0]: "A"}],
        )


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
    return relocation.repair_integrity(bytes(payload))


def test_menu_row_lines_sit_where_the_native_producer_put_them():
    assert screen_program.menu_line_offsets(1) == [0]
    assert screen_program.menu_line_offsets(2) == [-6, 6]
    with pytest.raises(ValueError, match="no donor draws a 3 line"):
        screen_program.menu_line_offsets(3)


def test_a_menu_row_is_repointed_and_renamed_in_every_replica():
    payload = gspm_payload_with_menu_replicas()
    before = ui_index.device_menus(payload)
    assert before["counts"]["replica_menus"] == 2

    result, report = authoring.assign_menu_row(payload, 0, label="Hy")

    after = ui_index.device_menus(result)
    codec = glyph_codec.inspect(result)
    assert report["replicas"] == 2
    assert sorted(report["menu_screens"]) == [0, 2]
    assert after["counts"]["replica_menus"] == 2
    assert [glyph_codec.decode(bytes.fromhex(item), codec)
            for item in after["devices"][0]["glyph_lines"]] == ["Hy"]
    assert gspm.validate(result)["ok"] is True


def test_a_menu_row_label_is_refused_when_that_font_cannot_draw_it():
    payload = gspm_payload_with_menu_replicas()

    with pytest.raises(ValueError, match="this font cannot draw 'N'"):
        authoring.assign_menu_row(payload, 0, label="N")


def test_a_menu_row_change_must_name_what_it_changes():
    payload = gspm_payload_with_menu_replicas()

    with pytest.raises(ValueError, match="must give a target screen, a label, or both"):
        authoring.assign_menu_row(payload, 0)


def test_a_menu_row_cannot_open_a_screen_the_image_does_not_have():
    payload = gspm_payload_with_menu_replicas()

    with pytest.raises(ValueError, match="declares no screen 99"):
        authoring.assign_menu_row(payload, 0, target_screen=99)


def test_repointing_a_menu_row_opens_the_new_screen_from_every_replica():
    payload = gspm_payload_with_menu_replicas()

    result, report = authoring.assign_menu_row(payload, 0, target_screen=2)

    rows = [row for menu in ui_index.device_menus(result)["menus"]
            for row in menu["rows"]]
    assert report["target_screen"] == 2
    assert {row["target_screen"] for row in rows} == {2}
    assert report["relocation"]["repaired_pointers"] > 0
    assert gspm.validate(result)["ok"] is True


def test_renaming_a_menu_row_does_not_relocate_any_section():
    payload = gspm_payload_with_menu_replicas()

    _result, report = authoring.assign_menu_row(payload, 0, label="Hy")

    assert report["relocation"] is None


def gspm_payload_with_paged_menu(numbered: bool = True,
                                 command_screen: bool = False) -> bytes:
    """Two menu replicas whose full page can grow into a second one when numbered.

    With ``command_screen`` the device screen also becomes a numbered one-button
    command page, which is the shape a build clones its new pages from.
    """
    base = gspm_payload_with_device_menu()
    at = int.from_bytes(base[4:8], "little") - gspm.BASE - 2
    payload = bytearray(base[:at])
    _install_fonts(payload)

    # A fourth object opens screen 0, giving the second row a target with no commands.
    table = struct.unpack_from("<I", payload, 0x0C + 4 * 11)[0] - gspm.BASE
    spare = len(payload)
    payload += b"\x01\x00\x00\x7e"
    struct.pack_into("<H", payload, table, 4)
    payload[table + 11:table + 14] = (gspm.BASE + spare).to_bytes(3, "little")

    # A template whose two equal row zones sit above a differently sized softkey.
    template = len(payload)
    payload += b"\x03" + bytes(9)
    zones = []
    for index, (tag, y, width, height) in enumerate(
            ((0x30, 3016, 2600, 807), (0x31, 2144, 2600, 807), (0x33, 271, 1395, 1001))):
        zone = len(payload)
        payload += bytes(12)
        struct.pack_into("<HHHHB", payload, zone, 1257, width, y, height, tag)
        payload[zone + 9:zone + 12] = (gspm.BASE + zone).to_bytes(3, "little")
        zones.append(zone)
    for index, zone in enumerate(zones):
        payload[template + 1 + 3 * index:template + 4 + 3 * index] = (
            gspm.BASE + zone).to_bytes(3, "little")
    payload[0x220:0x224] = b"\x01" + (gspm.BASE + template).to_bytes(3, "little")

    frame = gspm.BASE + len(payload)
    payload += bytes([0, 20, 0, 24]) + bytes(2 * 20 * 24)
    prologue = len(payload)
    payload += b"\x10\x01"
    if numbered:
        payload += b"\x05\x17\x12\x12\x00"  # the total "1" at (23, 18)
    payload += b"\x17"

    screens = []
    registers = []
    for replica in range(2):
        program = len(payload)
        payload += (
            b"\x16" + (gspm.BASE + prologue).to_bytes(3, "little")
            + b"\x02\x06\x26" + frame.to_bytes(3, "little")
            + b"\x10\x01" + b"\x05\x3f\x39\x08\x3f\x00"      # "TY" in row 0
            + b"\x02\x06\x5c" + frame.to_bytes(3, "little")
            + b"\x05\x3f\x6f\x25\x34\x00"                    # "OK" in row 1
            + b"\x12\x00\x00\x00"
            + (b"\x05\x0d\x12\x12\x00" if numbered else b"")  # page "1" at (13, 18)
            + b"\x00")
        registers.append(program)
        screens.append(None)

    slots = []
    bodies = [b"\x03\xb0\x01\x00\x7f\xb1\x03\x00\x7f\xb3\x00\x00\x72"] * 2
    for replica, program in enumerate(registers):
        slot = len(payload)
        payload += b"\x00\x00\x00\x00" + (gspm.BASE + program).to_bytes(3, "little")
        trailer = len(payload)
        payload += (b"\x00" + (gspm.BASE + 0x80).to_bytes(3, "little")
                    + (1).to_bytes(2, "little") + (gspm.BASE + slot).to_bytes(3, "little"))
        slots.append(slot)
        screens[replica] = trailer

    if command_screen:
        title = len(payload)
        payload += (b"\x10\x01" + b"\x05\x06\x04\x08\x00"
                    + b"\x05\x17\x12\x12\x00" + b"\x17")
        program = len(payload)
        payload += (b"\x16" + (gspm.BASE + title).to_bytes(3, "little")
                    + b"\x02\x06\x26" + frame.to_bytes(3, "little")
                    + b"\x10\x01" + b"\x05\x1e\x3a\x08\x00"
                    + b"\x12\x00\x00\x00"
                    + b"\x05\x0d\x12\x12\x00"
                    + b"\x00")
        slot = len(payload)
        payload += b"\x00\x00\x00\x00" + (gspm.BASE + program).to_bytes(3, "little")
        trailer = len(payload)
        payload += (b"\x00" + (gspm.BASE + 0x80).to_bytes(3, "little")
                    + (1).to_bytes(2, "little") + (gspm.BASE + slot).to_bytes(3, "little"))
        payload[0x166:0x169] = (gspm.BASE + trailer).to_bytes(3, "little")
        slots.append(slot)
        bodies.append(b"\x01\xb0\x02\x00\x7f")

    # Section 9 holds every key register, as it does in both donors. Put it last so its
    # range covers the registers alone and nothing else rides along when it relocates.
    section9 = len(payload)
    struct.pack_into("<I", payload, 0x0C + 4 * 9, gspm.BASE + section9)
    for slot, body in zip(slots, bodies):
        payload[slot + 1:slot + 4] = (gspm.BASE + len(payload)).to_bytes(3, "little")
        payload += body

    device_trailer = int.from_bytes(payload[0x166:0x169], "little") - gspm.BASE
    struct.pack_into("<H", payload, 0x160, 3)
    for ordinal, trailer in enumerate((screens[0], device_trailer, screens[1])):
        payload[0x163 + 3 * ordinal:0x166 + 3 * ordinal] = (
            gspm.BASE + trailer).to_bytes(3, "little")
    return relocation.repair_integrity(bytes(payload))


def test_menu_row_zones_are_the_equally_sized_ones_not_the_softkey():
    payload = gspm_payload_with_paged_menu()
    zones = ui_index.touch_templates(payload)[0]

    rows = authoring.menu_row_zones(zones)

    assert [zone["key_code"] for zone in rows] == [0xB0, 0xB1]


def test_a_full_numbered_menu_grows_a_page_in_every_replica():
    payload = gspm_payload_with_paged_menu()
    before = ui_index.device_menus(payload)
    capacity = authoring.menu_capacity(payload)
    assert capacity["free_rows"] == 0
    assert capacity["every_page_numbered"] is True

    result, report = authoring.add_menu_row(payload, 2, "Hy")

    after = ui_index.device_menus(result)
    assert report["replicas"] == 2
    assert set(report["pages"].values()) == {2}
    assert after["counts"]["replica_menus"] == before["counts"]["replica_menus"]
    assert after["counts"]["replica_rows"] == before["counts"]["replica_rows"] + 2
    assert gspm.validate(result)["ok"] is True


def test_the_new_menu_page_states_the_new_total_on_every_page():
    payload = gspm_payload_with_paged_menu()

    result, _report = authoring.add_menu_row(payload, 2, "Hy")

    screens = ui_index.screen_slots(result)
    for ordinal in (0, 2):
        numbers = []
        for index, slot in enumerate(screens[ordinal]["slots"]):
            program = ui_index.drawing_program(result, slot["program_offset"])
            numbers.append(screen_program.page_indicator(
                result, slot["program_offset"], screen_program.PAGE_NUMBER_XY)["text"])
            total = screen_program.page_indicator(
                result, program["instructions"][0]["target"],
                screen_program.PAGE_TOTAL_XY)
            assert total["text"] == "2"
        assert numbers == ["1", "2"]


def test_an_unnumbered_menu_cannot_grow_a_page():
    payload = gspm_payload_with_paged_menu(numbered=False)

    assert authoring.menu_capacity(payload)["every_page_numbered"] is False
    with pytest.raises(ValueError, match="draws no page numbers"):
        authoring.add_menu_row(payload, 2, "Hy")


def test_a_command_screen_can_be_built_from_several_pages():
    payload = gspm_payload_with_command_screen(paged=True)
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device = authoring.add_command_device(payload, [signal] * 4)
    source = authoring.command_screen_sources(with_device)[0]
    keys = source["command_key_codes"]
    wrappers = device["wrapper_object_ids"]
    order = screen_program.key_button_order(with_device, source["template"], sorted(keys))

    result, report = authoring.add_command_screen(
        with_device,
        [list(zip(keys, wrappers[:2])), list(zip(keys, wrappers[2:]))],
        sources=[source, source],
        labels=[dict(zip(order, ["A", "B"])), dict(zip(order, ["C", "D"]))],
        title="Hy",
    )

    numbers = [
        screen_program.page_indicator(
            result, offset, screen_program.PAGE_NUMBER_XY)["text"]
        for offset in report["program_offsets"]
    ]
    assert report["pages"] == 2
    assert numbers == ["1", "2"]
    assert screen_program.screen_title(result, report["prologue_offset"]) == "Hy"
    assert screen_program.page_indicator(
        result, report["prologue_offset"], screen_program.PAGE_TOTAL_XY)["text"] == "2"
    assert [screen_program.labelled(result, offset)
            for offset in report["program_offsets"]] == [
        [["A"], ["B"]], [["C"], ["D"]]]
    assert len(ui_index.screen_slots(result)[report["screen"]]["slots"]) == 2
    assert gspm.validate(result)["ok"] is True


def test_every_page_of_a_command_screen_binds_its_own_commands():
    payload = gspm_payload_with_command_screen(paged=True)
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device = authoring.add_command_device(payload, [signal] * 4)
    source = authoring.command_screen_sources(with_device)[0]
    keys = source["command_key_codes"]
    wrappers = device["wrapper_object_ids"]

    result, report = authoring.add_command_screen(
        with_device,
        [list(zip(keys, wrappers[:2])), list(zip(keys, wrappers[2:]))],
        sources=[source, source],
    )

    added = [item for item in key_index.inspect(result)["bindings"]
             if item["screen"] == report["screen"]]
    assert sorted(item["command_id"] for item in added) == [0x100, 0x101, 0x102, 0x103]
    assert {item["slot"] for item in added} == {0, 1}


def test_an_unnumbered_source_cannot_build_a_multi_page_screen():
    payload = gspm_payload_with_command_screen()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    with_device, device = authoring.add_command_device(payload, [signal] * 4)
    source = authoring.command_screen_sources(with_device)[0]
    keys = source["command_key_codes"]
    wrappers = device["wrapper_object_ids"]

    with pytest.raises(ValueError, match="draw no page number"):
        authoring.add_command_screen(
            with_device,
            [list(zip(keys, wrappers[:2])), list(zip(keys, wrappers[2:]))],
            sources=[source, source],
        )


def test_a_font_is_completed_only_from_its_own_typeface():
    payload = gspm_payload_with_menu_replicas()

    available = font_index.completions(payload)

    assert available[0]["typeface"] == [1]
    assert available[1]["typeface"] == [0]
    assert available[1]["fill"] == {0x3C: font_index.fonts(payload)[0]["glyphs"][0x3C][
        "pointer"]}
    assert available[0]["fill"] == {}


def test_completing_a_font_only_fills_slots_that_were_empty():
    payload = gspm_payload_with_menu_replicas()
    before = font_index.fonts(payload)

    result, report = font_index.complete(payload)

    after = font_index.fonts(result)
    assert report["added"] == 1
    assert report["disputed"] == {}
    assert set(after[1]["glyphs"]) == set(before[1]["glyphs"]) | {0x3C}
    for old, new in zip(before, after):
        for code, item in old["glyphs"].items():
            assert new["glyphs"][code]["pointer"] == item["pointer"]
    assert gspm.validate(result)["ok"] is True


def test_a_completed_font_can_draw_a_label_it_refused_before():
    payload = gspm_payload_with_menu_replicas()
    with pytest.raises(ValueError, match="this font cannot draw 'N'"):
        authoring.assign_menu_row(payload, 0, label="N")

    completed, _report = font_index.complete(payload)

    result, _report = authoring.assign_menu_row(completed, 0, label="N")
    codec = glyph_codec.inspect(result)
    assert [glyph_codec.decode(bytes.fromhex(item), codec)
            for item in ui_index.device_menus(result)["devices"][0]["glyph_lines"]] == ["N"]


def test_completing_fonts_leaves_every_label_the_image_already_draws():
    payload = gspm_payload_with_menu_replicas()
    before = ui_index.device_menus(payload)

    result, _report = font_index.complete(payload)

    assert ui_index.device_menus(result)["counts"] == before["counts"]
    assert glyph_codec.inspect(result)["repertoire"] == glyph_codec.inspect(
        payload)["repertoire"]


def test_fonts_of_different_heights_are_not_the_same_typeface():
    payload = gspm_payload_with_menu_replicas()
    one, other = font_index.fonts(payload)[:2]

    assert font_index.same_typeface(one, other) is True
    assert font_index.same_typeface(one, {**other, "height": one["height"] + 1}) is False


def gspm_payload_ready_to_author() -> bytes:
    """A paged menu plus a numbered one-button command screen to clone pages from."""
    return gspm_payload_with_paged_menu(command_screen=True)


def test_a_page_layout_uses_the_slot_shapes_the_image_has():
    assert build.page_layout([6, 4, 2], 16) == [6, 6, 4]
    assert build.page_layout([6, 4, 2], 6) == [6]
    assert build.page_layout([2], 6) == [2, 2, 2]
    assert build.page_layout([6, 4, 2], 7) is None
    assert build.page_layout([], 4) is None


def test_a_plan_keeps_devices_the_baseline_already_has():
    payload = gspm_payload_ready_to_author()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    project = {"devices": [
        {"label": "TY", "signals": {"Hy": signal}},
        {"label": "", "signals": {"Hy": signal}},
        {"label": "Hy", "signals": {}},
    ]}

    steps = build.plan(project, payload)

    assert steps["unchanged_devices"] == ["TY"]
    assert steps["add_devices"] == []
    assert [item["reason"] for item in steps["refused"]] == [
        "a device needs a name", "a device needs at least one command"]


def test_a_plan_refuses_a_name_the_image_cannot_draw():
    payload = gspm_payload_ready_to_author()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]

    steps = build.plan({"devices": [{"label": "Ny\u00e9", "signals": {"Hy": signal}}]}, payload)

    assert steps["add_devices"] == []
    assert "cannot draw" in steps["refused"][0]["reason"]


def test_a_build_adds_a_device_the_menu_reaches_and_accounts_for_every_change():
    payload = gspm_payload_ready_to_author()
    signal = command_index.portable_devices(command_index.inspect(payload))[0]["signals"][
        "Command 00"]
    project = {"devices": [{"label": "Hy", "signals": {"Hu": signal, "Ty": signal}}]}
    steps = build.plan(project, payload)
    assert [item["name"] for item in steps["add_devices"]] == ["Hy"]

    result, report = build.apply(payload, project, steps)

    menus = inventory.inspect(result)["ui"]["device_menus"]
    assert report["steps"] == [
        "complete-fonts", "add-command-device", "add-command-screen", "add-menu-row"]
    assert report["devices"] == {"before": 1, "after": 2}
    assert report["menu_replicas"]["after"] == report["menu_replicas"]["before"]
    assert report["rejected"]["after"] == report["rejected"]["before"]
    assert "Hy" in [item.get("label") for item in menus["devices"]]
    assert report["changed_bytes"] > 0
    assert gspm.validate(result)["ok"] is True


def test_a_menu_row_is_removed_from_every_replica_and_orphans_its_screen():
    payload = gspm_payload_ready_to_author()
    before = ui_index.device_menus(payload)

    result, report = authoring.remove_menu_row(payload, 0)

    after = ui_index.device_menus(result)
    assert report["replicas"] == 2
    assert report["orphaned_screen"] == 1
    assert after["counts"]["replica_rows"] == before["counts"]["replica_rows"] - 2
    assert after["counts"]["replica_menus"] == before["counts"]["replica_menus"]
    assert after["devices"][0]["target_screen"] is None
    assert gspm.validate(result)["ok"] is True


def test_removing_a_row_leaves_the_device_and_its_commands_in_the_image():
    payload = gspm_payload_ready_to_author()
    before = command_index.inspect(payload)

    result, _report = authoring.remove_menu_row(payload, 0)

    after = command_index.inspect(result)
    assert after["counts"]["devices"] == before["counts"]["devices"]
    assert after["counts"]["decoded_commands"] == before["counts"]["decoded_commands"]


def test_a_freed_row_band_is_filled_rather_than_growing_a_page():
    payload = gspm_payload_ready_to_author()
    emptied, _report = authoring.remove_menu_row(payload, 0)
    assert authoring.menu_capacity(emptied)["free_rows"] == 2
    slots = len(ui_index.screen_slots(emptied)[0]["slots"])

    result, report = authoring.add_menu_row(emptied, 1, "Hy")

    assert report["mode"] == "fill-menu-row"
    assert len(ui_index.screen_slots(result)[0]["slots"]) == slots
    assert ui_index.device_menus(result)["counts"]["replica_rows"] == (
        ui_index.device_menus(emptied)["counts"]["replica_rows"] + 2)
    assert gspm.validate(result)["ok"] is True


def test_a_menu_row_removal_that_would_empty_a_page_is_refused():
    payload = gspm_payload_with_menu_replicas()

    with pytest.raises(ValueError, match="with no rows"):
        authoring.remove_menu_row(payload, 0)


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
    return relocation.repair_integrity(bytes(payload))


def test_an_activity_row_is_owned_by_the_activity_it_starts():
    payload = gspm_payload_with_activity_menu()

    report = ui_index.activity_rows(payload)

    assert report["counts"] == {"screens": 1, "rows": 1, "activities": 1}
    assert report["rejected"] == {}
    assert report["rows"][0]["activity"] == 2
    assert report["rows"][0]["screen"] == 1
    assert report["rows"][0]["key_code"] == 0xB1


def test_renaming_an_activity_row_changes_its_text_and_nothing_it_starts():
    payload = gspm_payload_with_activity_menu()
    before = ui_index.activity_rows(payload)

    result, report = authoring.rename_activity_row(payload, 2, "Hy")

    after = ui_index.activity_rows(result)
    codec = glyph_codec.inspect(result)
    assert report["activity"] == 2
    assert after["counts"] == before["counts"]
    assert after["rows"][0]["object_index"] == before["rows"][0]["object_index"]
    assert [glyph_codec.decode(bytes.fromhex(line["glyphs"]), codec)
            for line in after["rows"][0]["lines"]] == ["Hy"]
    assert gspm.validate(result)["ok"] is True


def test_renaming_an_activity_the_menu_does_not_show_is_refused():
    payload = gspm_payload_with_activity_menu()

    with pytest.raises(ValueError, match="no Activities-menu row starts activity 9"):
        authoring.rename_activity_row(payload, 9, "Hy")


def test_an_activity_started_from_a_context_row_is_named():
    payload = gspm_payload_with_activity_menu()

    assert authoring.activity_start_contexts(payload) == {}


def test_deleting_an_activity_takes_it_off_the_menu_and_names_what_is_left():
    payload = gspm_payload_with_activity_menu()
    contexts = len(activity_index.contexts(payload))

    result, report = authoring.delete_activity(payload, 2)

    after = ui_index.activity_rows(result)
    assert after["counts"]["rows"] == 0
    assert report["orphaned"]["context"] == 2
    assert report["orphaned"]["objects"] == [3]
    # Nothing is renumbered: the context table keeps its length and the activity's
    # own objects stay where they were.
    assert len(activity_index.contexts(result)) == contexts
    assert gspm.validate(result)["ok"] is True


def test_deleting_an_activity_leaves_the_device_menu_alone():
    payload = gspm_payload_with_activity_menu()
    before = ui_index.device_menus(payload)["counts"]

    result, _report = authoring.delete_activity(payload, 2)

    assert ui_index.device_menus(result)["counts"] == before


def test_deleting_an_activity_the_menu_does_not_show_is_refused():
    payload = gspm_payload_with_activity_menu()

    with pytest.raises(ValueError, match="no Activities-menu row starts activity 9"):
        authoring.delete_activity(payload, 9)
