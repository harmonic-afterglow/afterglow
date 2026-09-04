"""Harmony PK activity XML: roles, power, macros and on-screen buttons.

An activity names the devices that play each role (display, volume, control), the
actions to run when it starts and stops, and any per-activity button overrides.
"""
from .actions import (_a_send, _a_setvalue, _action,
                      digit_command)
from .codes import esc

VOLUME_SLOTS = ("VolumeUp", "VolumeDown", "VolumeMute")
# Modest property set for a TV-watching activity (matches the factory VirtualTelevisionN).
# The properties a new activity gets. A real config carries many more (which help pages
# to hide, how the guide button behaves, whether unused devices power off); an imported
# activity keeps its own via `act["properties"]`.
_ACT_DEFAULTS = {
    "PowerOffUnusedDevices": "True",
    "ActivityStartPage": "Numbers",
    "ChannelButtonBehaviour": "BasicChannels",
    "ControlGroup_Hard Buttons": "True",
}


def _act_props(act):
    props = {**_ACT_DEFAULTS, **(act.get("properties") or {})}
    return ("<Properties>"
            + "".join(f'<Property name="{esc(k)}">{esc(str(v))}</Property>'
                      for k, v in props.items())
            + "</Properties>")

def _slot_map(spec):
    """{ hard-button slot -> command Name } for a device, from its commands' hardslots."""
    m = {}
    for name, _l, _a, _c, hard in spec["commands"]:
        if not hard:
            continue
        for slot in (hard if isinstance(hard, (list, tuple)) else [hard]):
            m.setdefault(slot, name)
    return m


def _default_hard_buttons(act, by_id):
    """Hard-key assignments implied by an activity's portable roles and devices.

    These do not need to be serialized as activity macros. Keeping this calculation in
    one place lets import distinguish an actual override from the ordinary key routing
    that the builder will reconstruct itself.
    """
    disp, ctrl = act.get("display"), act.get("control")
    vol = act.get("volume", disp)
    vmap = _slot_map(by_id[vol]) if vol in by_id else {}
    cmap = _slot_map(by_id[ctrl]) if ctrl in by_id else {}
    buttons = {}
    for slot in VOLUME_SLOTS:
        if slot in vmap:
            buttons[slot] = (vol, vmap[slot])
    for slot, command in cmap.items():
        buttons.setdefault(slot, (ctrl, command))
    return buttons

# Action builders. The firmware's Action vocabulary is SendCommand, SetValue, SendDelay
# and SendNumber, confirmed in HAO.lua. Used by EnterActions, LeaveActions and macros.


def _known_activity_types(remote=None):
    """The activity types this model's firmware has. PowerOff is not one of them - it
    is the everything-off scene, which the format writes as an activity.

    Asked of the remote being built for, not of a list kept here: the types come out of
    each model's own firmware, so what is valid depends on which remote this is.
    """
    from .... import vocabulary
    return {value for _label, value in vocabulary.activity_types(remote)} | {"PowerOff"}


def _check_activity_type(value, label, remote=None):
    known = _known_activity_types(remote)
    if not known or value in known:
        return
    close = sorted(n for n in known if value[:10].lower() in n.lower())[:4]
    model = getattr(vocabulary_profile(remote), "model", "this remote")
    raise ValueError(
        f"Activity {label!r} is of type {value!r}, which {model} does not have."
        + (f" Did you mean {', '.join(close)}?" if close else
           " The types it does have are listed in its profile."))


def vocabulary_profile(remote=None):
    """The profile whose vocabulary applies, or None if it cannot be resolved.

    The caller wants a model name for a message, so an unknown or unreadable profile is
    worth falling back on rather than raising. Named exceptions only: this used to catch
    everything, which would have swallowed a genuine fault in profile loading and
    reported it as "this remote".
    """
    from .... import vocabulary
    try:
        return vocabulary.for_remote(remote)
    except (LookupError, OSError, ValueError):
        return None


def _known_icons():
    """The glyph names the remote actually has, from the extracted artwork."""
    from .... import paths
    folder = paths.icons("buttons")
    return {path.stem for path in folder.glob("*.png")} if folder.is_dir() else set()


def _check_icon(name, label):
    """An <Icon> names a glyph in the remote's firmware. A name it does not have draws
    nothing at all, and the button looks broken rather than plain."""
    known = _known_icons()
    if not known or name in known:
        return
    close = sorted(n for n in known if name.lower() in n.lower()
                   or n.lower() in name.lower())[:4]
    raise ValueError(
        f"Button {label!r} asks for the icon {name!r}, which the remote does not have."
        + (f" Did you mean {', '.join(close)}?" if close else
           " See icons/buttons/ for the names it does have."))


