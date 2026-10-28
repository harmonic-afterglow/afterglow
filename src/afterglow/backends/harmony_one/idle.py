"""The idle machine a generated Harmony One runs: keypad lights, their timers, the events.

The firmware lights nothing by itself - the factory image has no light instruction and its
keys stay dark - so every Logitech configuration carries a small machine that lights the
keypad when a key is pressed, darkens it when a timer runs out, lights the zones the shown
screen uses, and answers the events the firmware posts: USB in and out, charging, the side
strips - and, while the remote charges, shows the charging screens in a ring. docs/harmony_one/gspm.md, "The idle layer", is its specification, read from
upstairs by running its handlers under every combination of the platform's variables.

This module builds that machine from the specification rather than carrying upstairs' own.
It is written as a model in the carried-screens form - objects, timers and variables named
by their index in the model, the platform's own instructions as ``{"platform": ...}`` - and
``attach`` appends it to the Options model, so a build numbers both in one namespace and
the carried screens' ``{"zones": ...}`` references find the zones built here.
"""
from __future__ import annotations

import copy

# Opcodes and bands, as the Harmony 800's interpreter reads them (gspm.md).
OBJECT = 0x7F
ENTER_MODE = 0x7E
REGISTER = 0x1F          # band FB loads the byte register, EB/EA start/stop a timer
SETTING = 0x3F           # band C0 a light channel, F0-FF the firmware's settings (gspm.md)
MODE_STACK = 0x07        # FFFD push the current mode, FFFC pop it, FFFF a silent write
TEST = 0x71              # compare a variable with the byte register
BEEP = 0x75
PAGE = 0x0F              # FFA0 / FFA1 previous / next page

LOAD = 0xFB00
ANY_STATE = 0xFFFE       # a transition's "from" that matches whatever the value was
START_TIMER, STOP_TIMER = 0xEB, 0xEA
EQUAL, NOT_EQUAL, GREATER, AT_MOST = 0x00, 0x01, 0x03, 0x04
INVERT = 0x80            # the test drops the next instruction when it holds
PUSH_MODE, POP_MODE, SILENT = 0xFFFD, 0xFFFC, 0xFFFF
STATUS = 0xFFFB          # stop every running timer (the firmware runs at most four)
CHARGE = 0xE8            # `1F E8xx`: the context under 0xFC on the key stack (gspm.md)
PREVIOUS_PAGE, NEXT_PAGE = 0xFFA0, 0xFFA1

# Light channels (gspm.md): the screen backlight, the keypad, and eight zones.
SCREEN = 0x11
KEYPAD = (0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x10)
ZONES = 8
SCREEN_LEVEL, KEY_LEVEL = 6, 1
# Setting 1: arm the motion sensor, so the next movement posts MOTION (0x17) once - what
# upstairs writes after darkening everything, so picking the remote up wakes it - or
# disarm it, as the donors do when the remote starts charging.
LIGHTS_OUT = (0xF101, SETTING)
MOTION_OFF = (0xF100, SETTING)

# The platform's variables are the firmware's (gspm.md): battery level 0-7, USB, HOLD and
# CHARGING as upstairs tests them, and AWAKE - the infrared engine's state, 0 when idle.
BATTERY, HOLD, CHARGING, USB, AWAKE = 9, 13, 15, 16, 17
LOW_BATTERY = 2

# Timers: the keypad goes dark when OFF runs out; POLL re-arms OFF while AWAKE says so.
OFF_DURATION, POLL_DURATION = 10, 2
# Charging, as every donor has it: the charging screens start this long after the remote
# starts charging, the battery stays up for BATTERY_SHOWN and each photo after it for
# PHOTO_SHOWN; a charging problem's notice stays lit for PROBLEM_SHOWN.
SHOW_DELAY, BATTERY_SHOWN, PHOTO_SHOWN, PROBLEM_SHOWN = 5, 5, 1, 20
# The ring goes round once and stops, and the screen goes dark DARK_DELAY later, as every
# donor's does - when platform variable 10 is above 1. The firmware copies it from its
# charge state machine (RAM 0xF10), which holds 2 to 7 while it looks after a charge.
# Without it the backlight stays lit for as long as the remote sits on the cradle.
CHARGE_STATE, DARK_DELAY = 10, 1

