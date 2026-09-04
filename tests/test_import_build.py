"""Importing a configuration, and building one back.

The failures this guards against all look the same from outside: the build succeeds, the
config verifies, and something is quietly missing or wrong. Each test below is a thing
that was silently lost at least once.
"""
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import entries_of

from afterglow import device_json, ir_signal, library
from afterglow.backends.harmony_pk import native_registry, ssir
from afterglow.backends.harmony_pk.builder import protocols
from afterglow.backends.harmony_pk.builder.activities import _default_hard_buttons
from afterglow.backends.harmony_pk.importer import protocol_map
from afterglow.importer import build_project


@pytest.fixture
def project(a_config, unpacked):
    tree = unpacked(a_config)
    return build_project(str(tree)), tree


def test_import_identifies_every_protocol(configs, unpacked):
    """A block the library cannot identify means devices fall back to a guess.

    Every block is either recognized as a generated portable family or extracted into
    transient backend evidence. No shipped donor-block catalogue is involved.
    """
    for index, config in enumerate(configs):
        tree = unpacked(config, f"p{index}")
        from afterglow.backends.harmony_pk import irproto
        payload = irproto.read_payload(str(tree / "userconfig" / "IrProto.bin"))
        blocks, _starts = irproto.parse_proto(payload)
        identified = protocol_map(str(tree))
        assert len(identified) == len(blocks), (
            f"{config.name}: {len(blocks) - len(identified)} unidentified block(s)")


def test_import_never_reads_a_shipped_native_catalogue(a_config, unpacked, monkeypatch):
    from afterglow.backends.harmony_pk import protocol_json

    tree = unpacked(a_config, "catalog-free")
    monkeypatch.setattr(
        protocol_json, "catalog",
        lambda: (_ for _ in ()).throw(AssertionError("native catalogue was read")),
    )

    assert protocol_map(str(tree))


def test_builder_refuses_an_unknown_protocol():
    """Captured codes with no known protocol must raise, not default to NEC.

    Defaulting pairs real command bytes with the wrong timing: the config builds, flashes
    and transmits IR that looks right and is not.
    """
    with pytest.raises(ValueError, match="no known protocol"):
        protocols.validate([{"id": "1", "label": "Mystery",
                             "raw_codes": {"X": "0x0400"}, "commands": []}])


def test_raw_only_device_needs_no_protocol():
    """A device whose commands are all recorded waveforms uses no protocol block."""
    protocols.validate([{"id": "1", "label": "Lights",
                         "raw_codes": {"X": ssir.make_code(0)}, "commands": []}])


def test_rebuild_preserves_devices_and_activities(project, build):
    proj, tree = project
    if not proj["devices"]:
        pytest.skip("config has no devices")
    out = build(proj)
    xml = entries_of(out).read("userconfig/UserConfiguration.xml").decode()
    for device in proj["devices"]:
        assert f"<Device><Id>{device['id']}</Id>" in xml
    for activity in proj["activities"]:
        assert f"<Activity><Id>{activity['id']}</Id>" in xml


def test_import_and_rebuild_preserve_the_all_off_label(configs, unpacked, build):
    for index, config in enumerate(configs):
        tree = unpacked(config, f"off-label-{index}")
        original = ET.parse(
            tree / "userconfig" / "UserConfiguration.xml").getroot()
        label = original.find("Activity[Id='-1']/Presentation/Label")
        if label is None or label.text in (None, "PowerOff"):
            continue
        project = build_project(str(tree))
        assert project["power_off_label"] == label.text
        rebuilt = ET.fromstring(entries_of(
            build(project, f"off-label-{index}.ezhex")).read(
                "userconfig/UserConfiguration.xml"))
        assert rebuilt.find("Activity[Id='-1']/Presentation/Label").text == label.text
        return
    pytest.skip("no real configuration has a localized all-off label")


def test_import_does_not_expand_implied_hard_keys_into_macros(project):
    proj, _tree = project
    by_id = {device["id"]: device for device in proj["devices"]}
    for activity in proj["activities"]:
        implied = _default_hard_buttons(activity, by_id)
        for slot, macro in (activity.get("hard_macros") or {}).items():
            if len(macro) != 1 or macro[0][0] != "command":
                continue
            target = tuple(macro[0][1:3])
            modifier = macro[0][3] if len(macro[0]) > 3 else "Press"
            assert implied.get(slot) != target or modifier != "Hold", (
                f"{activity['label']!r} stores implied key {slot!r} as a macro")


