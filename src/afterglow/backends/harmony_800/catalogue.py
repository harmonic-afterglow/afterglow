"""Every word a generated Harmony 800 draws, in English, and its translations.

Text on the remote comes from three places - the screens this backend builds, the Options
screens and the firmware's own notices and clock - and all of it is named here: a stable
key (the gettext context), the English, and a note telling a translator where it is drawn
and how much room it has, since they cannot see the screen. `locale/harmony-800.pot` is
written from this list (tools/harmony_800_pot.py) and `locale/<language>.po` answers it;
English is a catalogue like the others (`en.po`), so its wording is edited the same way,
and the text here is only what stands when a catalogue gives none.
A build asks for words through `Words`, which falls back to the English for anything a
catalogue leaves untranslated, fuzzy or missing, so a partial translation still builds.

Device and command names are the project's own and are drawn as typed.
"""
from __future__ import annotations

from pathlib import Path

from ... import po

DOMAIN = "harmony-800"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

# The project's language setting (settings.locale) uses Logitech's codes, which the other
# remotes' builders read too; a catalogue is named by its gettext language.
LOCALES = {"enu": "en", "esp": "es", "rus": "ru", "deu": "de", "nld": "nl", "dan": "da",
           "fin": "fi", "ita": "it", "sve": "sv"}

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
NOTICES = {
    0: "The battery level is low!",
    1: "USB Connected",
    4: "Update Successful",
    5: "Upgrade Success",
    6: "Update in progress",
    7: "Learning...",
    8: "Firmware upgrade in progress",
    9: "Charging problem.\nContact customer support:\nhttp://supportinfo.\n"
       "harmonyremote.com",
    10: "Go to Website\nto update settings",
    11: "USB\nInitialization",
    12: "Bootloader\nLocked",
    13: "Real Time Clock",
    14: "IR LEDs\nand\nPhotodiode",
    15: "FLASH Memory\nID",
    16: "FLASH Memory\nErase",
    17: "FLASH Memory\nWrite",
    18: "FLASH Memory\nClear",
    19: "LCD Module\nFailed",
    20: "PLL Failure",
    21: "BootRAM\nTruncated",
    22: "Safe Mode",
    23: "Safe Mode\nRequested",
    24: "Battery Low",
    25: "Battery Fast\nCharge",
    26: "Battery Trickle Charge",
    27: "Battery Charge\nComplete",
    28: "IR Sending",
    29: "Invalid\nConfiguration",
    30: "Bootloader\nBad Image",
    31: "Bootloader\nUpgrade Failed",
    32: "Battery ADC\nNot Calibrated",
    33: "LightSense ADC\nNot Calibrated",
    34: "Revision ADC\nNot Calibrated",
    35: "Application\nTerminated",
    36: "Configuration\nCorrupted",
    37: "Missing\nLicense",
    38: "USB Connected",
    39: "Needs to be\nsetup.\nBattery\nCharging",
}

TITLE = "a screen's title, top left; about 96 pixels in the title font"
SOFTKEY = "a softkey label, bottom of the screen; about 70 pixels"
BUTTON = "a button label, centred on a 81-pixel button; may wrap to two lines"
ROW = "a row label, centred on a 164-pixel row"
MESSAGE = "a message centred on the screen; about 160 pixels a line"
TUTORIAL_NOTE = ("A Tutorial page, from the left, about 160 pixels a line; a line break "
                 "starts a new paragraph. The last paragraph says which key moves on.")