# What each kind of screen lights, as every donor's screens of that kind do (gspm.md):
# the arrows light only where there are pages to turn, a softkey's bar only where the
# screen has that softkey. Screens of no kind - an activity starting - light nothing.
SCREEN_ZONES = {
    "activities": (1, 3, 5, 7),
    "options": (1, 3, 5),
    "devices": (0, 2, 4),
    "commands": (4, 6),
    "commands-paged": (0, 2, 4, 6),
    "activity": (7,),
    "activity-paged": (1, 3, 7),
    # an activity's page with a left softkey too: Commands on its favourites, Favorites
    # on its commands
    "activity-both": (5, 7),
    "activity-both-paged": (1, 3, 5, 7),
    # Help's questions: Yes and No are the two softkeys, and their bars lit nothing - a
    # tester's Logitech remote lights them. As an activity's screen with both softkeys.
    "question": (5, 7),
    "tutorial": (1, 3, 7),
}
# The firmware's own screens that light a zone or mark themselves shown.
LOW_BATTERY_SCREEN, USB_SCREEN, SCREEN_NINE = 0, 1, 9
ENTER, LEAVE = 0x06, 0x07

MOTION = 0x17            # the event the firmware posts when the remote is picked up
# The firmware's charging events (gspm.md, "Where the events come from"): external power
# removed and connected - lifted off the cradle and set on it - and a charger fault.
CHARGING_STOPPED, CHARGING_STARTED, CHARGING_PROBLEM = 0x1E, 0x1F, 0x23
# The battery level went up: on the cradle, as it charges.
BATTERY_UP = 0x0F
REDRAW = 0x2D
# The battery events each charge context answers, as all three donors' contexts 0, 5, 6.
CHARGE_EVENTS = {"normal": (0x1A, 0x1B, 0x1C, 0x1D), "usb": (0x1E,), "low": (0x18, 0x19)}

BEEP_KEY = 0x4664
BEEP_SHORT = 0x01FF
BEEP_PAGE = 0x0FCA


def light(channel: int, level: int, flag: int = 0) -> list:
    return [0xC000 | channel << 4 | level << 1 | flag, SETTING]


class _Model:
    """Objects, timers and variables, numbered as they are made."""

    def __init__(self):
        self.objects: list[list] = []
        self.timers: list[dict] = []
        self.variables: list[dict] = []

    def object(self, atoms: list[list]) -> list:
        self.objects.append(atoms)
        return [{"object": len(self.objects) - 1}, OBJECT]

    def reserve(self) -> int:
        self.objects.append([])
        return len(self.objects) - 1

    def timer(self, duration: int) -> int:
        self.timers.append({"flags": 1, "duration": duration, "action": None})
        return len(self.timers) - 1

    def flag(self) -> dict:
        """A new 0/1 variable, as the model names one: ``{"variable": index}``."""
        self.variables.append({"initial": 0, "limit": 1, "transitions": []})
        return {"variable": len(self.variables) - 1}

    def when(self, variable: dict, value: int, action: list):
        """Run ``action`` whenever ``variable`` becomes ``value``."""
        self.variables[variable["variable"]]["transitions"].append(
            {"flags": 0, "from": ANY_STATE, "to": value, "action": action})


def _timer(band: int, timer: int) -> list:
    return [{"timer": timer, "band": band}, REGISTER]


def _test(kind: int, variable) -> list:
    """Compare ``variable`` - a platform variable's number or a model flag - with the
    byte register; ``kind`` is the test in the high byte's low nibble."""
    return [{"test": kind, "variable": variable}, TEST]


def _write(variable, value: int) -> list:
    return [value, {"write": variable}]