def test_rebuild_preserves_raw_ir(configs, unpacked, build):
    """Raw waveforms and the codes pointing at them must both survive.

    Byte 0 carries the protocol index for encoded commands, but overwriting it on a raw
    code destroys the 0xFFFF marker and every raw command vanishes without an error.
    """
    for index, config in enumerate(configs):
        tree = unpacked(config, f"raw{index}")
        proj = build_project(str(tree))
        original = ssir.read(str(tree / "userconfig" / "SsIr.bin"))
        if not original:
            continue
        out = build(proj, f"raw{index}.ezhex")
        archive = entries_of(out)
        assert ssir.parse(archive.read("userconfig/SsIr.bin")) == original
        xml = archive.read("userconfig/UserConfiguration.xml").decode()
        codes = re.findall(r"<Code>(0xFFFF[0-9A-Fa-f]{4})</Code>", xml)
        assert codes, f"{config.name}: raw codes disappeared"
        assert all(ssir.raw_index(code) < len(original) for code in codes)
        return
    pytest.skip("no config uses raw IR")


def test_import_gives_every_command_a_discriminated_signal(project):
    proj, _tree = project
    for device in proj["devices"]:
        command_names = {command[0] for command in device["commands"]}
        assert set(device.get("signals") or {}) == command_names
        for signal in device["signals"].values():
            ir_signal.validate(signal)
            assert signal["kind"] in ("protocol", "waveform", "backend-opaque")


def test_non_generated_native_commands_carry_their_transient_definition(project):
    proj, _tree = project
    generated = set(native_registry.catalog())
    opaque = [
        signal["native"]["harmony-pk"]
        for device in proj["devices"]
        for signal in device.get("signals", {}).values()
        if signal["kind"] == "backend-opaque"
        and signal["native"]["harmony-pk"].get("protocol_block_id")
        and signal["native"]["harmony-pk"]["protocol_block_id"] not in generated
    ]
    if not opaque:
        pytest.skip("config contains no non-generated native protocol commands")
    for native in opaque:
        assert native["protocol_definition"]["id"] == native["protocol_block_id"]
        assert native["protocol_definition"]["origin"] == "imported-irproto"


def test_raw_commands_declare_protocol_minus_one(configs, unpacked, build):
    for index, config in enumerate(configs):
        tree = unpacked(config, f"neg{index}")
        proj = build_project(str(tree))
        if not any(d.get("raw_ir") for d in proj["devices"]):
            continue
        xml = entries_of(build(proj, f"neg{index}.ezhex")).read(
            "userconfig/UserConfiguration.xml").decode()
        raw_count = len(re.findall(r"<Code>0xFFFF", xml))
        assert len(re.findall(r"<Protocol>-1</Protocol>", xml)) == raw_count
        return
    pytest.skip("no config uses raw IR")


def test_properties_survive_a_rebuild(project, build):
    """Device and activity <Property> entries were dropped entirely once."""
    proj, _tree = project
    wanted = {name for device in proj["devices"]
              for name in (device.get("properties") or {})}
    wanted |= {name for activity in proj["activities"]
               for name in (activity.get("properties") or {})}
    if not wanted:
        pytest.skip("config has no properties")
    xml = entries_of(build(proj)).read("userconfig/UserConfiguration.xml").decode()
    present = set(re.findall(r'<Property name="([^"]+)"', xml))
    assert wanted <= present, f"lost: {sorted(wanted - present)}"


def test_time_format_is_written_to_both_homes(project, build):
    """The clock lives in the XML *and* in platformconfig; the remote reads the file."""
    proj, _tree = project
    proj["settings"]["time_format"] = "Civilian"
    archive = entries_of(build(proj))
    xml = archive.read("userconfig/UserConfiguration.xml").decode()
    dat = archive.read("platformconfig/system_timeformat.dat").decode().strip()
    assert re.search(r'<Property name="TimeDisplayFormat">([^<]*)<', xml).group(1) == dat


def test_scaffold_documentation_never_ships(project, build):
    """A README dropped beside a scaffold once got packed into the flashed config."""
    proj, _tree = project
    names = entries_of(build(proj)).namelist()
    assert not [n for n in names if n.lower().endswith(".md")]


def test_rf_map_never_references_a_missing_device(project, build):
    proj, _tree = project
    ids = {d["id"] for d in proj["devices"]}
    xml = entries_of(build(proj)).read("platformconfig/XmlUserRfSetting.xml").decode()
    for mapped in re.findall(r"<UserDeviceId>(\d+)</UserDeviceId>", xml):
        assert mapped in ids, f"RF map points at absent device {mapped}"