def _gen_activity(act, by_id, remote=None):
    """An activity = a scene. `act` keys:
        id, label, type?,
        display  device id -> DISPLAY role (the screen),
        control  device id -> DEFAULT role + all non-volume hard keys,
        volume?  device id -> VOLUME role + volume/mute hard keys (defaults to display),
        input?   (deviceId, InputStateValue) to jump on enter (e.g. TV -> HDMI2, AVR -> MD),
        leave?   [action-step, ...] actions to run when the activity is left (LeaveActions),
        soft_buttons? [ (Label, deviceId, command[, icon])                      single-cmd button
                        | {label, device, command, icon?}                        single-cmd button
                        | {label, icon?, macro:[action-step,...]} ]              macro button
        channels?, channel_confirm?, channels_via_numeric?  (favorite channels).
    Returns (activity_xml, [extra ActionList xml]) -- macros need their own named ActionLists.
    Every distinct non-AlwaysOn device among {display, volume, control} powers on."""
    disp, ctrl = act.get("display"), act.get("control")
    vol = act.get("volume", disp)                  # volume can ride a 3rd device (e.g. an AVR)
    buttons = _default_hard_buttons(act, by_id)
    macro_als = []                                  # extra ActionLists this activity needs
    
    hard_macros = act.get("hard_macros", {})
    # A macro may claim a hard key the control device does not otherwise use - putting
    # "dim the lights" on an unused colour button is the whole point. Iterating only
    # over the keys a device already occupies dropped those macros without a word.
    for slot in hard_macros:
        buttons.setdefault(slot, (ctrl, None))
    btn_xml = ""
    for slot, (dev, cmd) in buttons.items():
        if slot in hard_macros:
            macro = hard_macros[slot]
            aid = f'{act["id"]}_hardmacro_{slot}'
            macro_als.append(f'<ActionList name="{aid}">' + "".join(_action(s) for s in macro) + '</ActionList>')
            btn_xml += f'<Button name="{slot}"><Label /><ActionId>{aid}</ActionId></Button>'
        elif cmd:
            btn_xml += f'<Button name="{slot}"><Label /><ActionId>{dev}_{esc(cmd)}_Hold</ActionId></Button>'
            
    roles = [("DISPLAY", disp), ("VOLUME", vol), ("DEFAULT", ctrl)]
    extra_roles = act.get("roles", {})
    for r_name, r_dev in extra_roles.items():
        roles.append((r_name, r_dev))
        
    role_xml = "".join(f'<Role><Name>{r}</Name><DeviceId>{d}</DeviceId>'
                       f'<Presentation /></Role>' for r, d in roles if d)
    # touchscreen soft buttons (activity UI). An <Icon>NAME</Icon> renders the CUSTOM_NAME glyph;
    # a macro button gets its own multi-Action ActionList that the button's ActionId points at.
    soft = act.get("soft_buttons", [])
    soft_xml = ""
    if soft:
        btns = []
        for i, sb in enumerate(soft):
            icon = macro = dev = cmd = label = None
            if isinstance(sb, dict):
                label = sb["label"]; icon = sb.get("icon")
                macro = sb.get("macro"); dev = sb.get("device"); cmd = sb.get("command")
            else:                                    # tuple: (label, dev, cmd[, icon])
                label, dev, cmd = sb[0], sb[1], sb[2]
                icon = sb[3] if len(sb) > 3 else None
            if macro:                                # multi-step -> dedicated ActionList
                aid = f'{act["id"]}_macro{i}'
                macro_als.append(f'<ActionList name="{aid}">'
                                 + "".join(_action(s) for s in macro) + '</ActionList>')
            else:
                aid = f'{dev}_{esc(cmd)}_Hold'       # existing per-command device ActionList
            if icon:
                _check_icon(icon, label)
            icon_xml = f'<Icon>{esc(icon)}</Icon>' if icon else ''
            btns.append(f'<Button><Label>{esc(label)}</Label>{icon_xml}'
                        f'<Position>{i}</Position><ActionId>{aid}</ActionId></Button>')
        soft_xml = '<ControlGroup name="Misc">' + "".join(btns) + '</ControlGroup>'
        
    enter_actions = "".join(_action(s) for s in act.get("enter", []))
    if act.get("input"):
        enter_actions += _a_setvalue(act["input"][0], "Input", act["input"][1])
    enter = enter_actions
    
    # LeaveActions: run when the activity is left (e.g. put the AVR back to its TV input).
    leave = "".join(_action(s) for s in act.get("leave", []))
    # favorite channels: [(Station, Number, ImageFile), ...] shown as tappable logos. The Flash
    # UI reads Station/Number/Slot/Image per <Channel> (logo from userconfig/image/<Image>).
    # Tuning: default = SendAsCharacters (explicit digit macro to the control device); with
    # channels_via_numeric=True we omit that so the firmware dials via the control device's
    # <Numeric> block instead (which must exist on the control device).
    # Favourites may be given either as full image buttons (what the GUI writes) or as
    # the shorthand `channels` list of (Station, Number, ImageFile). Accepting only the
    # first silently dropped every favourite while still shipping its logo, which is how
    # a config ends up with eight orphaned images and an empty <ChannelList/>.
    image_buttons = list(act.get("image_buttons", []))
    for station, number, image in act.get("channels", []):
        image_buttons.append((station, "channel", number, image))
    confirm = act.get("channel_confirm")           # e.g. "Select" -> press OK after the digits
    via_numeric = act.get("channels_via_numeric")
    chan_xml = "<ChannelList />"
    if image_buttons:
        entries = []
        for slot, (label, atype, payload, image) in enumerate(image_buttons):
            # Slot is 1-BASED + contiguous: convertChannelList gap-fills missing slots with blank
            # channels seeding "previous"=0, so slot+1 avoids 7 ghost favorites being prepended.
            # We use 'label' as both Station and Number text if there's no explicit number
            number_txt = str(payload) if atype == "channel" else label
            head = (f'<Channel><Station>{esc(label)}</Station><Number>{esc(number_txt)}</Number>'
                    f'<Slot>{slot + 1}</Slot><Image>{esc(image)}</Image>')
            
            if atype == "channel":
                if via_numeric:
                    entries.append(head + '</Channel>')          # -> dialed via control's Numeric
                else:
                    # The control device's own digit keys, by whatever it calls them.
                    names = [digit_command(by_id[ctrl], d) for d in str(payload)]
                    if any(name is None for name in names):
                        raise ValueError(
                            f"Favourite {label!r} dials {payload} on "
                            f"{by_id[ctrl].get('label', ctrl)!r}, which has no number keys. "
                            "Give that device its digit commands, or set "
                            "channels_via_numeric to dial through its <Numeric> block.")
                    digits = "".join(_a_send(ctrl, name, "Hold") for name in names)
                    if confirm:
                        digits += _a_send(ctrl, confirm, "Hold")
                    entries.append(head + '<Option>SendAsCharacters</Option>'
                                   f'<Actions>{digits}</Actions></Channel>')
            elif atype == "command":
                target_dev, cmd_name = payload
                action = _a_send(target_dev, cmd_name, "Hold")
                entries.append(head + '<Option>SendAsCharacters</Option>'
                               f'<Actions>{action}</Actions></Channel>')
            elif atype == "macro":
                action = "".join(_action(s) for s in payload)
                entries.append(head + '<Option>SendAsCharacters</Option>'
                               f'<Actions>{action}</Actions></Channel>')
                
        chan_xml = "<ChannelList>" + "".join(entries) + "</ChannelList>"
    # power on every distinct device the activity uses (display, volume, control) that isn't
    # AlwaysOn (STB / Media Center stay on). dict.fromkeys keeps order and de-dupes.
    # An activity says what to turn ON *and* what to turn OFF. Without the <Off> list
    # the devices from the previous activity stay powered - switching from Watch DVD to
    # Watch TV left the DVD player running, because only <On> was ever written.
    power_devs = act.get("power_on_devices") or ([disp, vol, ctrl]
                                                 + list(extra_roles.values()))
    power_devs = [d for d in dict.fromkeys(power_devs)
                  if d and d in by_id and not by_id[d].get("always_on")]
    off_devs = [d for d in dict.fromkeys(act.get("power_off_devices") or [])
                if d in by_id and d not in power_devs
                and not by_id[d].get("always_on")]
    # Every device the configuration knows is either switched on or switched off.
    # That is not a guess: all six donor configurations partition completely, in
    # all thirty of their activities, without exception. A device in neither list
    # is one the activity never touches - which is how a device added to a project
    # after it was imported silently stopped being powered down by anything.
    #
    # AlwaysOn devices are the one case no donor demonstrates, since none of them
    # has such a device. They are left out of both lists on the reading that
    # "always on" means activities do not power it at all.
    listed = set(power_devs) | set(off_devs)
    off_devs += [d for d in by_id
                 if d not in listed and not by_id[d].get("always_on")]
    power = ("".join(f'<On>{d}</On>' for d in power_devs)
             + "".join(f'<Off>{d}</Off>' for d in off_devs))
    
    activity_type = act.get("type", "VirtualTelevisionN")
    _check_activity_type(activity_type, act.get("label", act["id"]), remote)
    xml = (f'<Activity><Id>{act["id"]}</Id><Type>{activity_type}</Type>'
           f'{_act_props(act)}<Presentation><Label>{esc(act["label"])}</Label>{chan_xml}'
           f'<ControlGroup name="HardButtons">{btn_xml}</ControlGroup>{soft_xml}</Presentation>'
           f'{role_xml}<EnterActions>{enter}</EnterActions>'
           f'<LeaveActions>{leave}</LeaveActions><Power>{power}</Power></Activity>')
    return xml, macro_als