def _messages() -> list[po.Message]:
    out = [
        po.Message("hub.activities-title", "My Activities", "The Activities screen: " + TITLE),
        po.Message("hub.no-activities", "No activities",
                   "The Activities screen when there are none: " + MESSAGE),
        po.Message("hub.devices-title", "Devices", "The device list: " + TITLE),
        po.Message("hub.no-devices", "No devices",
                   "The device list when there are none: " + MESSAGE),
        po.Message("keytest.title", "Key test", "The key test screen: " + TITLE),
        po.Message("keytest.prompt", "Press any key", "The key test, before a key: " + MESSAGE),
        po.Message("keytest.pressed", "That was {code}",
                   "The key test: {code} is the code the key sent, e.g. C02B. " + MESSAGE,
                   brace_format=True),
        po.Message("keytest.again", "Press another key", "The key test, after a key: " + MESSAGE),
        po.Message("keytest.back", "Touch the screen to go back",
                   "The key test: how to leave it. " + MESSAGE),
        po.Message("lighttest.title", "Light test", "The light test screen: " + TITLE),
        po.Message("lighttest.lit", "Only LED {led} is lit",
                   "The light test: {led} is the LED's number, 0 to 6. " + MESSAGE,
                   brace_format=True),
        po.Message("lighttest.next", "Touch the screen for the next",
                   "The light test: how to go on. " + MESSAGE),
        po.Message("softkey.options", "Options", "Opens Options: " + SOFTKEY),
        po.Message("softkey.activities", "Activities", "Back to Activities: " + SOFTKEY),
        po.Message("softkey.devices", "Devices", "Opens the device list: " + SOFTKEY),
        po.Message("softkey.current-activity", "Current Activity",
                   "Back to the activity that is running, from the device list and a "
                   "device's screens: " + SOFTKEY),
        po.Message("pages", "page", "After a screen's page total, e.g. '1/3 pages', in the "
                   "small counter font; about 40 pixels", plural="pages"),
        po.Message("activity.starting", "Starting {activity}",
                   "While an activity starts, under its icon; {activity} is its name. One "
                   "line of about 164 pixels, cut to fit", brace_format=True),
        po.Message("activity.keep-pointed", "Keep the remote pointed at your system.",
                   "While an activity starts or Help is fixing it, at the bottom: "
                   + MESSAGE + "; two lines at most"),
        po.Message("activity.fixing", "Attempting to fix the problem...",
                   "Help, under the activity's name, while it re-sends what the activity "
                   "needs: " + MESSAGE),
        po.Message("activity.power-off", "Power Off",
                   "The title of Help when nothing is running, while it turns everything "
                   "off again: " + TITLE),
        po.Message("softkey.numbers", "123",
                   "On an activity's commands, opens its number keypad: " + SOFTKEY),
        po.Message("softkey.back", "Back",
                   "On the number keypad, back to the activity's commands: " + SOFTKEY),
        po.Message("softkey.commands", "Commands",
                   "On an activity's favourite channels, opens its commands: " + SOFTKEY),
        po.Message("softkey.favourites", "Favorites",
                   "On an activity's commands, opens its favourite channels: " + SOFTKEY),
        po.Message("help.keep-pointed", "Keep the remote pointed to your system.",
                   "Help, at the bottom while it re-sends: " + MESSAGE + "; two lines"),
        po.Message("help.fixed-first", "Did that fix the problem?\nIf not, the remote will "
                   "ask you questions to help correct the problem.",
                   "Help's first question, after it has re-sent everything; a line break "
                   "starts the explanation below it: " + MESSAGE),
        po.Message("help.fixed", "Did that fix the problem?",
                   "Help, after a device answered: " + MESSAGE),
        po.Message("assistant.is-on", "Is the {device} on?",
                   "Help asks about each device an activity turns on; {device} is its "
                   "name: " + MESSAGE + "; three lines at most", brace_format=True),
        po.Message("assistant.now-on", "Now is the {device} on?",
                   "Help asks again after sending its power: " + MESSAGE, brace_format=True),
        po.Message("assistant.input", "Is the {device} set to the {input} input?",
                   "Help asks about each input; {device} and {input} are names: "
                   + MESSAGE + "; three lines at most", brace_format=True),
        po.Message("assistant.now-input", "Now is the {device} set to the {input} input?",
                   "Help asks again after sending the input: " + MESSAGE, brace_format=True),
        po.Message("assistant.is-off", "Is the {device} off?",
                   "Off's Help asks about each device: " + MESSAGE, brace_format=True),
        po.Message("assistant.now-off", "Now is the {device} off?",
                   "Off's Help asks again after turning it off: " + MESSAGE,
                   brace_format=True),
        po.Message("softkey.yes", "Yes", "An answer, bottom left: " + SOFTKEY),
        po.Message("softkey.no", "No", "An answer, bottom right: " + SOFTKEY),
        po.Message("softkey.ok", "OK", "Closes a Remote Assistant note, bottom right: "
                   + SOFTKEY),
        po.Message("assistant.title", "{name}:", "The Remote Assistant's screens: the "
                   "activity's name, or Off's, as their title: " + TITLE, brace_format=True),
        po.Message("assistant.heading", "Remote Assistant:",
                   "Above each Remote Assistant note: " + MESSAGE),
        po.Message("assistant.press-help", 'If any devices are not set up correctly, press '
                   '"Help" now.', "After an activity starts: " + MESSAGE),
        po.Message("assistant.set-up", "The remote has now set up your system for this "
                   "Activity.", "After an activity starts, once Remote Assistant is back "
                   "on: " + MESSAGE),
        po.Message("assistant.hide", "Do you want to hide the Remote Assistant?",
                   "Above Yes and No: " + MESSAGE),
        po.Message("assistant.how-to-hide", "To hide the remote assistant, use the software "
                   "to update the display settings for your remote.",
                   "After choosing to hide it: " + MESSAGE),
        po.Message("assistant.welcome", "Welcome to your remote.",
                   "The first note a new remote shows, when it starts: " + MESSAGE),
        po.Message("assistant.all-off", 'Ensure all your devices are off.  If any devices '
                   'are still on, press "Help" now.', "After Off: " + MESSAGE),
        po.Message("options.assistant-off", "Turn Remote Assistant Off",
                   "An Options row while the Remote Assistant asks after each start: "
                   + ROW),
        po.Message("options.assistant-on", "Turn Remote Assistant On",
                   "An Options row while it does not: " + ROW),
        po.Message("options.tutorial", "Tutorial", "An Options row: " + ROW),
        po.Message("tutorial.title", "Tutorial", "The Tutorial's screens: " + TITLE),
        po.Message("softkey.exit", "Exit", "Leaves the Tutorial: " + SOFTKEY),
    ]
    tutorial = TUTORIAL_NOTE
    out += [po.Message(f"tutorial.{number}", text, tutorial) for number, text in (
        (1, "Welcome to your Harmony 800 touch-screen remote. Touch the screen to learn "
            "more."),
        (2, "Use the arrow buttons on the sides of this screen to move between pages.\n"
            "Press the right arrow now."),
        (3, "The Harmony remote uses Activities to give you simple one-touch control of "
            "your entertainment system.\nPress the Activities button now."),
        (4, "Activities are what you actually do with your entertainment system, like "
            "watch TV or listen to music.\nTouch Watch TV now."),
        (5, "Selecting the Watch TV Activity turns on the devices you use to watch TV.\n"
            "Press the right arrow to continue."),
        (6, "Look on the screen for functions you can't find elsewhere on the remote.\n"
            "Press the right arrow to continue."),
        (7, "To select another Activity, simply press the Activities button.\nPress the "
            "right arrow to continue."),
        (8, "Use the Help button if your Activity doesn't start properly.\nPress Help "
            "now."),
        (9, "Help asks you questions to get your Activity back on track. Press the right "
            "arrow to continue."),
        (10, "To turn off your entertainment system, press the Power button.\nPress the "
             "Power button to continue."),
        (11, "It's that easy!\nYou can now enjoy your entertainment system with "
             "one-touch Activity control.\nPress Exit now."))]
    out += [
        po.Message("tutorial.watch-tv", "Watch TV", "On the activity row the Tutorial "
                   "pictures; about 100 pixels"),
        po.Message("tutorial.display", "Display", "On a button the Tutorial pictures: "
                   + BUTTON),
        po.Message("tutorial.aspect", "Aspect", "On a button the Tutorial pictures: "
                   + BUTTON),
        po.Message("tutorial.is-tv-on", "Is the TV on?", "The question the Tutorial "
                   "pictures Help asking: " + MESSAGE),
        po.Message("tutorial.yes", "Yes", "On a button the Tutorial pictures: " + BUTTON),
        po.Message("tutorial.no", "No", "On a button the Tutorial pictures: " + BUTTON),
        po.Message("options.title", "Options", "The Options screen: " + TITLE),

        po.Message("options.date-and-time", "Date and Time", "An Options row: " + ROW),
        po.Message("options.screen-sensitivity", "Screen Sensitivity",
                   "An Options row, and the title of its screen: " + ROW),
        po.Message("options.sounds-off", "Turn Screen Sounds Off",
                   "An Options row while touch sounds are on: " + ROW),
        po.Message("options.sounds-on", "Turn Screen Sounds On",
                   "An Options row while touch sounds are off: " + ROW),
        po.Message("options.back", "Back", "Steps back a screen: " + SOFTKEY),
        po.Message("options.ok", "OK", "Closes a confirmation, bottom right; about 40 pixels"),
        po.Message("options.year", "Year", "Date and Time, choosing the year: " + TITLE),
        po.Message("options.month", "Month", "Date and Time, choosing the month: " + TITLE),
        po.Message("options.day", "Day", "Date and Time, choosing the day: " + TITLE),
        po.Message("options.hour", "Hour", "Date and Time, choosing the hour: " + TITLE),
        po.Message("options.minute", "Minute", "Date and Time, choosing the minute: " + TITLE),
        po.Message("options.time-of-day", "Time of Day",
                   "Date and Time, morning or afternoon: " + TITLE),
        po.Message("options.am", "AM", "Morning: " + BUTTON),
        po.Message("options.pm", "PM", "Afternoon: " + BUTTON),
    ]
    out += [po.Message(f"options.month.{n}", name, f"Month {n}: " + BUTTON)
            for n, name in enumerate(MONTHS, start=1)]
    for key, name in (("very-low", "Very Low"), ("low", "Low"), ("medium", "Medium"),
                      ("high", "High"), ("very-high", "Very High")):
        out.append(po.Message(f"options.sensitivity.{key}", name,
                              "A touch sensitivity level: " + BUTTON))
    out.append(po.Message("options.sensitivity-set", "Screen sensitivity is set to",
                          "Confirms the level chosen; the level follows on the next line: "
                          + MESSAGE))
    out.append(po.Message("system.ok", "OK", "Closes a firmware notice, bottom right; "
                          "about 40 pixels"))
    out.append(po.Message("system.message", "System Message: {number}",
                          "Title of a firmware diagnostic screen: " + TITLE,
                          brace_format=True))
    out += [po.Message(f"system.screen.{n}", text,
                       f"Firmware screen {n}, one line per line break, centred; about 160 "
                       "pixels a line")
            for n, text in sorted(NOTICES.items())]
    out += [po.Message(f"clock.weekday.{n}", name,
                       "The status bar's clock, before the time; about 20 pixels in the "
                       "11-pixel font")
            for n, name in enumerate(WEEKDAYS)]
    return out


