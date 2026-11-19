"""Every word a generated Harmony 5xx draws, and its translations.

Text on a 5xx comes from two places: the platform's own screens, which the scaffold keeps
line by line as Logitech drew them (platform/screens.json), and the pages a build draws
for the household - its Help questions, "Starting", the Sound and Picture titles and the
page counter. All of it is named here: a stable key (the gettext context), the English,
and a note telling a translator where it is drawn and how much room it has, since they
cannot see the screen. A platform text Logitech broke into lines keeps them as line
breaks, and a build finds it on the platform's pages by those lines.

`locale/harmony-5xx.pot` is written from this list (tools/harmony_5xx_pot.py) and
`locale/<language>.po` answers it. English is a catalogue like the others (`en.po`); a
build draws the platform's own English where a catalogue gives the English back, so an
English build is Logitech's to the pixel. A build asks for words through `Words`, which
falls back to the English for anything a catalogue leaves untranslated, fuzzy or missing,
so a partial translation still builds.

Device, activity and command names are the project's own and are drawn as typed.
"""
from __future__ import annotations

import logging
import string
from pathlib import Path

from ... import po

DOMAIN = "harmony-5xx"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

# The project's language setting (settings.locale) uses Logitech's codes, which the other
# remotes' builders read too; a catalogue is named by its gettext language.
LOCALES = {"enu": "en", "fra": "fr", "deu": "de", "esp": "es", "ita": "it", "nld": "nl",
           "dan": "da", "fin": "fi", "sve": "sv", "rus": "ru"}

WIDTH = "the screen is 96 pixels wide"
NOTICE = ("A firmware notice, centred, one line per line break; about 90 pixels a line ("
          + WIDTH + ")")
NOTE = ("A note of the Remote Assistant, centred, one line per line break; about 90 "
        "pixels a line (" + WIDTH + ")")
LINES = ("Each line break is a line of the screen, as Logitech's remote breaks it; a line "
         "too wide is wrapped again between its words, and a text with more lines than the "
         "screen has room for is cut")
TITLE = "a screen's title, top left; about 90 pixels in the title font, cut with '..'"
ANSWER = "centred over its key at the bottom of the screen; about 30 pixels"


def _then(where: str, what: str) -> str:
    """A note on when a text is shown, then what it is."""
    return f"{where}: {what[0].lower()}{what[1:]}"


QUESTION = ("Help's question, centred; three lines of about 90 pixels, wrapped between "
            "words and cut")

