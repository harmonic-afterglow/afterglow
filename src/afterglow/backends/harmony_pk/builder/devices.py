"""Harmony PK device XML and its ActionLists entries.

Format reference: docs/harmony_pk/configuration.md
"""

from .. import ssir, states as states_mod
from .actions import _a_send, digit_command
from .codes import CODECS, code_pre, esc, necext_code, portable_code


def _gen_device(spec):
    """Return (device_xml, actionlists_fragment) for one device spec."""
    did = spec["id"]; cmds = spec["commands"]; inputs = spec.get("inputs", [])
    necext = spec.get("necext_addr")
    default_proto = spec.get("_proto_idx", 0)
    command_protocols = spec.get("_command_proto_idx") or {}
    codec = CODECS.get(spec.get("codec", "nec"))
    raw_codes = spec.get("raw_codes", {})
    signals = spec.get("signals", {})

    def proto_for(name):
        """Runtime IrProto index selected by this command's XML and Code."""
        return command_protocols.get(name, default_proto)

    def code_for(name, a, c):
        proto = proto_for(name)
        if name in raw_codes:
            raw = raw_codes[name]
            # A code beginning 0xFFFF is a recorded waveform, not a protocol frame: the
            # byte after the marker is an index into SsIr.bin. Rewriting byte 0 with the
            # protocol index - which is right for every other code - destroys the marker
            # and the command silently stops resolving to anything.
            if ssir.is_raw(raw):
                return raw
            prefix = "0x" if raw.lower().startswith("0x") else ""
            body = raw[len(prefix):]
            if len(body) < 2 or len(body) % 2:
                raise ValueError(f"Invalid raw profile code for {name!r}")
            # Byte 0 selects the IrProto block, so it must match the XML <Protocol>.
            return f"{prefix}{proto:02X}{body[2:]}"
        if name in signals:
            return portable_code(signals[name], proto)
        pre = code_pre(proto)
        return necext_code(necext[0], necext[1], c, pre) if necext else codec(a, c, pre)

    def protocol_of(name):
        """-1 for a recorded waveform: it has no protocol block."""
        return -1 if ssir.is_raw(raw_codes.get(name, "")) else proto_for(name)

    cmd_xml = "".join(
        f"<Command><Name>{esc(n)}</Name><Data><Protocol>{protocol_of(n)}</Protocol>"
        f"<Code>{code_for(n,a,c)}</Code></Data></Command>" for n,_l,a,c,_h in cmds)
    # Defaults, not constants: a device that carries its own timing keeps it.
    pre_sil  = spec.get("press_presilence", 1000)
    inter    = spec.get("press_interkey", 500)
    hold_sil = spec.get("hold_presilence", 50)
    hold_int = spec.get("hold_interkey", 100)
    cmd_props = (f'<Properties><Property name="PressPreSilence">{pre_sil}</Property>'
                 f'<Property name="PressInterKey">{inter}</Property>'
                 f'<Property name="HoldPreSilence">{hold_sil}</Property>'
                 f'<Property name="HoldInterKey">{hold_int}</Property></Properties>')

    # The remote draws these on the device's page, so they survive a round trip.
    icons = spec.get("icons", {})
    misc = "".join(
        f"<Button><Label>{esc(l)}</Label>"
        + (f"<Icon>{esc(icons[n])}</Icon>" if n in icons else "")
        + f"<Position>{i}</Position>"
        f"<ActionId>{did}_{esc(n)}_Hold</ActionId></Button>"
        for i,(n,l,_a,_c,_h) in enumerate(cmds))
    hard = ""
    for n,_l,_a,_c,h in cmds:
        if not h: continue
        for slot in (h if isinstance(h,(list,tuple)) else [h]):   # a command may sit on >1 hard key
            hard += f'<Button name="{slot}"><Label /><ActionId>{did}_{esc(n)}_Hold</ActionId></Button>'
    presentation = (f"<Presentation><Label>{esc(spec['label'])}</Label>"
                    f'<ControlGroup name="Misc">{misc}</ControlGroup>'
                    f'<ControlGroup name="HardButtons">{hard}</ControlGroup></Presentation>')

    states_content = ""
    delay = spec.get("power_delay", 1500)
    def _pwr_send(cmd):
        return (f'<Action><Target>Device</Target><Operation><Name>SendCommand</Name>'
                f'<Parameter name="DeviceId">{did}</Parameter>'
                f'<Parameter name="Command">{esc(cmd)}</Parameter>'
                f'<Parameter name="Modifier">Press</Parameter></Operation></Action>')
    if spec.get("power_on_cmd") and spec.get("power_off_cmd"):
        # Discrete power: On is idempotent.
        states_content += (f"<State><Id>Power</Id><Value>Off</Value><Value>On</Value><Delay>{delay}</Delay>"
                   f"<DiscreteActions>"
                   # <Action> before <Name>, as every real configuration writes it.
                   f"<SetAction>{_pwr_send(spec['power_on_cmd'])}<Name>On</Name></SetAction>"
                   f"<SetAction>{_pwr_send(spec['power_off_cmd'])}<Name>Off</Name></SetAction>"
                   f"</DiscreteActions></State>")
    elif spec.get("power_cmd") and not spec.get("always_on"):
        # Toggle power: one code cycles On<->Off.
        states_content += (f"<State><Id>Power</Id><Value>Off</Value><Value>On</Value><Delay>{delay}</Delay>"
                   f"<RelativeActions><NextAction>{_pwr_send(spec['power_cmd'])}"
                   f"</NextAction></RelativeActions></State>")
    def _op(name, params):
        """One <Action> for this device."""
        body = "".join(f'<Parameter name="{n}">{esc(str(v))}</Parameter>'
                       for n, v in params)
        return (f"<Action><Target>Device</Target><Operation><Name>{name}</Name>"
                f'<Parameter name="DeviceId">{did}</Parameter>{body}'
                f"</Operation></Action>")

    def _input_steps(selection):
        """Render one input's selection, which may be a whole sequence.

        A bare command name is the common case and stays a single press. A list is a
        device-local step sequence - a real input on many devices needs `InputNext`, a
        settling wait, then a second press, and sending only the first step selects
        whatever input happens to be adjacent.

        `hold_ms` becomes a real `Duration` parameter: configurations write
        `Modifier=Press` alongside `Duration=2000` for a device that needs a long press,
        so the length is expressible and is kept.
        """
        if isinstance(selection, str):
            return _op("SendCommand", [("Command", selection), ("Modifier", "Press")])
        out = []
        for step in selection:
            if isinstance(step, str):
                out.append(_op("SendCommand",
                               [("Command", step), ("Modifier", "Press")]))
            elif "delay_ms" in step:
                out.append(_op("SendDelay", [("Delay", int(step["delay_ms"]))]))
            elif "command" in step:
                params = [("Command", step["command"]), ("Modifier", "Press")]
                if step.get("hold_ms"):
                    params.append(("Duration", int(step["hold_ms"])))
                out.append(_op("SendCommand", params))
            elif "set" in step:
                out.append(_op("SetValue", [("State", step["set"]),
                                            ("Value", step["to"])]))
        return "".join(out)

    # An input whose selection is indirect (it sets another state rather than sending
    # a code) has no command to synthesise from; those devices carry their real block.
    inputs = [pair for pair in inputs if len(pair) == 2 and pair[1]]
    cycle = spec.get("input_cycle") or {}
    if inputs or cycle:
        sv = "".join(f"<Value>{esc(v)}</Value>" for v, _ in inputs)
        body = sv
        # Never both: `State.lua` reads `RelativeActions` and only falls through to
        # `DiscreteActions` in an `elseif`, so a state carrying both loses its discrete
        # selections silently. Discrete wins where it exists; stepping is the fallback.
        # No catalogue device publishes both, but an authored one can.
        if inputs:
            sa = "".join(
                f"<SetAction>{_input_steps(cn)}<Name>{esc(v)}</Name></SetAction>"
                for v, cn in inputs)
            body += f"<DiscreteActions>{sa}</DiscreteActions>"
        elif cycle:
            rel = ""
            if cycle.get("next"):
                rel += f"<NextAction>{_input_steps(cycle['next'])}</NextAction>"
            if cycle.get("previous"):
                rel += f"<PrevAction>{_input_steps(cycle['previous'])}</PrevAction>"
            if rel:
                body += f"<RelativeActions>{rel}</RelativeActions>"
        states_content += f"<State><Id>Input</Id>{body}</State>"
    
    # A device imported from a real config carries its whole state machine; emit that
    # rather than the four-field approximation above, which cannot express indirect
    # inputs, Next/Prev cycling, or a discrete power whose On is a ChangeAction. The
    # synthesised version is for devices authored from scratch, which have no block.
    carried = spec.get("states")
    if carried:
        states = states_mod.build_states(carried)
    else:
        # States Logitech declares for this device - `InputType`, `TVInput` and friends -
        # rebuilt beside the Power/Input/Numeric ones synthesised above. They are what a
        # `{"set": …, "to": …}` step refers to; without them such a step names a state the
        # configuration never declares.
        declared = states_mod.build_control_states(
            spec.get("control_states") or [], did)
        if declared:
            states_content += states_mod.build_states(declared)[len("<States>"):-len("</States>")]
        states = f"<States>{states_content}</States>" if states_content else ""

    # Direct channel dialling: `numeric` is True, or {"finish": cmd, "fixed": N}.
    numeric_xml = ""
    nspec = spec.get("numeric")
    if isinstance(nspec, dict) and nspec.get("digits"):
        # Carried from a real config: three digit sets, each digit's own action.
        numeric_xml = states_mod.build_numeric(nspec)
    elif nspec:
        # Synthesised for a device authored here. Digit commands are whatever the device
        # calls them - real configurations name them "0".."9", so matching only
        # "Number0".."Number9" emits an empty block and loses the number pad.
        ncfg = nspec if isinstance(nspec, dict) else {}
        digs = ""
        for digit in range(10):
            name = digit_command(spec, digit)
            if name:
                # <Digit value="N"> - an attribute, as every real config writes it.
                digs += (f'<Digit value="{digit}">'
                         + _a_send(did, name, "Press") + "</Digit>")
        finish = ncfg.get("finish")
        fin_xml = f"<Finish>{_a_send(did, finish, 'Press')}</Finish>" if finish else ""
        # `Start`, and the `-/--` prefixes. `Numeric.lua` emits these as: start actions,
        # zero-padding to FixedDigits, then GreaterTen for a two-digit number or
        # GreaterHundred for three to six, then the digits, then Finish. It indexes the
        # block by tag name, so the order written here is for a human reading the XML.
        extra_xml = ""
        for key, tag in (("start", "Start"), ("greater_ten", "GreaterTen"),
                         ("greater_hundred", "GreaterHundred")):
            steps = ncfg.get(key)
            if steps:
                extra_xml += f"<{tag}>{_input_steps(steps)}</{tag}>"
        numeric_xml = (f"<Numeric><FixedDigits>{ncfg.get('fixed', 0)}</FixedDigits>"
                       f"{extra_xml}<FirstDigit>{digs}</FirstDigit>{fin_xml}</Numeric>")

    always = "true" if spec.get("always_on") else "false"   # AlwaysOn -> excluded from activity power on/off
    # Properties the builder owns, then everything else the config carried. Devices use
    # these to describe what they are, and the remote changes behaviour based on them, so
    # dropping unmodelled ones would quietly alter the device.
    #
    # Three layers, in order: values every device must carry, then the device's own
    # properties, then AlwaysOn - which wins because it is derived from `always_on`,
    # which the importer sets from that same property, so the two cannot drift.
    #
    # ManualPower is on every device in every donor configuration, so it is always
    # written. IsNewDevice is not: 32 of 35 donor devices lack it, and it means "just
    # added, the remote will clear it" - writing it everywhere tells the remote every
    # device is new on every flash.
    always_written = {"ManualPower": "false"}
    carried = {k: v for k, v in (spec.get("properties") or {}).items()}
    # IsNewDevice is true or absent, never false - that is the only shape any real
    # configuration has, and it keeps "is it flagged" and "is it true" the same
    # question. NewDeviceFound in the User block is derived from exactly that.
    if str(carried.get("IsNewDevice", "")).lower() != "true":
        carried.pop("IsNewDevice", None)
    dev_props = ("<Properties>"
                 + "".join(f'<Property name="{esc(k)}">{esc(str(v))}</Property>'
                           for k, v in {**always_written, **carried,
                                        "AlwaysOn": always}.items())
                 + "</Properties>")
    device = (f"<Device><Id>{did}</Id><Type>{spec['type']}</Type>"
              f"<Manufacturer>{esc(spec.get('mfr', ''))}</Manufacturer>"
              f"<Model>{esc(spec.get('model', ''))}</Model>"
              f"{presentation}{dev_props}{states}{numeric_xml}<Commands>{cmd_props}{cmd_xml}</Commands></Device>")

    al = "".join(
        f'<ActionList name="{did}_{esc(n)}_Hold"><Action><Target>Device</Target>'
        f'<Operation><Name>SendCommand</Name><Parameter name="DeviceId">{did}</Parameter>'
        f'<Parameter name="Command">{esc(n)}</Parameter>'
        f'<Parameter name="Modifier">Hold</Parameter></Operation></Action></ActionList>'
        for n,_l,_a,_c,_h in cmds)
    return device, al