MESSAGES = _messages()
_ENGLISH = {message.context: message for message in MESSAGES}


class Words:
    """The words of one language, English where it has none."""

    def __init__(self, catalogue: po.Catalogue | None = None, language: str = "en"):
        self.catalogue = catalogue
        self.language = language

    def __call__(self, key: str, **values) -> str:
        message = _ENGLISH[key]
        found = self.catalogue.get(key, message.text) if self.catalogue else None
        text = found if found is not None else message.text
        return text.format(**values) if message.brace_format else text

    def fixed(self, key: str) -> str:
        """The words of a message without what is filled into it: the characters it
        draws whatever the values are."""
        message = _ENGLISH[key]
        found = self.catalogue.get(key, message.text) if self.catalogue else None
        text = found if found is not None else message.text
        if not message.brace_format:
            return text
        import string
        return "".join(literal for literal, *_field in string.Formatter().parse(text))

    def plural(self, key: str, n: int) -> str:
        message = _ENGLISH[key]
        found = self.catalogue.get(key, message.text, n) if self.catalogue else None
        if found is not None:
            return found
        return message.text if n == 1 else (message.plural or message.text)


ENGLISH = Words()            # the catalogue's own text; a build reads en.po (load)


def load(language: str | None, directory: Path | None = None) -> Words:
    """The words for ``language`` - a gettext code (``fi``) or the project's Logitech
    code (``fin``) - from its catalogue; English when there is none."""
    language = LOCALES.get(language, language) if language else "en"
    folder = LOCALE_DIR if directory is None else Path(directory)
    path = folder / f"{language}.po"
    if not path.is_file():
        language, path = "en", folder / "en.po"
    if not path.is_file():
        return Words(language="en")
    try:
        return Words(po.parse(path.read_text("utf-8")), language)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def characters(words: Words) -> set[str]:
    """Every character ``words`` could draw: each message in that language, its plurals,
    the digits and punctuation the clock and counters use, and printable ASCII."""
    from .faces import REPERTOIRE

    out = set(REPERTOIRE)
    for message in MESSAGES:
        if message.plural is not None:
            for n in (1, 2, 5):
                out.update(words.plural(message.context, n))
        elif message.brace_format:
            out.update(words.fixed(message.context))
        else:
            out.update(words(message.context))
    return out


def for_project(project: dict) -> Words:
    """The words a project's build draws: its language, or English (en.po)."""
    return load((project.get("settings") or {}).get("locale"))


def template() -> str:
    return po.template(MESSAGES, DOMAIN)


def english_catalogue(existing: str | None = None) -> str:
    """`en.po`: every message, its English kept from ``existing`` where that has one, the
    catalogue's text for anything new; messages no longer drawn are dropped."""
    previous = po.parse(existing) if existing else po.Catalogue()

    def answers(message):
        forms = previous.messages.get((message.context, message.text))
        if forms and all(forms):
            return forms if message.plural is None else (forms + forms)[:2]
        return [message.text] if message.plural is None else [message.text, message.plural]
    return po.template(MESSAGES, DOMAIN, answers, "en")