def build(system: dict | None, sounds: dict | None = None, charging: int = 0) -> dict:
    """The machine as a model, with its entry points under ``"idle"``.

    ``system`` is the platform model (system-screens.json): the firmware's own screens,
    whose enter and leave handlers the machine extends. ``sounds`` is the Options model's
    Screen Sounds switch, whose flag start-up clears as upstairs does. ``charging`` is how
    many charging screens the image has - the battery, then its photos - which it names
    ``{"exit": "charging-<n>"}``; none, and the remote shows nothing while it charges.
    """
    machine = _Machine(charging)
    events, key_rows = machine.events(), machine.key_rows()
    screens = (system or {}).get("screens", ())
    handlers = machine.platform_handlers(screens)
    kinds = {**machine.screen_kinds(screens), **machine.charging_kinds()}
    m = machine.m
    return {
        "objects": m.objects,
        "timers": m.timers,
        "variables": m.variables,
        "zones": machine.zones,
        "idle": {
            "events": {f"{code:#04x}": value for code, value in sorted(events.items())},
            "key_light": machine.wake,
            "key_rows": {f"{code:#04x}": value for code, value in sorted(key_rows.items())},
            "startup": machine.startup(sounds),
            # The charge contexts' rows, every one passed on down the stack: the normal
            # one and the low battery's choose again on the firmware's battery events, the
            # USB one stops the timers when charging finishes (0x1E).
            "charge": {
                "normal": {f"{code:#04x}": machine.charge for code in CHARGE_EVENTS["normal"]},
                "usb": {f"{code:#04x}": [STATUS, MODE_STACK] for code in CHARGE_EVENTS["usb"]},
                "low": {f"{code:#04x}": machine.charge for code in CHARGE_EVENTS["low"]},
            },
            "handlers": handlers,
            "screens": kinds,
        },
    }