# The platform's own texts, by key: the English as the platform's lines have it, line
# breaks between them, and where it is shown. A build finds each on the platform's pages
# by its English lines (Image.translate_platform).
PLATFORM = (
    ("notice.terminate-entry", "Terminate Entry", NOTICE),
    ("notice.usb-connected", "USB CONNECTED", _then("While the remote is on USB", NOTICE)),
    ("notice.upgrade-success", "Upgrade Success", NOTICE),
    ("notice.error-startup-u0", "U0 : Error Startup\nEntry", NOTICE),
    ("notice.error-startup-u2", "U2 : Error Startup\nEntry", NOTICE),
    ("notice.update-successful", "Update Successful", NOTICE),
    ("notice.update-in-progress", "Update in progress", NOTICE),
    ("notice.learning", "Learning...", _then("While the remote learns a command", NOTICE)),
    ("notice.learning-complete", "Learning complete", NOTICE),
    ("notice.firmware-upgrade", "Firmware upgrade\nin progress", NOTICE),
    ("notice.go-to-website", "Go to Website\nto update settings", NOTICE),
    ("notice.usb-initialization", "USB\nInitialization", NOTICE),
    ("notice.bootloader-locked", "Bootloader\nLocked", NOTICE),
    ("notice.real-time-clock", "Real Time Clock", NOTICE),
    ("notice.ir-leds-and-photodiode", "IR LEDs\nand\nPhotodiode", NOTICE),
    ("notice.flash-memory-id", "FLASH Memory\nID", NOTICE),
    ("notice.flash-memory-erase", "FLASH Memory\nErase", NOTICE),
    ("notice.flash-memory-write", "FLASH Memory\nWrite", NOTICE),
    ("notice.flash-memory-clear", "FLASH Memory\nClear", NOTICE),
    ("notice.lcd-module-failed", "LCD Module\nFailed", NOTICE),
    ("notice.pll-failure", "PLL Failure", NOTICE),
    ("notice.bootram-truncated", "BootRAM\nTruncated", NOTICE),
    ("notice.safe-mode", "Safe Mode", NOTICE),
    ("notice.safe-mode-requested", "Safe Mode\nRequested", NOTICE),
    ("notice.battery-low", "Battery Low", NOTICE),
    ("notice.battery-fast-charge", "Battery Fast\nCharge", NOTICE),
    # Logitech's own text, its backslash drawn as one
    ("notice.battery-trickle-charge", "Battery\nTrickle\\Charge", NOTICE),
    ("notice.battery-charge-complete", "Battery Charge\nComplete", NOTICE),
    ("notice.ir-sending", "IR Sending", NOTICE),
    ("notice.invalid-configuration", "Invalid\nConfiguration", NOTICE),
    ("notice.bootloader-bad-image", "Bootloader\nBad Image", NOTICE),
    ("notice.bootloader-upgrade-failed", "Bootloader\nUpgrade Failed", NOTICE),
    ("notice.battery-adc", "Battery ADC\nNot Calibrated", NOTICE),
    ("notice.lightsense-adc", "LightSense ADC\nNot Calibrated", NOTICE),
    ("notice.revision-adc", "Revision ADC\nNot Calibrated", NOTICE),
    ("notice.application-terminated", "Application\nTerminated", NOTICE),
    ("notice.configuration-corrupted", "Configuration\nCorrupted", NOTICE),
    ("notice.missing-license", "Missing\nLicense", NOTICE),
    ("notice.needs-setup", "Needs to be\nsetup.\nBattery\nCharging", NOTICE),
    ("notice.replace-batteries", "Replace the\nbatteries",
     _then("Before an activity starts or All Off ends, when the batteries are low", NOTICE)),
    ("assistant.how-to-hide", "Remote\nAssistant:\nTo permanently\nhide the Remote\n"
     "Assistant, use",
     _then("The first page of the note after 'Yes' to hiding the Remote Assistant", NOTE)),
    ("assistant.how-to-hide-2", "the software to\nupdate your\npreferences.",
     "The note's second page, from the left; about 90 pixels a line"),
    ("assistant.hide", "Do you want to\nhide the Remote\nAssistant?",
     _then("Above Yes and No", NOTE)),
    ("assistant.off-check", "All your devices\nshould be off.  If\nany devices are\n"
     "still on, press\n\"Help\" now.", _then("After All Off", NOTE)),
    ("assistant.start-check", "Ensure all your\ndevices are off. If\nany devices are\n"
     "still on, press\n\"Help\" now.", _then("The Remote Assistant's note", NOTE)),
    ("devices.title", "Devices", "The Devices list: " + TITLE),
    ("menu.title", "Choose an activity", "The Activities menu: " + TITLE),
    ("notice.nothing-to-do", "Nothing to do",
     _then("Help with nothing to fix, above OK", NOTE)),
    ("off.stopping", "Stopping Activity",
     "While All Off turns everything off, above 'Please keep the remote pointed'; "
     "about 90 pixels"),
    ("notice.keep-pointed", "Please keep the\nremote pointed at\nyour system.",
     _then("Below 'Stopping Activity' and below 'Starting' and the activity's name", NOTE)),
    ("welcome", "Welcome to your\nremote.",
     _then("The welcome after a write, at the top", NOTE)),
    ("answer.yes", "Yes", "An answer, bottom left: " + ANSWER),
    ("answer.no", "No", "An answer, bottom right: " + ANSWER),
    ("answer.ok", "OK", "Closes a note, bottom left: " + ANSWER),
)

# The answers the platform draws over the two keys under the screen
ANSWERS = ("answer.yes", "answer.no", "answer.ok")


def _messages() -> list[po.Message]:
    out = [po.Message(key, text, comment + ("" if "\n" not in text else ". " + LINES))
           for key, text, comment in PLATFORM]
    out += [
        po.Message("activity.starting", "Starting",
                   "While an activity starts, on a line of its own above the activity's "
                   "name; about 90 pixels"),
        po.Message("help.fixed", "Did that fix the problem?", "Help, above Yes and No; "
                   + QUESTION),
        po.Message("help.is-on", "Is the {device} on?",
                   "Help asks about each device an activity turns on; {device} is its "
                   "name; " + QUESTION, brace_format=True),
        po.Message("help.now-on", "Now is the {device} on?",
                   "Help asks again after sending its power; " + QUESTION,
                   brace_format=True),
        po.Message("help.is-off", "Is the {device} off?",
                   "All Off's Help asks about each device; " + QUESTION, brace_format=True),
        po.Message("help.now-off", "Now is the {device} off?",
                   "All Off's Help asks again after turning it off; " + QUESTION,
                   brace_format=True),
        po.Message("help.is-set", "Is the {device} set to the {input} input?",
                   "Help asks about each input; {device} and {input} are names; " + QUESTION
                   + ". An import reads the input's name back from it, so keep both "
                   "fields", brace_format=True),
        po.Message("help.now-set", "Now is the {device} set to the {input} input?",
                   "Help asks again after sending the input; " + QUESTION,
                   brace_format=True),
        po.Message("help.is-state", "Is the {device} {state} set to {value}?",
                   "Help asks about another of a device's states, such as its screen; "
                   "{device}, {state} and {value} are names (\"Is the TV Screen set to "
                   "HDMI2?\"); " + QUESTION + ". An import reads the value back from it, "
                   "so keep the fields", brace_format=True),
        po.Message("help.now-state", "Now is the {device} {state} set to {value}?",
                   "Help asks again after sending the state; " + QUESTION,
                   brace_format=True),
        po.Message("layout.sound", "{name} (Sound)",
                   "The title of an activity's or a device's Sound page; {name} is its "
                   "name: " + TITLE, brace_format=True),
        po.Message("layout.picture", "{name} (Picture)",
                   "The title of an activity's or a device's Picture page; {name} is its "
                   "name: " + TITLE, brace_format=True),
        po.Message("page.counter", "{number} OF {count}",
                   "Under a page of buttons when there is more than one, such as 1 OF 3; "
                   "drawn 8 pixels high with no room above the capitals, so capitals and "
                   "digits only, no accents; about 40 pixels", brace_format=True),
    ]
    return out


