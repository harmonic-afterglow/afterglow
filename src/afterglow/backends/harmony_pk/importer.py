"""Import an extracted Harmony PK XML tree into the portable project model.

Native XML, IrProto indexes and SsIr table positions exist only while this module reads
them. Known commands leave as semantic protocol signals, learned commands as portable
waveforms, and undecoded commands as explicitly backend-opaque evidence.
"""
import xml.etree.ElementTree as ET
import hashlib
import json
import os
import glob
import html

from ... import ir_signal
from ...preferences import read as read_preferences
from ...rf import extract_rf
from . import ssir, states as states_mod

def parse_action_id(action_id):
    if not action_id: return None, None
    parts = action_id.split('_')
    if len(parts) >= 2:
        return parts[0], '_'.join(parts[1:-1])
    return None, None

def parse_action(action_elem):
    """One <Action> -> an action step, or None if it is not one we can express.

    Four of the firmware's five operations are represented (SendFlush appears in no
    real config, so there is nothing to import). Each one dropped here is a step that
    silently disappears from a macro, an activity's enter actions, or its leave
    actions - which is how a Hold became a Press and a "set the TV to HDMI 1" step
    vanished from the middle of a sequence.
    """
    op = action_elem.find('Operation')
    if op is None: return None
    op_name = op.find('Name').text

    def param(name):
        found = op.find(f'Parameter[@name="{name}"]')
        return found.text if found is not None else None

    if op_name == 'SendCommand':
        did, cmd = param("DeviceId"), param("Command")
        if did is None or cmd is None:
            return None
        # Modifier is part of the step: Press and Hold are different behaviours, and
        # Hold is the more common of the two in real configurations.
        #
        # So is Duration: a `Press` carrying `Duration=2000` is a two-second hold. Four
        # appear in the donor configurations, one of them the Panasonic TX-P42VT20E's
        # power off, a set that needs a long press to turn off at all. Discarding it
        # turns that into a tap that does nothing.
        modifier = param("Modifier") or "Press"
        duration = param("Duration")
        step = ["command", did, html.unescape(cmd)]
        if duration is not None and duration.isdigit() and int(duration) > 0:
            return step + [modifier, int(duration)]
        return step + [modifier] if modifier != "Press" else step
    elif op_name == 'SendDelay':
        ms = param("Delay")
        return ["delay", param("DeviceId"), int(ms)] if ms else None
    elif op_name == 'SetValue':
        did, state, val = param("DeviceId"), param("State"), param("Value")
        if did is None or state is None or val is None:
            return None
        # Any state, not just Input: a television is switched by setting InputType, so
        # narrowing this to Input would discard those steps.
        if state == "Input":
            return ["input", did, html.unescape(val)]
        return ["state", did, state, html.unescape(val)]
    elif op_name == 'SendNumber':
        val = param("Value")
        return ["number", param("DeviceId"), val] if val else None
    return None




def protocol_table(extracted_dir):
    """Return runtime block identities and transient unknown-block definitions.

    Generated portable families are recognized semantically by their VM-proven native
    output. Everything else is extracted from this very payload and made self-contained;
    importing a remote therefore does not require a shipped donor-block catalogue.
    """
    path = os.path.join(extracted_dir, "userconfig", "IrProto.bin")
    if not os.path.exists(path):
        return {}, {}
    from . import irproto, native_registry, protocol_json
    try:
        payload = irproto.read_payload(path)
        blocks, starts = irproto.parse_proto(payload)
    except Exception as exc:
        print("Warning: failed to parse IrProto.bin:", exc)
        return {}, {}
    generated = native_registry.catalog()
    found = {}
    definitions = {}
    unusable: dict[str, str] = {}
    for index, (block, position) in enumerate(zip(blocks, starts)):
        for block_id, spec in generated.items():
            if protocol_json.encode(spec, position) == block:
                found[index] = block_id
                break
        else:
            try:
                definition = protocol_json.extract_definition(
                    block, payload, position,
                    name=f"Imported native protocol {index}")
            except ValueError as exc:
                # One unusable block must not cost the whole configuration. This function
                # already tolerates a malformed *table* with a warning; letting a single
                # unrecognised *block* abort the import was the opposite policy applied
                # to the smaller failure, and it cost a real config: `my-remote.ezhex`
                # has seven blocks, one of which the carrier VM also refuses to run, and
                # importing it returned nothing at all rather than the other six devices.
                #
                # Record the block by its own digest so commands that use it keep a
                # stable identity and stay backend-opaque. They carry their original
                # Code, so they survive a round trip; the builder refuses them by name
                # if someone later tries to rebuild that device.
                block_id = hashlib.sha256(block).hexdigest()[:12]
                print(f"Warning: protocol block {index} ({block_id}) cannot be made "
                      f"self-contained: {exc}. Its commands stay native-only.")
                unusable[block_id] = str(exc)
                found[index] = block_id
                continue
            block_id = definition["id"]
            prior = definitions.get(block_id)
            if (prior is not None
                    and protocol_json.encode(prior) != protocol_json.encode(definition)):
                raise ValueError(f"conflicting imported native protocol {block_id}")
            found[index] = block_id
            if prior is None:
                definitions[block_id] = definition
    _warn_unrunnable_blocks(extracted_dir, payload, found)
    return found, definitions