class _Machine:
    """The idle machine's parts, built into one model in the order they are made: the
    keypad lights and their timers, then what the charging events choose, then the
    events, the key rows, and the screens' handlers."""

    def __init__(self, charging: int = 0):
        m = self.m = _Model()
        self.zone_flags = [m.flag() for _ in range(ZONES)]
        self.usb_shown = m.flag()
        self.off_timer, self.poll_timer = m.timer(OFF_DURATION), m.timer(POLL_DURATION)
        self._zone_objects: dict[tuple, list] = {}
        self._lights()
        self._charge()
        self.charging = charging
        if charging:
            self._charging()

    def guarded(self, byte: int, test: list, step: list) -> list:
        """Run ``step`` when ``test`` holds against ``byte``, in the donors' shape: the
        byte is loaded, then an object holds the test and the one step it guards."""
        return self.m.object([[LOAD | byte, REGISTER], self.m.object([test, step])])

    def _lights(self):
        m, guarded, off_timer = self.m, self.guarded, self.off_timer
        # Zones: on lights a zone and records it, off darkens it and clears the record.
        self.zone_on = [m.object([light(z, KEY_LEVEL), _write(self.zone_flags[z], 1)])
                        for z in range(ZONES)]
        self.zone_off = [m.object([light(z, 0), _write(self.zone_flags[z], 0)])
                         for z in range(ZONES)]
        restore = m.object([guarded(1, _test(EQUAL, self.zone_flags[z]), light(z, KEY_LEVEL))
                            for z in range(ZONES)])
        # The off timer darkens everything; the zone records stay, so the next wake
        # restores them.
        lights_out = m.object(
            [_timer(STOP_TIMER, off_timer)] + [light(c, 0) for c in KEYPAD]
            + [light(z, 0) for z in range(ZONES)] + [light(SCREEN, 0), list(LIGHTS_OUT)])
        m.timers[off_timer]["action"] = self.lights_out = lights_out
        # Arm: start the off timer when AWAKE is set, and poll again either way.
        arm_slot = m.reserve()
        arm = [{"object": arm_slot}, OBJECT]
        m.objects[arm_slot] = [
            _timer(STOP_TIMER, off_timer),
            guarded(0, _test(INVERT | EQUAL, AWAKE),
                    m.object([light(SCREEN, SCREEN_LEVEL, 1), _timer(START_TIMER, off_timer)])),
            _timer(START_TIMER, self.poll_timer)]
        m.timers[self.poll_timer]["action"] = arm
        self.wake = m.object([_timer(STOP_TIMER, off_timer), light(SCREEN, SCREEN_LEVEL)]
                             + [light(c, KEY_LEVEL) for c in KEYPAD] + [restore, arm])

    def _charge(self):
        m, guarded = self.m, self.guarded

        # Which charge context sits under 0xFC on the key stack, chosen on every charging
        # event as every donor chooses it: the USB one, the normal one, or the low
        # battery's.
        def charge_context(name):
            return [{"charge": name, "band": CHARGE}, REGISTER]
        self.charge = m.object([
            guarded(1, _test(INVERT | EQUAL, HOLD), charge_context("usb")),
            guarded(1, _test(INVERT | EQUAL, USB), charge_context("usb")),
            guarded(LOW_BATTERY, _test(INVERT | AT_MOST, BATTERY), charge_context("normal")),
            charge_context("low")])
        # The setting byte upstairs writes while HOLD is set: F201 off USB - unless
        # CHARGING is clear, which drops just that step - and F200 on it.
        self.usb_setting = guarded(1, _test(EQUAL, HOLD), m.object([[LOAD, REGISTER], m.object([
            _test(INVERT | EQUAL, CHARGING),
            guarded(0, _test(EQUAL, USB), [0xF201, SETTING]),
            guarded(1, _test(EQUAL, USB), [0xF200, SETTING])])]))
        self.low_battery_wake = guarded(LOW_BATTERY, _test(AT_MOST, BATTERY), self.wake)

    def _charging(self):
        """The charging screens in a ring, each entering the next when its timer runs out,
        and the timer that opens the ring after charging starts - over what was shown,
        which charging stopping goes back to while the ring is up."""
        m, count = self.m, self.charging
        self.charging_shown = m.flag()
        self.frame_timers = [m.timer(BATTERY_SHOWN if index == 0 else PHOTO_SHOWN)
                             for index in range(count)]
        for index, timer in enumerate(self.frame_timers):
            m.timers[timer]["action"] = [{"exit": f"charging-{(index + 1) % count}"},
                                         ENTER_MODE]
        self.show_timer = m.timer(SHOW_DELAY)
        m.timers[self.show_timer]["action"] = m.object(
            [[PUSH_MODE, MODE_STACK], [{"exit": "charging-0"}, ENTER_MODE]])
        # A lap: the battery clears the flag and the last picture sets it. Setting it
        # stops the ring where it is and, a moment later, darkens the keypad, the zones
        # and the screen - fading it - and arms the motion sensor only when HOLD is
        # clear, as the donors do; lifting the remote off the cradle wakes it either way.
        dark_timer = m.timer(DARK_DELAY)
        m.timers[dark_timer]["action"] = m.object(
            [_timer(STOP_TIMER, self.off_timer)] + [light(c, 0) for c in KEYPAD]
            + [light(z, 0) for z in range(ZONES)]
            + [light(SCREEN, 3, 1), light(SCREEN, 0, 1),
               self.guarded(0, _test(EQUAL, HOLD), list(LIGHTS_OUT))])
        self.lap = m.flag()
        m.when(self.lap, 1, self.guarded(1, _test(GREATER, CHARGE_STATE), m.object(
            [[STATUS, MODE_STACK], _timer(START_TIMER, dark_timer)])))
        self.problem_timer = m.timer(PROBLEM_SHOWN)
        m.timers[self.problem_timer]["action"] = self.lights_out

    def events(self) -> dict[int, list]:
        m, guarded, charge, wake = self.m, self.guarded, self.charge, self.wake
        return {
            # USB in: wake and show the USB screen over whatever was shown.
            0x26: m.object([[BEEP_KEY, BEEP], charge, wake, [PUSH_MODE, MODE_STACK],
                            [USB_SCREEN, ENTER_MODE], [STATUS, MODE_STACK]]),
            # USB out: back to what was shown, if the USB screen is still the one shown.
            0x27: m.object([[BEEP_KEY, BEEP], [BEEP_SHORT, BEEP], [BEEP_SHORT, BEEP],
                            [BEEP_SHORT, BEEP], [BEEP_KEY, BEEP], charge, wake,
                            self.usb_setting,
                            guarded(0, _test(NOT_EQUAL, self.usb_shown), [POP_MODE, MODE_STACK]),
                            guarded(1, _test(EQUAL, BATTERY), [0xFFF6, MODE_STACK]),
                            self.low_battery_wake]),
            0x10: m.object([self.low_battery_wake, self.usb_setting]),
            0x19: [0xFFF6, MODE_STACK],
            0x2D: [0xFFFA, MODE_STACK],
            0x25: [0, 0],
            0xAE: m.object([[BEEP_PAGE, BEEP], [PREVIOUS_PAGE, PAGE]]),
            0xAF: m.object([[BEEP_PAGE, BEEP], [NEXT_PAGE, PAGE]]),
            **self._charging_events(),
        }

    def _charging_events(self) -> dict[int, list]:
        """Charging starts: wake, stop the motion sensor waking it on the cradle, and open
        the charging screens a moment later. Charging stops: back to what was shown, if
        the charging screens are still up, as unplugging USB does. The battery level rising
        goes back to what was shown and opens them again. A charging problem shows the
        firmware's notice."""
        if not self.charging:
            return {}
        m, guarded, charge, wake = self.m, self.guarded, self.charge, self.wake
        return {
            CHARGING_STARTED: m.object([
                list(MOTION_OFF), [BEEP_KEY, BEEP], charge, wake, self.usb_setting,
                guarded(1, _test(EQUAL, HOLD), _timer(START_TIMER, self.show_timer))]),
            CHARGING_STOPPED: m.object([
                [BEEP_KEY, BEEP], [BEEP_SHORT, BEEP], [BEEP_SHORT, BEEP], [BEEP_SHORT, BEEP],
                [BEEP_KEY, BEEP], _timer(STOP_TIMER, self.show_timer), charge,
                guarded(0, _test(NOT_EQUAL, self.charging_shown), [POP_MODE, MODE_STACK]),
                wake, guarded(1, _test(EQUAL, BATTERY), [0xFFF6, MODE_STACK]),
                self.low_battery_wake]),
            # The battery level rose, as it does on the cradle: back to what was shown,
            # and the charging screens again a moment later, as every donor does.
            BATTERY_UP: m.object([
                [BEEP_KEY, BEEP], _timer(STOP_TIMER, self.show_timer),
                guarded(0, _test(NOT_EQUAL, self.charging_shown), [POP_MODE, MODE_STACK]),
                wake, guarded(1, _test(EQUAL, HOLD), _timer(START_TIMER, self.show_timer))]),
            # A charging problem: the firmware's notice (screen 9), lit for a while.
            CHARGING_PROBLEM: m.object([[BEEP_KEY, BEEP], wake, [SCREEN_NINE, ENTER_MODE],
                                        [STATUS, MODE_STACK],
                                        _timer(START_TIMER, self.problem_timer)]),
        }

    def key_rows(self) -> dict[int, list]:
        """Two codes below the keys run the key light too, as both donors have them:
        0x17, which wakes the remote when it is picked up (gspm.md), with its own firmware
        steps first and lights-out's setting byte after, and 0x30, a plain wake."""
        m = self.m
        return {
            MOTION: m.object([m.object([[LOAD | 1, REGISTER], [0xFFE1, PAGE],
                                        [LOAD, REGISTER], [0xFFE1, PAGE],
                                        [0xFFE3, PAGE], [0xFFE3, PAGE]]),
                              self.wake, list(LIGHTS_OUT)]),
            0x30: self.wake,
        }

    def zones(self, chosen, on: bool) -> list:
        """An object lighting or darkening the zones ``chosen``, made once for each."""
        key = (tuple(sorted(chosen)), on)
        if key not in self._zone_objects:
            self._zone_objects[key] = self.m.object(
                [(self.zone_on if on else self.zone_off)[z] for z in key[0]])
        return self._zone_objects[key]

    def platform_handlers(self, screens) -> dict[str, list]:
        """The firmware's own screens: the low-battery screen and screen 9 light zone 7,
        the USB screen marks itself shown so unplugging knows whether to go back."""
        zones = self.zones
        extra = {
            (LOW_BATTERY_SCREEN, ENTER): [zones((7,), True)],
            (LOW_BATTERY_SCREEN, LEAVE): [zones((7,), False)],
            (SCREEN_NINE, ENTER): [zones((7,), True)],
            (SCREEN_NINE, LEAVE): [zones((7,), False)],
            (USB_SCREEN, ENTER): [[SILENT, MODE_STACK], _write(self.usb_shown, 1)],
            (USB_SCREEN, LEAVE): [[SILENT, MODE_STACK], _write(self.usb_shown, 0)],
        }
        handlers = {}
        for (ordinal, tag), steps in extra.items():
            if ordinal >= len(screens):
                continue
            own = [[{"platform": operand}, category]
                   for key, operand, category in screens[ordinal]["header"] if key == tag]
            handlers[f"{ordinal}:{tag:#04x}"] = self.m.object(own + steps)
        return handlers

    def screen_kinds(self, screens) -> dict[str, dict]:
        """A screen the build owns: the platform's own enter and leave, then its zones."""
        own = {}
        for screen in screens:
            rows = {key: (operand, category) for key, operand, category in screen["header"]}
            if ENTER in rows and LEAVE in rows and rows[ENTER][1] != OBJECT \
                    and rows[LEAVE][1] != OBJECT:
                own = rows
                break
        return {kind: {f"{tag:#04x}": self.m.object(
                    ([[{"platform": own[tag][0]}, own[tag][1]]] if tag in own else [])
                    + [self.zones(chosen, tag == ENTER)])
                       for tag in (ENTER, LEAVE)}
                for kind, chosen in SCREEN_ZONES.items()}

    def charging_kinds(self) -> dict[str, dict]:
        """Each charging screen's enter and leave: entering stops every timer - the
        keypad's too, so the screen stays lit while the remote charges - darkens the keypad
        and starts the screen's own timer; leaving stops it. A redraw draws nothing over
        the picture."""
        if not self.charging:
            return {}
        m = self.m
        usb = [{"charge": "usb", "band": CHARGE}, REGISTER]
        dark = [light(channel, 0) for channel in KEYPAD]
        last = len(self.frame_timers) - 1
        return {f"charging-{index}": {
                    f"{ENTER:#04x}": m.object(
                        [[STATUS, MODE_STACK], light(SCREEN, SCREEN_LEVEL)] + dark
                        + [usb, _write(self.charging_shown, 1), _timer(START_TIMER, timer)]
                        # a lap starts at the battery - a key on the cradle starts one
                        # too - and ends at the last picture, after its timer starts
                        + ([_write(self.lap, 0)] if index == 0 else [])
                        + ([_write(self.lap, 1)] if index == last else [])),
                    f"{LEAVE:#04x}": m.object(
                        [_timer(STOP_TIMER, timer), _write(self.charging_shown, 0),
                         self.charge]),
                    f"{REDRAW:#04x}": [0, 0]}
                for index, timer in enumerate(self.frame_timers)}

    def startup(self, sounds) -> dict:
        """What start-up resets, then sets up: the charge context, the zone records, the
        lights, and the Screen Sounds flag with its setting."""
        m = self.m
        resets = [[SILENT, MODE_STACK], _write(self.usb_shown, 0)]
        if self.charging:
            resets.append(_write(self.charging_shown, 0))
        setup = [self.charge, m.object([_write(flag, 0) for flag in self.zone_flags]),
                 self.wake]
        if sounds is not None:
            setup.append(m.object([_write(sounds["variable"], 0), [0xF301, SETTING]]))
        return {"resets": resets, "setup": setup}


