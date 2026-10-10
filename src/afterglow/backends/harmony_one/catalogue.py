"""Every word a generated Harmony One draws, in English, and its translations.

Text on the remote comes from three places - the screens this backend builds, the Options
screens and the firmware's own notices and clock - and all of it is named here: a stable
key (the gettext context), the English, and a note telling a translator where it is drawn
and how much room it has, since they cannot see the screen. `locale/harmony-one.pot` is
written from this list (tools/harmony_one_pot.py) and `locale/<language>.po` answers it;
English is a catalogue like the others (`en.po`), so its wording is edited the same way,
and the text here is only what stands when a catalogue gives none.
A build asks for words through `Words`, which falls back to the English for anything a
catalogue leaves untranslated, fuzzy or missing, so a partial translation still builds.

Device and command names are the project's own and are drawn as typed.
"""
from __future__ import annotations

from pathlib import Path

from ... import po

DOMAIN = "harmony-one"
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


def _messages() -> list[po.Message]:
    out = [
        po.Message("hub.activities-title", "My Activities", "The Activities screen: " + TITLE),
        po.Message("hub.no-activities", "No activities",
                   "The Activities screen when there are none: " + MESSAGE),
        po.Message("hub.devices-title", "Devices", "The device list: " + TITLE),
        po.Message("hub.no-devices", "No devices",
                   "The device list when there are none: " + MESSAGE),
        po.Message("softkey.options", "Options", "Opens Options: " + SOFTKEY),
        po.Message("softkey.activities", "Activities", "Back to Activities: " + SOFTKEY),
        po.Message("softkey.devices", "Devices", "Opens the device list: " + SOFTKEY),
        po.Message("pages", "page", "After a screen's page total, e.g. '1/3 pages', in the "
                   "small counter font; about 40 pixels", plural="pages"),
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
            out.update(words(message.context, number=0))
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