def _report_unpromotable(unpromotable: dict[str, tuple[str, int]]) -> None:
    """Say loudly when a dumped protocol block would not become a portable one.

    Every native block in this project is meant to be an *intermediate*: importing a
    configuration converts it to a portable protocol definition, and building emits from
    that. Conversion is proved rather than assumed - `promote()` runs the source block and
    the rebuilt one through the carrier VM and requires the same emission at several
    held-key counts - and it succeeds on all 29 blocks across the donor configurations
    here and on all 675 protocol families the Logitech archive defines.

    So a failure is not an expected shape this tool does not handle yet. It is a defect,
    in a construct nothing available here contains, and the only way it gets fixed is if
    the person holding that file says so.

    Swallowing the error imports the commands as opaque native codes with nothing
    reporting that a conversion failed. They are still imported - refusing would leave
    someone unable to read their own remote for the sake of a purity the file cannot be
    blamed for - but the failure has to be impossible to miss.
    """
    if not unpromotable:
        return
    commands = sum(count for _reason, count in unpromotable.values())
    print()
    print("=" * 72)
    print(f"ERROR: {len(unpromotable)} protocol block(s) in this configuration could not "
          f"be converted")
    print(f"       to a portable protocol, affecting {commands} command(s).")
    print()
    for block_id, (reason, count) in sorted(unpromotable.items()):
        print(f"  block {block_id} ({count} command(s))")
        print(f"      {reason}")
    print()
    print("  This is a bug in Afterglow, not in your remote or your configuration.")
    print("  Every block in every configuration and every protocol family tested so far")
    print("  converts, so yours contains something no available sample does.")
    print()
    print("  Please open an Issue in the Afterglow repository and attach the .ezhex you")
    print("  imported. That file is the only way this can be diagnosed and fixed.")
    print()
    print("  Your commands were still imported and will still work on this remote. They")
    print("  are carried as native codes, which means they cannot be moved to a different")
    print("  remote until the conversion is fixed.")
    print("=" * 72)
    print()


def _warn_unrunnable_blocks(extracted_dir, payload, found) -> None:
    """Report blocks whose own Codes will not execute in our carrier VM.

    Block 1 of `my-remote.ezhex` declares a 109-bit data frame while all 65 of its Codes
    carry 32 bits, so the VM runs out of command data. **The VM is right and the block is
    malformed**, on two independent grounds:

    * Across every configuration available here, a data frame wider than 64 bits appears
      only in `my-remote.ezhex` and `ui-test-manual.ezhex` (109 bits) and in
      `test_remote_step1_mod.ezhex` (65,519 - plainly garbage). No pristine Logitech dump
      contains one.
    * `harmony900tools`, written independently against the same format, carries a code as
      a `uint64_t` and converts it with `u64tobits(bitCount, data)`. A 109-bit data frame
      cannot be represented in that model at all.

    That write-up also confirms the element layout Afterglow uses, field for field: bit
    count, toggle position, frame period, Ctrl0/Ctrl1 (our alphabet size and words per
    symbol), then Payload/SoF/EoF pointers. Their offsets are quoted `+13` where this project's are
    `+5` purely because their raw view keeps the 8-byte outer header we strip first.

    Still a warning rather than a refusal, but for a different reason than first written:
    rebuilding emits the same block with the same Codes, so it reproduces exactly the
    behaviour the file already had and makes nothing worse, while refusing would drop a
    whole device. The commands are preserved either way.
    """
    import collections
    import xml.etree.ElementTree as ET

    from . import ir_vm

    path = os.path.join(extracted_dir, "userconfig", "UserConfiguration.xml")
    if not os.path.exists(path):
        return
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    per = collections.defaultdict(list)
    for command in root.iter("Command"):
        data = command.find("Data")
        if data is None:
            continue
        index, code = data.find("Protocol"), data.find("Code")
        if index is not None and code is not None and code.text:
            per[(index.text or "").strip()].append(code.text.strip())

    for index, block_id in sorted(found.items()):
        codes = per.get(str(index), [])
        if not codes:
            continue
        failures = 0
        for code in codes:
            try:
                ir_vm.simulate_transmission(payload, code)
            except Exception:
                failures += 1
        if failures == len(codes):
            print(f"Warning: protocol block {index} ({block_id}) is malformed - none of "
                  f"its {failures} commands execute in the carrier VM, because the block "
                  "asks for more data bits than its Codes carry. They are imported and "
                  "rebuilt unchanged, so nothing is lost and nothing is made worse, but "
                  "this device is unlikely to have ever worked on the remote.")