def _shift(value, objects: int, timers: int, variables: int):
    """``value`` with its model indices moved past the Options model's own. A platform
    instruction keeps the platform model's indices; a platform variable is a bare number."""
    if isinstance(value, list):
        return [_shift(item, objects, timers, variables) for item in value]
    if not isinstance(value, dict) or "platform" in value:
        return value
    if set(value) == {"object"}:
        return {"object": value["object"] + objects}
    if set(value) == {"variable"}:
        return {"variable": value["variable"] + variables}
    if set(value) == {"timer", "band"}:
        return {"timer": value["timer"] + timers, "band": value["band"]}
    return {key: _shift(item, objects, timers, variables) for key, item in value.items()}


def attach(options: dict, system: dict | None, charging: int = 0) -> dict:
    """The Options model with the idle machine appended in its namespace, and each of
    its ``{"zones": ...}`` references made a call of the machine's zone object."""
    model = copy.deepcopy(options)
    sounds = model.get("sounds", {}).get("switch")
    machine = build(system, sounds, charging)
    shift = (len(model["objects"]), len(model["timers"]), len(model["variables"]))

    def zones(value):
        if isinstance(value, list):
            if (len(value) == 2 and isinstance(value[0], dict) and "zones" in value[0]
                    and value[1] == OBJECT):
                return _shift(machine["zones"](value[0]["zones"], value[0]["on"]), *shift)
            return [zones(item) for item in value]
        if isinstance(value, dict):
            return {key: zones(item) for key, item in value.items()}
        return value
    for key in ("modes", "blocks", "objects", "timers", "variables"):
        model[key] = zones(model[key])

    # Resolving a reference may have built a zone object, so the machine is added after.
    model["objects"] += _shift(machine["objects"], *shift)
    model["timers"] += _shift(machine["timers"], *shift)
    model["variables"] += _shift(machine["variables"], *shift)
    model["idle"] = _shift(machine["idle"], *shift)
    return model