MESSAGES = _messages()
_ENGLISH = {message.context: message for message in MESSAGES}
# a platform text's key by its English lines
PLATFORM_KEYS = {text: key for key, text, _comment in PLATFORM}


class Words:
    """The words of one language, English where it has none."""

    def __init__(self, catalogue: po.Catalogue | None = None, language: str = "en"):
        self.catalogue = catalogue
        self.language = language

    def text(self, key: str) -> str:
        message = _ENGLISH[key]
        found = self.catalogue.get(key, message.text) if self.catalogue else None
        return found if found is not None else message.text

    def __call__(self, key: str, **values) -> str:
        message = _ENGLISH[key]
        text = self.text(key)
        if not message.brace_format:
            return text
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError) as exc:
            # a translation's misspelt {field}: the English, and a word in the log naming
            # the message, rather than a build stopped with a bare KeyError
            logging.getLogger("afterglow").warning(
                "%s.po, message %s: %r does not fit (%s); English used", self.language,
                key, text, exc)
            return message.text.format(**values)

    def fixed(self, key: str) -> str:
        """The words of a message without what is filled into it."""
        text = self.text(key)
        if not _ENGLISH[key].brace_format:
            return text
        return "".join(literal for literal, *_field in string.Formatter().parse(text))

    def english(self, key: str) -> bool:
        """Whether ``key`` is drawn in the catalogue's own English."""
        return self.text(key) == _ENGLISH[key].text


ENGLISH = Words()            # the catalogue's own text; a build reads en.po (load)


def english(key: str) -> str:
    return _ENGLISH[key].text


def translations() -> list[str]:
    """Every language a catalogue here translates into, by its gettext code; English is
    the base every build falls back to, so it is not one of them."""
    return sorted(path.stem for path in LOCALE_DIR.glob("*.po") if path.stem != "en")


def load(language: str | None, directory: Path | None = None) -> Words:
    """The words for ``language`` - a gettext code (``fr``) or the project's Logitech
    code (``fra``) - from its catalogue; English when there is none."""
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


_LOADED: dict = {}


def languages() -> dict[str, Words]:
    """Every translation's words, by its gettext code - read again when a file changes."""
    files = tuple((path.name, path.stat().st_mtime_ns)
                  for path in sorted(LOCALE_DIR.glob("*.po")) if path.stem != "en")
    key = (str(LOCALE_DIR), files)
    if key not in _LOADED:
        _LOADED.clear()
        _LOADED[key] = {code: load(code) for code in translations()}
    return _LOADED[key]


def every(key: str) -> list[str]:
    """``key``'s words in English and in every language there is a catalogue for, the
    English first: what an import looks for, whatever language the image was built in."""
    out = [english(key)]
    for words in languages().values():
        found = words.text(key)
        if found not in out:
            out.append(found)
    return out


def layout_titles(name: str) -> list[str]:
    """The titles a Sound or Picture page of ``name`` has, in English and every
    translation."""
    out = []
    for words in (ENGLISH, *languages().values()):
        for key in ("layout.sound", "layout.picture"):
            title = words(key, name=name)
            if title not in out:
                out.append(title)
    return out


def characters() -> set[str]:
    """Every character a translation here draws: what reading an image back must know."""
    out = set()
    for words in languages().values():
        for message in MESSAGES:
            out.update(words.fixed(message.context))
    if "\u00ad" in out:           # a soft hyphen is drawn as "-" where a word breaks
        out.add("-")
    return out - {"\n", "\u00ad"}


def counter_characters() -> set[str]:
    """The characters the page counter draws besides its digits, in every language."""
    return {character for words in (ENGLISH, *languages().values())
            for character in words.fixed("page.counter")}


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
            return forms
        return [message.text]
    return po.template(MESSAGES, DOMAIN, answers, "en")