def protocol_map(extracted_dir):
    """``{runtime index: block id}`` for compatibility with reporting callers."""
    return protocol_table(extracted_dir)[0]


def action_lists(extracted_dir):
    """`{name: [action-step, ...]}` from ActionLists.xml.

    A soft button can point at a named ActionList instead of a single command - that is
    how a macro button ("TV + Guide") is stored. Without reading these, such buttons are
    seen as unparseable and silently dropped.
    """
    path = os.path.join(extracted_dir, "userconfig", "ActionLists.xml")
    if not os.path.exists(path):
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print("Warning: failed to parse ActionLists.xml:", exc)
        return {}
    out = {}
    for lst in root.findall("ActionList"):
        name = lst.attrib.get("name")
        steps = [step for step in (parse_action(a) for a in lst.findall("Action")) if step]
        if name and steps:
            out[name] = steps
    return out


class _HarmonyPkImport:
    """One extracted Harmony PK tree, read into the portable project model.

    The steps below were a single 440-line function. Its locals - the protocol table,
    the macro map, the recorded waveform table, the promoted definitions - were each
    needed by several steps at once, which is what kept them in one scope. As fields
    they can be read one step at a time, and the blocks this refuses to promote have
    somewhere to be counted rather than being dropped silently.

    Format reference: docs/harmony_pk/configuration.md
    """

    def __init__(self, extracted_dir, out_file=None):
        self._extracted_dir = extracted_dir
        # Blocks this import could not promote to a portable definition, by block id:
        # why, and how many Codes selected it. Reported, never discarded quietly.
        self.rejects: dict[str, tuple[str, int]] = {}
        xml_path = os.path.join(self._extracted_dir, 'userconfig', 'UserConfiguration.xml')
        tree = ET.parse(xml_path)
        self._root = tree.getroot()


        base = os.path.basename(os.path.normpath(self._extracted_dir)).replace('_extracted', '')
        self._project = {
            "devices": [],
            "activities": [],
            "assets": [],
            "settings": {
                "out_file": out_file or (base + "_mod.ezhex"),
            }
        }
        # Which IrProto block each runtime protocol index refers to, resolved once.
        self._ir_proto_map, self._imported_protocols = protocol_table(self._extracted_dir)
        self._macros = action_lists(self._extracted_dir)
        # Recorded waveforms, for commands no protocol describes. Carried with the device
        # that uses them: without this its buttons import as codes pointing at nothing.
        ssir_path = os.path.join(self._extracted_dir, "userconfig", "SsIr.bin")
        try:
            self._raw_waveforms = ssir.read(ssir_path) if os.path.exists(ssir_path) else []
        except ValueError as exc:
            print("Warning: could not read SsIr.bin:", exc)
            self._raw_waveforms = []

    def project(self) -> dict:
        """The portable project this configuration describes."""
        self._read_protocol_meta()
        self._promote_unknown_blocks()
        self._read_settings()
        self._read_assets()
        self._read_devices()
        self._read_activities()
        return self._project

    def _read_protocol_meta(self):
        # Per-protocol metadata from <Protocols>: an RC5/RC6-family protocol declares
        # which bit is its toggle bit, and the remote flips it between presses so the
        # device can tell a second press from a held key. Dropping it made repeated
        # presses read as one. Keyed by block id, because the index is a position.
        by_index = self._ir_proto_map
        self._protocol_meta = {}
        for element in self._root.findall("Protocols/Protocol"):
            index = element.attrib.get("index")
            block_id = by_index.get(int(index)) if index and index.isdigit() else None
            if block_id is None:
                continue
            inner = "".join(ET.tostring(child, encoding="unicode") for child in element)
            if inner:
                self._protocol_meta[block_id] = inner
        if self._protocol_meta:
            self._project["protocol_meta"] = self._protocol_meta

    def _promote_unknown_blocks(self):
        # An unknown block can only be understood together with every Code that selects it:
        # the block supplies carrier elements while each Code supplies element order,
        # lifecycle stages and payload bits. Promote the pair once, before devices are
        # migrated. Any structural or VM-proof failure simply leaves the existing opaque
        # import path in charge. Blocks with companion XML metadata stay native until that
        # metadata itself has a portable representation.
        from . import native_portable
        codes_by_block = {}
        for command in self._root.findall("Device/Commands/Command"):
            proto_text = command.findtext("Data/Protocol")
            code = command.findtext("Data/Code")
            if proto_text is None or code is None:
                continue
            try:
                proto_index = int(proto_text)
            except ValueError:
                continue
            block_id = self._ir_proto_map.get(proto_index)
            if block_id in self._imported_protocols:
                codes_by_block.setdefault(block_id, []).append(code)
        self._promoted_protocols = {}
        for block_id, codes in codes_by_block.items():
            if block_id in self._protocol_meta:
                continue
            try:
                self._promoted_protocols[block_id] = native_portable.promote(
                    self._imported_protocols[block_id], codes)
            except native_portable.PromotionError as exc:
                self.rejects[block_id] = (str(exc), len(codes))
        _report_unpromotable(self.rejects)

    def _read_settings(self):
        rf = extract_rf(self._extracted_dir)
        if rf:
            self._project["settings"]["rf"] = rf
        self._project["settings"].update(read_preferences(self._extracted_dir))
    
        # Whose remote this is. Carried so a re-import round-trips the owner's name; the
        # account/login ids that sat beside it are not read - they addressed a service that
        # no longer exists, and nothing in a build needs them.
        user = self._root.find("User/Presentation")
        if user is not None:
            for element, key in (("FirstName", "first_name"), ("LastName", "last_name")):
                found = user.find(element)
                if found is not None and found.text:
                    self._project["settings"][key] = html.unescape(found.text)
            
        time_fmt = self._root.find("User/Properties/Property[@name='TimeDisplayFormat']")
        if time_fmt is not None:
            self._project["settings"]["time_format"] = time_fmt.text
        
        locale = self._root.find("User/Properties/Property[@name='LocaleId']")
        if locale is not None:
            self._project["settings"]["locale"] = locale.text

    def _read_assets(self):
        # 2. Extract Assets
        image_dir = os.path.join(self._extracted_dir, 'userconfig', 'image')
        if os.path.exists(image_dir):
            for img in glob.glob(os.path.join(image_dir, '*')):
                basename = os.path.basename(img)
                self._project["assets"].append({
                    "name": basename,
                    "source": os.path.join(self._extracted_dir, 'userconfig', 'image', basename)
                })

    def _read_devices(self):
        # 3. Extract Devices
        for d in self._root.findall('Device'):
            did = d.find('Id').text
            dev = {
                "id": did,
                "type": d.find('Type').text,
                "mfr": html.unescape(d.find('Manufacturer').text),
                "model": html.unescape(d.find('Model').text),
                "label": html.unescape(d.find('Presentation/Label').text) if d.find('Presentation/Label') is not None else "",
                "raw_codes": {},
                "commands": []
            }
        
            props_node = d.find('Properties')
            if props_node is not None:
                properties = {}
                for p in props_node.findall('Property'):
                    name = p.attrib.get('name')
                    properties[name] = p.text
                    if name == 'AlwaysOn':
                        dev["always_on"] = ((p.text or "").lower() == 'true')
                if properties:
                    dev["properties"] = properties
        
            # The device's state machine and number entry, carried whole. The convenience
            # fields below are a *view* of it for the interface - the block itself is what
            # gets rebuilt, so a state this self._project has never heard of still survives.
            parsed_states = states_mod.parse_states(d)
            if parsed_states:
                dev["states"] = parsed_states
                power = states_mod.power_commands(parsed_states)
                if "delay" in power:
                    dev["power_delay"] = power["delay"]
                if power.get("on"):
                    dev["power_on_cmd"] = power["on"]
                if power.get("off"):
                    dev["power_off_cmd"] = power["off"]
                if power.get("toggle"):
                    dev["power_cmd"] = power["toggle"]
                found = states_mod.input_list(parsed_states)
                if found:
                    dev["inputs"] = found

            numeric = states_mod.parse_numeric(d)
            if numeric is not None:
                dev["numeric"] = numeric

            cmds = d.find('Commands')
            command_protocol_indexes = {}
            if cmds is not None:
                props = cmds.find('Properties')
                if props is not None:
                    for p in props.findall('Property'):
                        pname = p.attrib['name']
                        # Map to the keys build_config expects
                        if pname == "PressPreSilence": dev["press_presilence"] = int(p.text)
                        if pname == "PressInterKey": dev["press_interkey"] = int(p.text)
                        if pname == "HoldPreSilence": dev["hold_presilence"] = int(p.text)
                        if pname == "HoldInterKey": dev["hold_interkey"] = int(p.text)
            
                for c in cmds.findall('Command'):
                    cname = c.find('Name').text
                    # <Protocol>-1</Protocol> marks a raw command: it has no protocol block,
                    # its Code indexes SsIr.bin instead. Taking the device's protocol from
                    # one of those loses the protocol its other commands really use.
                    this_proto = int(c.find('Data/Protocol').text)
                    if this_proto >= 0:
                        command_protocol_indexes[cname] = this_proto
                    code = c.find('Data/Code').text
                    dev["raw_codes"][cname] = code
                    dev["commands"].append([cname, cname, "00", "00", None])
                
            command_protocols = {
                name: self._ir_proto_map[index]
                for name, index in command_protocol_indexes.items()
                if index in self._ir_proto_map
            }
            if command_protocols:
                dev["command_protocols"] = command_protocols
                distinct = set(command_protocols.values())
                if len(distinct) == 1:
                    dev["protocol"] = next(iter(distinct))
                definitions = {
                    block_id: self._imported_protocols[block_id]
                    for block_id in distinct if block_id in self._imported_protocols
                }
                if definitions:
                    dev["protocol_definitions"] = definitions
            
            soft_map = {}
            hard_map = {}
            icon_map = {}
            for cg in d.findall('Presentation/ControlGroup'):
                if cg.attrib.get('name') == 'Misc':
                    for btn in cg.findall('Button'):
                        label = html.unescape(btn.find('Label').text or "")
                        _, cmd = parse_action_id(btn.find('ActionId').text)
                        if cmd:
                            soft_map[cmd] = label
                            icon = btn.find('Icon')
                            if icon is not None and icon.text:
                                icon_map[cmd] = icon.text
                elif cg.attrib.get('name') == 'HardButtons':
                    for btn in cg.findall('Button'):
                        hname = btn.attrib.get('name')
                        _, cmd = parse_action_id(btn.find('ActionId').text)
                        # One command may sit on several keys - a set-top box that puts
                        # Menu on both Menu and Exit, or PlayPause on both Play and Pause.
                        # Assigning rather than collecting kept whichever came last in the
                        # file and left the other key dead on the device page.
                        if hname and cmd:
                            hard_map.setdefault(cmd, []).append(hname)

            # Merge soft and hard labels into commands array
            # commands format: [name, label, addr, code, hardslot]
            new_cmds = []
            for c in dev["commands"]:
                cname = c[0]
                label = soft_map.get(cname, cname)
                # A list only when there really is more than one key, so the ordinary
                # one-key command keeps the plain string every other reader expects.
                slots = hard_map.get(cname) or []
                hardslot = slots[0] if len(slots) == 1 else (slots or None)
                new_cmds.append([cname, label, "00", "00", hardslot])
            dev["commands"] = new_cmds
            if icon_map:
                dev["icons"] = icon_map
            used = {}
            for cmd_name, code in dev["raw_codes"].items():
                index = ssir.raw_index(code)
                if index is not None and index < len(self._raw_waveforms):
                    used[str(index)] = ssir.decode_capture(
                        self._raw_waveforms[index], name=f"{dev['label']}-{cmd_name}")
            if used:
                dev["raw_ir"] = used
            signals = {}
            portable_definitions = {}
            for cmd_name, code in dev["raw_codes"].items():
                index = ssir.raw_index(code)
                if index is not None and str(index) in used:
                    signals[cmd_name] = used[str(index)]
                    continue
                block_id = command_protocols.get(cmd_name)
                if index is None and block_id:
                    from .backend import _decode_protocol_code
                    decoded = _decode_protocol_code(block_id, code, name=cmd_name)
                    if decoded is not None:
                        signals[cmd_name] = decoded
                        continue
                    from . import native_portable
                    promotion = self._promoted_protocols.get(block_id)
                    if promotion is not None:
                        transmission = promotion.transmissions.get(
                            native_portable.code_key(code))
                        if transmission is not None:
                            definition = promotion.definition
                            signals[cmd_name] = ir_signal.protocol_signal(
                                definition["id"], {}, name=cmd_name,
                                transmission=transmission,
                                provenance={
                                    "kind": "structural-native-import",
                                    "backend": "harmony-pk",
                                })
                            portable_definitions[definition["id"]] = definition
                            continue
                native = {
                    "format": ("ssir-command" if index is not None else "command-code"),
                    "code": code,
                }
                if block_id and index is None:
                    native["protocol_block_id"] = block_id
                    definition = (dev.get("protocol_definitions") or {}).get(block_id)
                    if definition is not None:
                        native["protocol_definition"] = definition
                signals[cmd_name] = ir_signal.backend_opaque(
                    {"harmony-pk": native}, name=cmd_name,
                    provenance={"kind": "imported-config"})
            if signals:
                dev["signals"] = signals
            if portable_definitions:
                dev["portable_protocol_definitions"] = portable_definitions
        
            # Nothing above this line escapes the importer.  ``dev`` mirrors the native XML
            # while it is being decoded; the self._project receives only the portable command
            # representation.  Known NEC/Samsung/RC6 Codes become semantic signals, learned
            # SsIr entries become waveforms, and only genuinely unknown Codes stay opaque.
            from .backend import migrate_legacy_device
            self._project["devices"].append(migrate_legacy_device(dev))

    def _read_activities(self):
        # 4. Extract Activities
        for a in self._root.findall('Activity'):
            aid = a.find('Id').text
            if aid == "-1":
                # The "all off" pseudo-activity. Its list is the owner's, not something to
                # infer: it may include a device with no power command of its own (a shade
                # controller), and it may deliberately leave one alone.
                off = [e.text for e in a.findall('Power/Off') if e.text]
                if off:
                    self._project["power_off_all"] = off
                label = a.find('Presentation/Label')
                if label is not None and label.text is not None:
                    self._project["power_off_label"] = html.unescape(label.text)
                continue
            
            act = {
                "id": aid,
                "type": a.find('Type').text,
                "label": html.unescape(a.find('Presentation/Label').text),
                "soft_buttons": [],
                "image_buttons": [],
                "hard_macros": {}
            }
            # Which devices this activity powers off when it starts. Kept as the config
            # states it rather than recomputed: an owner may deliberately leave a device
            # alone, and inferring "everything else" would override that.
            power = a.find('Power')
            if power is not None:
                off = [e.text for e in power.findall('Off') if e.text]
                if off:
                    act["power_off_devices"] = off
        
            props = {p.attrib.get('name'): p.text for p in a.findall('Properties/Property')}
            if props:
                act["properties"] = props

            # The three roles the interface names, plus any others verbatim. A config may
            # use a role this self._project has no field for (PASSTHROUGH, where the sound goes
            # through an amplifier); dropping it also dropped that device from the
            # activity's power-on list, so the amp stayed silent.
            for r in a.findall('Role'):
                rname = r.find('Name').text
                rdid = r.find('DeviceId').text
                if rname == 'DISPLAY': act['display'] = rdid
                elif rname == 'VOLUME': act['volume'] = rdid
                elif rname == 'DEFAULT': act['control'] = rdid
                else: act.setdefault('roles', {})[rname] = rdid

            # The order devices are powered on in is the config's, not one we infer:
            # an amplifier that comes up after the source it is switching can miss the
            # input change.
            power = a.find('Power')
            if power is not None:
                on = [e.text for e in power.findall('On') if e.text]
                if on:
                    act["power_on_devices"] = on
            
            from .builder.activities import _default_hard_buttons
            implied_hard = _default_hard_buttons(
                act, {device["id"]: device for device in self._project["devices"]})
            for cg in a.findall('Presentation/ControlGroup'):
                # An activity's on-screen buttons are stored in a group named "Misc" - which is
                # what the builder writes too. Reading only "SoftButtons" meant a config this
                # tool produced could not be imported back: the buttons were simply not seen.
                if cg.attrib.get('name') in ('Misc', 'SoftButtons'):
                    for btn in cg.findall('Button'):
                        label = html.unescape(btn.find('Label').text or "")
                        did, cmd = parse_action_id(btn.find('ActionId').text)
                        action_id = btn.find('ActionId').text or ""
                        icon = btn.find('Icon')
                        icon_name = icon.text if icon is not None and icon.text else None
                        if did and cmd:
                            entry = [label, did, cmd]
                            if icon_name:
                                entry.append(icon_name)
                            act["soft_buttons"].append(entry)
                        elif action_id in self._macros:                 # a macro button
                            entry = {"label": label, "macro": self._macros[action_id]}
                            if icon_name:
                                entry["icon"] = icon_name
                            act["soft_buttons"].append(entry)
                elif cg.attrib.get('name') == 'HardButtons':
                    for btn in cg.findall('Button'):
                        hname = btn.attrib.get('name')
                        action_id = btn.find('ActionId').text
                        if not hname:
                            continue
                        # A hard key may run a whole named ActionList, not just one
                        # command. Rebuilding it from the id alone kept the first step and
                        # threw the rest away, so a three-step macro came back as one.
                        if action_id in self._macros:
                            steps = self._macros[action_id]
                            implied = implied_hard.get(hname)
                            ordinary = (["command", *implied, "Hold"]
                                        if implied is not None else None)
                            if steps != [ordinary]:
                                act["hard_macros"][hname] = steps
                            continue
                        did, cmd = parse_action_id(action_id)
                        # Ordinary role/device routing is reconstructed by the builder. It
                        # is not an activity macro and storing it as one expands every key
                        # into a redundant ActionList on import/rebuild. Preserve only a
                        # real override whose target differs from the implied assignment.
                        if did and cmd and implied_hard.get(hname) != (did, cmd):
                            act["hard_macros"][hname] = [["command", did, cmd]]
                        
            if not act["hard_macros"]: del act["hard_macros"]
            if not act["soft_buttons"]: del act["soft_buttons"]

            ch_list = a.find('Presentation/ChannelList')
            if ch_list is not None:
                for ch in ch_list.findall('Channel'):
                    name = html.unescape(ch.find('Station').text)
                    num = ch.find('Number').text
                    img = ch.find('Image').text
                    act["image_buttons"].append(
                        [name, "channel", num, img]
                    )
                    # Many receivers need the channel number confirmed with OK/Select. It
                    # is the trailing action after the digits, and reading only the number
                    # dropped it - the favourite then typed the digits and sat there.
                    steps = [parse_action(x) for x in ch.findall('Actions/Action')]
                    commands = [step[2] for step in steps
                                if step and step[0] == "command"]
                    digits = list(str(num))
                    if len(commands) == len(digits) + 1 and commands[:-1] == digits:
                        act["channel_confirm"] = commands[-1]
                    elif not steps:
                        # No explicit digits at all: the remote dials through the control
                        # device's own <Numeric> block.
                        act["channels_via_numeric"] = True
            if not act["image_buttons"]: del act["image_buttons"]

            for xml_tag, json_key in [('EnterActions', 'enter'), ('LeaveActions', 'leave')]:
                actions_elem = a.find(xml_tag)
                if actions_elem is not None:
                    macro = []
                    for act_elem in actions_elem.findall('Action'):
                        parsed = parse_action(act_elem)
                        if parsed: macro.append(parsed)
                    if macro: act[json_key] = macro

            self._project["activities"].append(act)


def _build_project_harmony_pk(extracted_dir, out_file=None):
    """Read one extracted arch-15 configuration into the portable project model."""
    return _HarmonyPkImport(extracted_dir, out_file).project()




def main():
    import sys
    if len(sys.argv) != 3:
        print("Usage: extract_project.py <extracted_dir> <out_json>")
        sys.exit(1)
    project = _build_project_harmony_pk(sys.argv[1])
    # Device and activity labels are the owner's own words, so this file is not ASCII.
    # Without an explicit encoding it takes the platform's, which on Windows cannot
    # represent most of them.
    with open(sys.argv[2], 'w', encoding="utf-8") as f:
        json.dump(project, f, indent=2)


if __name__ == '__main__':
    main()