# the library
def test_device_fingerprint_ignores_naming_and_position():
    """The same hardware under two names, and after a rebuild renumbers its tables,
    must be one entry."""
    base = {"id": "1", "label": "TV Samsung", "protocol": "aaaaaaaaaaaa",
            "raw_codes": {"Power": "0x0400AA", "Up": "0x0400BB"}, "commands": []}
    renamed = {**base, "label": "la télé", "id": "2"}
    renumbered = {**base, "protocol": None,
                  "raw_codes": {"Power": "0x0700AA", "Up": "0x0700BB"}}
    assert library.device_fingerprint(base) == library.device_fingerprint(renamed)
    assert library.device_fingerprint(base) == library.device_fingerprint(renumbered)


def test_different_devices_fingerprint_differently():
    a = {"id": "1", "commands": [["Power"]], "signals": {
        "Power": ir_signal.protocol_signal("nec1", {"address": 4, "command": 0xAA})}}
    b = {"id": "1", "commands": [["Power"]], "signals": {
        "Power": ir_signal.protocol_signal("nec1", {"address": 4, "command": 0xBB})}}
    assert library.device_fingerprint(a) != library.device_fingerprint(b)


def test_learning_is_idempotent(project, tmp_path):
    proj, tree = project
    shelf = tmp_path / "library"
    library.learn(proj, tree, library=shelf)          # populates the shelf
    second = library.learn(proj, tree, library=shelf)
    assert not second["devices"], "re-import created duplicate devices"
    assert not second["protocols"], "re-import created duplicate protocols"
    assert not second["captures"], "re-import created duplicate captures"
    # Every device is recognised the second time. Not compared against the count of
    # *new* entries from the first run: two identical devices in one config (a pair of
    # matching televisions, say) correctly collapse to a single library entry.
    assert len(second["known_devices"]) == len(proj["devices"])


def test_names_have_no_primary(project, tmp_path):
    """Every name a device is known by is equal - no label/alias split."""
    proj, tree = project
    if not proj["devices"]:
        pytest.skip("config has no devices")
    shelf = tmp_path / "library"
    library.learn(proj, tree, library=shelf)
    renamed = {**proj, "devices": [{**proj["devices"][0], "label": "Another Name"}]}
    library.learn(renamed, tree, library=shelf)
    import json
    for path in (shelf / "devices").glob("*.json"):
        spec = json.loads(path.read_text())
        assert "label" not in spec and "also_known_as" not in spec
        if len(device_json.names(spec)) > 1:
            assert "Another Name" in device_json.names(spec)
            return
    pytest.fail("the second name was not recorded")


def test_a_configuration_imports_with_no_protocols_installed(a_config, unpacked,
                                                             tmp_path, monkeypatch,
                                                             request):
    """Everything a configuration needs is inside the configuration.

    This is the property that makes "read one remote, write another" possible: importing
    must not depend on a protocol library, because every protocol the file uses is
    described by the file's own IrProto blocks.

    It did not hold. Three separate places assumed the library was populated - the block
    recognition catalogue and the Code-codec map both *emitted* every shipped protocol to
    build themselves, and the semantic decoder produced signals naming `nec1` and
    `rc6-mce` with no definition of either carried, giving a project that imported
    cleanly and could not be built.
    """
    import json

    from afterglow import ir_protocol
    from afterglow.backends.harmony_pk import importer, native_registry

    empty = tmp_path / "no-protocols"
    empty.mkdir()
    monkeypatch.setattr(ir_protocol, "LIBRARY", empty)

    # Those caches are keyed on nothing, so they hold whichever library was current when
    # they were first filled. Clearing only on the way in leaves an *empty* registry
    # cached for every test that runs afterwards.
    def _clear():
        native_registry._generated.cache_clear()
        native_registry.code_codecs.cache_clear()

    _clear()
    request.addfinalizer(_clear)

    project = importer._build_project_harmony_pk(str(unpacked(a_config)))

    installed = set(ir_protocol.catalog(empty))
    assert not installed, "the point of this test is an empty library"

    dangling = []
    kinds = {}
    for device in project["devices"]:
        inline = set(device.get("portable_protocol_definitions") or {})
        for name, signal in (device.get("signals") or {}).items():
            kinds[signal["kind"]] = kinds.get(signal["kind"], 0) + 1
            if signal["kind"] == "protocol" and signal["protocol"] not in inline:
                dangling.append(f"{device.get('label')}/{name}:{signal['protocol']}")
    assert not dangling, (
        f"the project references protocols nothing defines: {dangling[:5]}")
    assert kinds.get("backend-opaque", 0) == 0, (
        f"every command must convert, not fall back: {kinds}")
    assert kinds.get("protocol", 0) > 0
    json.dumps(project)          # a portable project must be serialisable as-is
