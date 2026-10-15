"""Build a Harmony One configuration from a project, and nothing else.

A build starts from an empty buffer and the scaffold - a directory of files, not anybody's
configuration - and lays out a header, every section, and the bodies they point at. What
a generated image is obliged to contain was settled by the configuration a Harmony One
ships with, `Region_3.EZHex` in firmware 54.2.5: a virgin remote has no devices, no status
overlays, an empty name chain, and zero entries in sections 13 and 15.

This module prepares a project - its devices lowered (devices.py), its activities planned
(activities.py), its icons composed (pictures.py), its fonts loaded with exactly the
characters it draws - and then runs the layout in its order: the platform's objects
(scaffold.py), the carried screens (carried.py), the firmware's screens
(firmware_screens.py), the hub (hub.py), Options (options_screens.py), the activities
(activity_screens.py), and finally placement and the tables (assemble.py). Every number
in an image is a position, so that order is what makes a build the same each time.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import activities as activity_plan
from . import (
    assemble, catalogue, charging, firmware_screens, font_index, keys, ordinals, platform_text,
    scaffold, structures)
from . import idle as idle_machine
from .actions import Actions
from .activity_screens import Flow
from .carried import Carried
from .devices import held_commands, lowered_devices, state_variables
from .hub import Hub, device_pages, empty_screen
from .layout import Layout
from .options_screens import TUTORIAL, Options
from .pages import BUTTON_POSITIONS, SOFTKEY_FONTS, labeller
from .pages import frames as page_frames
from .pictures import favourite_picture, row_icon, start_icon
from .firmware_screens import load_system
from .scaffold import (
    DEFAULT_STAMP, HOUSEHOLD_BUTTONS, PLATFORM_TAIL_SIZE, engine_records, platform_tail,
    touch_templates)
from .screens import Screens
from .structures import DRAW_OVERLAY, ENTER_MODE, OBJECT_ATOM, object_body


def skeleton(*, buttons: int = HOUSEHOLD_BUTTONS, stamp: bytes | None = None,
             tail: bytes | None = None, fonts=(), pictures=(), engine=(),
             devices=(), templates=None, label_font: int | None = None,
             softkey_fonts: dict | None = None, options: dict | None = None,
             system: dict | None = None, words=None, activities: dict | None = None) -> bytes:
    """Lay out a whole image from what a build has prepared.

    With nothing given it is the smallest configuration this backend can build: no
    devices, no activities and no status overlays, which is what the factory image has.
    Sections whose contents nobody has decoded are emitted with a count of zero, which is
    also what it has. Every number - object, screen, context, variable, switch table - is
    handed out in the order below, so the order is part of what makes a build the same
    each time.
    """
    tail = platform_tail() if tail is None else tail
    # Section 16 indexes fixed offsets into this table, the last at 134, so a table of
    # the wrong length would point past the end of section 15 rather than into it.
    if len(tail) != PLATFORM_TAIL_SIZE:
        raise ValueError(
            f"the platform table is {len(tail)} bytes; section 15's table is "
            f"{PLATFORM_TAIL_SIZE}")
    # Every word this image draws comes from the catalogue, in the project's language.
    words = catalogue.ENGLISH if words is None else words
    system = _worded(system, fonts, words)
    household = buttons == HOUSEHOLD_BUTTONS
    layout = Layout(scaffold.header(buttons))
    platform = _platform(layout, system, household)

    # The hub every Logitech configuration has, devices or not: Activities is the first
    # screen the image owns - what it boots into and what every OK opens - with Options
    # and Devices softkeys, and the device list behind Devices, empty or not. Options and
    # the screens carried behind it come next; the idle machine - key lights, events,
    # start-up - is built into the same namespace.
    label = label_font if label_font is not None else 0
    hub = system is not None and bool(fonts) and softkey_fonts is not None
    # The charging screens are the idle layer's, so only an image with it has them.
    charging_pictures = (charging.roles(pictures) if hub and options
                         and isinstance(pictures, dict) else [])
    model = (idle_machine.attach(options, system, len(charging_pictures)) if hub and options
             else None)
    numbers = ordinals.hub(platform=platform.count, hub=hub,
                           carried_modes=len(model["modes"]) if model else None,
                           charging=len(charging_pictures))
    carried = _carried(layout, model, numbers, platform, system, engine, household)
    _command_objects(layout, devices)
    variables = state_variables(
        devices, layout.object,
        len(engine) - 1 + (len(model["variables"]) if model else 0) if engine else None)
    running = hub and carried is not None and carried.idle and engine
    acts = list((activities or {}).get("activities") or []) if running else []
    if running and activities is not None:
        _activity_variables(variables, acts)

    # The object every owned page's fragment queues to draw status overlays 3 and 0.
    status_object = (layout.object(object_body([(3, DRAW_OVERLAY), (0, DRAW_OVERLAY)]))
                     if system and len(system["overlays"]) >= 4 else None)
    roles = set(pictures) if isinstance(pictures, dict) else set()
    frames = page_frames(pictures)
    pages = device_pages(devices, frames, roles, fonts[label] if fonts else None)
    if system:
        firmware_screens.place(layout, system, household, platform.handlers,
                               platform.navigate, roles, platform.first)
    ordinals.screens(numbers, hub=hub, system=system is not None, device_pages=pages,
                     acts=acts, device_slots=variables.slots, tutorial_pages=len(TUTORIAL),
                     off_devices=((activities or {}).get("all_off") or {}).get("off", []))

    owned = platform.owned
    screens = Screens(
        layout, fonts=fonts, words=words, roles=roles, label=label,
        softkey_fonts=softkey_fonts,
        handlers=((lambda kind: carried.screen_handlers(kind, owned)) if carried
                  else (lambda kind: owned)),
        status_object=status_object,
        current=(variables.state, len(acts)) if variables.state is not None else None)
    activity_rows = _owned_screens(
        screens, numbers, carried, variables, devices, acts, pages, charging_pictures,
        hub=hub, frames=frames,
        geometry=touch_templates() if templates is None else templates,
        all_off=(activities or {}).get("all_off"), platform=platform)
    startup, global_keys = _start_up(layout, numbers, carried, variables,
                                     usb=system is not None, hub=hub)
    return assemble.image(
        layout, devices=devices, fonts=fonts, pictures=pictures, system=system,
        carried=carried, variables=variables, engine=engine, activity_rows=activity_rows,
        global_keys=global_keys, startup=startup, tail=tail, first_platform=platform.first,
        stamp=structures.stamp(*DEFAULT_STAMP) if stamp is None else stamp)


def _worded(system, fonts, words):
    """The firmware's screens name their words; they are drawn in this image's fonts
    (platform_text.py), or left out of an image built without fonts."""
    if not system:
        return system
    used = {item["font"] for block in system["blocks"] for item in block
            if item.get("opcode") == "label"}
    fonts_ok = bool(fonts) and all(font < len(fonts) for font in used)
    return platform_text.render(system, labeller(list(fonts)) if fonts_ok else None, words)


@dataclass
class _Platform:
    first: int                    # the first of the firmware's screens' objects
    count: int                    # how many screens the firmware owns
    mode_zero: dict               # mode 0's event handlers, tag to object
    navigate: int | None          # opens the first screen the image owns
    owned: list                   # the handlers a screen the image owns gets
    handlers: dict = field(default_factory=dict)   # the idle layer's, (ordinal, tag)


def _platform(layout, system, household) -> _Platform:
    """Mode 0's handlers, then the firmware's screens' own objects, which they queue by
    index, and the object their OK buttons use to open the first screen a project owns.
    Everything a project adds is numbered after them."""
    first = HOUSEHOLD_BUTTONS if household else 0
    mode_zero = (firmware_screens.event_handlers(system["screens"][0]["header"], first)
                 if household and system else {})
    if household:
        for index in range(HOUSEHOLD_BUTTONS):
            layout.object(scaffold.mode_zero_handler(index, mode_zero))
    navigate = None
    if system:
        for atoms in system["objects"]:
            layout.object(object_body([(scaffold.platform_object(value, first), category)
                                       for value, category in atoms]))
        navigate = layout.navigation(len(system["screens"]))
    return _Platform(first=first, count=len(system["screens"]) if system else 0,
                     mode_zero=mode_zero, navigate=navigate,
                     owned=firmware_screens.owned_handlers(system, first))


def _carried(layout, model, numbers, platform, system, engine, household) -> Carried | None:
    """The carried screens, their objects numbered now so the firmware's own screens -
    whose enter, leave and redraw handlers the idle layer's flags depend on - can name
    them; mode 0's list then calls the idle layer's handlers through objects 0 to 54."""
    if not model:
        return None
    carried = Carried(model, engine_size=len(engine), system=system,
                      first_platform=platform.first, first_mode=numbers.carried,
                      exits={"options": numbers.options, "home": numbers.home,
                             "devices": numbers.first_menu,
                             **{f"charging-{index}": ordinal
                                for index, ordinal in enumerate(numbers.charging)}})
    carried.number_objects(layout)
    layout.group_base = len(model["groups"])
    if carried.idle:
        platform.handlers = carried.firmware_handlers()
        zero = {tag: operand for (ordinal, tag), (operand, category)
                in platform.handlers.items() if ordinal == 0 and category == OBJECT_ATOM}
        if zero and household:
            for index in range(HOUSEHOLD_BUTTONS):
                layout.objects[index] = scaffold.mode_zero_handler(
                    index, {**platform.mode_zero, **zero})
    return carried


def _command_objects(layout, devices):
    """Each command gets the object naming it and the wrapper a key binds to, laid out the
    way every donor lays them out: command object, then its wrapper, command by command."""
    for device in devices:
        bodies, wrappers = structures.device_objects(
            device["index"], len(device["commands"]), len(layout.objects),
            structures.IR_OBJECT_KIND_FALLBACK)
        for body in bodies:
            layout.object(body)
        for command, wrapper in zip(device["commands"], wrappers):
            command["wrapper_index"] = wrapper
            # the command object a wrapper calls, which is what a state change sends
            command["object_index"] = wrapper - 1


def _activity_variables(variables, acts):
    """`CurrentActivityState`: each activity is a value, and the one past them is nothing
    running, the value it starts at - section 0 names it, as the donors do. Then the
    Remote Assistant's state, as upstairs keeps it: 0 never shown, 1 welcomed, 2 shown
    before, 3 hidden (activity_screens.Flow._notes)."""
    variables.state = variables.add(f"CurrentActivityState_0_{len(acts) + 1}", {
        "initial": len(acts), "limit": len(acts), "padding": 0, "transitions": []})
    if acts:
        variables.assistant = variables.add("RemoteAssistant_4", {
            "initial": 0, "limit": 3, "padding": 0, "transitions": []})


def _owned_screens(screens, numbers, carried, variables, devices, acts, pages,
                   charging_pictures, *, hub, frames, geometry, all_off,
                   platform) -> dict[int, list]:
    """Every screen the image owns, in the order their objects are numbered: Activities,
    Options, the charging screens, the device menu and pages, the activities' screens, Options' second page and
    the Tutorial. Each activity's context rows, then Off's, by context."""
    layout = screens.layout
    flow = None
    if variables.state is not None:
        flow = Flow(screens, numbers, variables, devices, acts,
                    Actions(layout, devices, variables.slots), frames=frames,
                    geometry=geometry, all_off=all_off)
    owned = Hub(screens, numbers, devices, pages, frames=frames, geometry=geometry, hub=hub,
                flow=flow, options=carried is not None)
    if hub and acts:
        flow.menu_page(0)
    elif hub:
        owned.home()
    settings = None
    if carried:
        settings = Options(screens, numbers, carried, frames=frames, flow=flow,
                           assistant=variables.assistant)
        settings.carry()
    charging.place(screens, numbers, charging_pictures)
    owned.device_menu()
    owned.command_pages()
    rows = flow.activities() if hub and acts else {}
    if hub and variables.state is not None:
        rows[numbers.off_context] = flow.off()
    if numbers.options_more is not None:
        settings.page(1)
        settings.tutorial()
    if len(layout.trailers) == platform.count:
        empty_screen(screens, platform.owned)
    return rows


def _start_up(layout, numbers, carried, variables, *, usb, hub) -> tuple[int, list]:
    """The objects the image starts with, on the first screen it owns - the one every OK
    button opens - and the keys the flow owns: Activities opens the Activities menu, Off
    selects Off's context. The first start-up object, and the keys' rows."""
    startup = len(layout.objects)
    idle = None
    if carried and carried.idle:
        idle = {part: carried.atoms(steps) for part, steps in carried.idle["startup"].items()}
    for body in scaffold.startup_objects(
            numbers.platform, scaffold.USB_SCREEN if usb else None, startup, idle,
            numbers.off_context if variables.state is not None else None):
        layout.object(body)
    if not (hub and variables.state is not None):
        return startup, []
    return startup, [
        (keys.code(keys.ACTIVITIES), layout.object(object_body([(numbers.home, ENTER_MODE)]))),
        (keys.code(keys.OFF), layout.object(object_body([(0xFF00 | numbers.off_context,
                                                          0x1F)]))),
    ]


def font_from_scaffold(font: dict) -> dict:
    """Turn a loaded scaffold font into the shape a font record is written from.

    A scaffold font indexes its glyphs by the code the manifest gives them, and those run
    past the largest repertoire any donor uses, so the slot count is the highest code
    rather than a number read out of somebody's image.
    """
    glyphs = {code: item["body"] for code, item in font["glyphs"].items()}
    slots = max(glyphs, default=0)
    return {
        "height": font["height"],
        "slots": slots,
        # The wide header counts glyphs in a u16, which is the only one that reaches 95.
        "layout": font_index.WIDE_COUNT,
        "glyphs": glyphs,
        # A font record is written from bytes, but laying a label out needs each glyph's
        # width and the character it stands for. Both are carried so that a caller does
        # not have to hold the scaffold's own shape as well as this one.
        "metrics": {
            code: {"width": item["width"], "char": item["char"]}
            for code, item in font["glyphs"].items()
        },
    }


def configuration(project: dict, **options) -> bytes:
    """Build a whole configuration for a project from the scaffold (see ``build``)."""
    return build(project, **options)["image"]


def build(project: dict, *, directory=None, library=None,
          stamp_fields=None, buttons: int = HOUSEHOLD_BUTTONS) -> dict:
    """Build a whole configuration for a project from the scaffold, and nothing else.

    Fonts are emitted in the donor's attribute order, because the firmware's own screens
    name fonts by attribute; the one labelling a button is found by the role the scaffold
    records for it rather than assumed.
    """
    from ... import paths
    from . import assets

    directory = Path(paths.scaffolds("harmony-one") if directory is None else directory)
    if stamp_fields is None:
        stamp_fields = build_stamp()
    words = catalogue.for_project(project)
    manifest = assets.read_manifest(directory)
    # Each font carries only the characters it draws, as Logitech's builder did: a build
    # with every character the words could need records what each slot drew, and the
    # image is then built with exactly those, numbered from 1 in each slot.
    candidates = catalogue.characters(words) | {
        character for device in project.get("devices") or []
        for text in [device.get("label") or ""] + list(device.get("signals") or {})
        for character in text} | {
        character for activity in project.get("activities") or []
        for text in [activity.get("label") or ""] + [
            button.get("label") or "" if isinstance(button, dict) else button[0]
            for button in (activity.get("soft_buttons") or []) + [
                entry for _name, entries in activity.get("screen_groups") or []
                for entry in entries] if button is not None]
        for character in text} | set(project.get("power_off_label") or "")
    first = _configuration(project, directory, manifest, assets.load(directory, candidates),
                           stamp_fields, buttons, library, words)
    drawn = {role: font.get("drawn", set()) for role, font in first["fonts"].items()}
    built = _configuration(project, directory, manifest, assets.load(directory, drawn),
                           stamp_fields, buttons, library, words)
    # what each font attribute's codes stand for, since every image numbers its own
    built["characters"] = [{code: item["char"] for code, item in font["metrics"].items()}
                           for _role, font in sorted(built["fonts"].items())]
    return built


def _configuration(project, directory, manifest, loaded, stamp_fields, buttons, library,
                   words) -> dict:
    """One build of ``project`` with the fonts ``loaded``: the image, and the fonts as
    laid out, each knowing what it drew."""
    order = sorted(loaded["fonts"])
    button = manifest.get("font_roles", {}).get("button")
    if button not in loaded["fonts"]:
        raise ValueError("the scaffold names no font for labelling a button")
    pictures = {role: item["body"] for role, item in loaded["pictures"].items()}
    devices = lowered_devices(project, library=library)
    for device, spec in zip(devices, project.get("devices") or []):
        device["icon"] = row_icon(directory, manifest, pictures, "devices", spec.get("type"))
    planned = activity_plan.plan(project, devices)
    held_commands(project, devices, planned, library=library)
    frame = "activity/row-frame" if "activity/row-frame" in pictures else "row-frame"
    for activity in planned["activities"]:
        activity["icon"] = row_icon(directory, manifest, pictures, "activities",
                                    activity["type"], frame)
        activity["start_icon"] = start_icon(directory, manifest, pictures, activity["type"])
        for number, favourite in enumerate(activity["favourites"]):
            favourite["picture"] = favourite_picture(
                directory, manifest, pictures, favourite["image"],
                number % len(BUTTON_POSITIONS), planned["skipped"],
                f"activity {activity['label']!r} favourite {favourite['label']!r}")
    # one set of fonts for everything this build draws, so each records all it drew
    fonts = [font_from_scaffold(loaded["fonts"][role]) for role in order]
    image = skeleton(
        buttons=buttons, stamp=structures.stamp(*stamp_fields),
        tail=platform_tail(directory),
        fonts=fonts,
        label_font=order.index(button),
        softkey_fonts=dict(SOFTKEY_FONTS) if len(order) > max(SOFTKEY_FONTS.values())
        else None,
        pictures=pictures,
        engine=engine_records(*stamp_fields),
        devices=devices,
        templates=touch_templates(directory), system=load_system(directory),
        options=options_model(fonts, stamp_fields[-1], words),
        words=words, activities=planned)
    return {"image": image, "fonts": dict(zip(order, fonts)), "skipped": planned["skipped"]}


def build_stamp(now=None) -> tuple:
    """The clock a configuration starts with: when it was built, as section 3 and the
    clock variables hold it (day and month counted from 0)."""
    import datetime

    now = datetime.datetime.now() if now is None else now
    return (now.second, now.minute, now.hour, now.day - 1, now.month - 1, now.year)


def options_model(fonts: list[dict], year: int, words=None) -> dict | None:
    """The Options screens (options.py), their text set in the image's own fonts."""
    from . import options

    if not fonts or len(fonts) <= max(options.TITLE_FONT, options.COUNTER_FONT,
                                      options.LABEL_FONT, options.BACK_FONT):
        return None
    return options.build(labeller(fonts), year, words)
