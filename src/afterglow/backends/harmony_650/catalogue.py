"""Every word a generated arch-14 remote (600, 650, 665, 700) draws, and its translations.

Text on the remote comes from two places - the screens this backend builds and the
firmware's own notices and clock - and all of it is named here: a stable key (the gettext
context), the English, and a note telling a translator where it is drawn and how much room
it has, since they cannot see the screen. Where Logitech's remote breaks a text into fixed
lines, its English keeps them as line breaks. `locale/arch14.pot` is written from this
list (tools/arch14_pot.py) and `locale/<language>.po` answers it;
English is a catalogue like the others (`en.po`), so its wording is edited the same way,
and the text here is only what stands when a catalogue gives none.
A build asks for words through `Words`, which falls back to the English for anything a
catalogue leaves untranslated, fuzzy or missing, so a partial translation still builds.

Device and command names are the project's own and are drawn as typed.
"""
from __future__ import annotations

from pathlib import Path

from ... import po

DOMAIN = "arch14"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

# The project's language setting (settings.locale) uses Logitech's codes, which the other
# remotes' builders read too; a catalogue is named by its gettext language.
LOCALES = {"enu": "en", "esp": "es", "rus": "ru", "deu": "de", "nld": "nl", "dan": "da",
           "fin": "fi", "ita": "it", "sve": "sv"}

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
# The words on the firmware's own screens, by name. Which screen shows which is the
# scaffold's (platform/system-screens.json, "notices"): a 650 and a 700 number them
# differently, and only a 700 asks to be charged.
NOTICES = {
    'add-an-activity-on-this-button': 'Use the Harmony\nsetup software to\nadd an Activity on\nthis button.',
    'add-activities': 'Use the Harmony\nsetup software to\nadd Activities.',
    'usb-connected': 'USB Connected',
    'low-battery': 'Low Battery',
    'please-charge-your-remote': 'Please charge your\nremote',
    'insert-batteries': 'Insert batteries',
    'unable-to-charge-batteries': 'Unable to charge\nbatteries',
    'update-successful': 'Update Successful',
    'upgrade-successful': 'Upgrade\nSuccessful',
    'ready-to-learn': 'Ready to learn\ncommand from\nother remote.',
    'command-received': 'Command\nReceived',
    'terminate-entry': 'Terminate Entry',
    'go-to-website': 'Go to Website\nto update settings',
    'usb-initialization': 'USB\nInitialization',
    'bootloader-locked': 'Bootloader\nLocked',
    'real-time-clock': 'Real Time Clock',
    'ir-leds-and-photodiode': 'IR LEDs\nand\nPhotodiode',
    'flash-memory-id': 'FLASH Memory\nID',
    'flash-memory-erase': 'FLASH Memory\nErase',
    'flash-memory-write': 'FLASH Memory\nWrite',
    'flash-memory-clear': 'FLASH Memory\nClear',
    'lcd-module-failed': 'LCD Module\nFailed',
    'pll-failure': 'PLL Failure',
    'bootram-truncated': 'BootRAM\nTruncated',
    'safe-mode': 'Safe Mode',
    'safe-mode-requested': 'Safe Mode\nRequested',
    'battery-low': 'Battery Low',
    'battery-fast-charge': 'Battery Fast\nCharge',
    'battery-trickle-charge': 'Battery\nTrickle Charge',
    'battery-charge-complete': 'Battery Charge\nComplete',
    'ir-sending': 'IR Sending',
    'invalid-configuration': 'Invalid\nConfiguration',
    'bootloader-bad-image': 'Bootloader\nBad Image',
    'bootloader-upgrade-failed': 'Bootloader\nUpgrade Failed',
    'battery-adc-not-calibrated': 'Battery ADC\nNot Calibrated',
    'lightsense-adc-not-calibrated': 'LightSense ADC\nNot Calibrated',
    'revision-adc-not-calibrated': 'Revision ADC\nNot Calibrated',
    'application-terminated': 'Application\nTerminated',
    'configuration-corrupted': 'Configuration\nCorrupted',
    'missing-license': 'Missing\nLicense',
    'usb-connected-capitals': 'USB CONNECTED',
    'needs-setup-battery-charging': 'Needs to be\nsetup.\nBattery\nCharging',
}

TITLE = "a screen's title, top left; about 100 pixels in the title font"
SOFTKEY = "the softkey's word, centred at the bottom of the screen; about 60 pixels"
CORNER = ("a button's label, beside one of the four keys at the screen's corners; about "
          "50 pixels, two lines at most")
MESSAGE = "a message centred on the screen; about 120 pixels a line"
ANSWER = "over one of the two bottom keys, in the answer font; about 40 pixels"
ROW = "a row of a menu, beside its two keys; about 120 pixels"
FIXED_LINES = ("Each line break is a line of the screen, as Logitech's remote breaks it; a "
               "line too wide is wrapped again between its words")
TOUR_WIDTH = "about 124 pixels a line, wrapped between its words"
TOUR_NOTE = "A page of the welcome tour after a write, from the left; " + TOUR_WIDTH
TOUR_PROMPT = "Below a tour page's words, what to press to go on; " + TOUR_WIDTH


def _messages() -> list[po.Message]:
    out = [
        po.Message("menu.title", "Activities", "The Activities menu: " + TITLE),
        po.Message("devices.title", "Devices", "The Devices list: " + TITLE),
        po.Message("softkey.devices", "Devices",
                   "Opens the Devices list, from the Activities menu and an activity's "
                   "pages: " + SOFTKEY),
        po.Message("softkey.activities", "Activities",
                   "Back to the Activities menu, from the Devices list: " + SOFTKEY),
        po.Message("softkey.activity", "Activity",
                   "Back to the running activity, from its Devices list: " + SOFTKEY),
        po.Message("softkey.back", "Back", "Back a screen: " + SOFTKEY),
        po.Message("softkey.exit", "Exit",
                   "Leaves Delay Fixing, the Remote Assistant's note or the tour: " + SOFTKEY),
        po.Message("softkey.done", "Done", "Keeps the delay chosen: " + SOFTKEY),
        po.Message("activity.favourites", "Favorite Channels",
                   "Opens an activity's favourite channels, first on its page: " + CORNER),
        po.Message("favourites.commands", "Commands",
                   "Back to an activity's buttons, first among its favourites: " + CORNER),
        po.Message("favourites.unnamed", "Favorite {number}",
                   "A favourite channel given no name; {number} counts them from 1: "
                   + CORNER, brace_format=True),
        po.Message("activity.starting", "Starting {activity}",
                   "While an activity starts, at the top; {activity} is its name: "
                   + MESSAGE + "; cut to fit", brace_format=True),
        po.Message("off.turning-off", "Turning system off",
                   "While All Off turns everything off, at the top: " + MESSAGE),
        po.Message("notice.keep-pointed", "Please keep the\nremote pointed at\nyour system",
                   "Below 'Starting' and 'Turning system off': " + MESSAGE + ". "
                   + FIXED_LINES),
        po.Message("help.attempting", "Attempting to fix\nthe problem...",
                   "Help, at the top, while it sends the activity's power and inputs again: "
                   + MESSAGE + ". " + FIXED_LINES),
        po.Message("help.keep-pointed", "Please keep your\nremote pointed at the\nsystem",
                   "Help, at the bottom, below 'Attempting to fix': " + MESSAGE + ". "
                   + FIXED_LINES),
        po.Message("help.fixed", "Did that fix the problem?",
                   "Help, above No and Yes: " + MESSAGE + "; four lines at most"),
        po.Message("help.is-on", "Is the {device} on?",
                   "Help asks about each device an activity turns on; {device} is its "
                   "name: " + MESSAGE + "; four lines at most", brace_format=True),
        po.Message("help.now-on", "Now is the {device} on?",
                   "Help asks again after sending its power: " + MESSAGE, brace_format=True),
        po.Message("help.is-off", "Is the {device} off?",
                   "All Off's Help asks about each device: " + MESSAGE, brace_format=True),
        po.Message("help.now-off", "Now is the {device} off?",
                   "All Off's Help asks again after turning it off: " + MESSAGE,
                   brace_format=True),
        po.Message("help.input", "Is the {device} set to the {input} input?",
                   "Help asks about each input; {device} and {input} are names: "
                   + MESSAGE + "; four lines at most", brace_format=True),
        po.Message("help.now-input", "Now is the {device} set to the {input} input?",
                   "Help asks again after sending the input: " + MESSAGE, brace_format=True),
        po.Message("answer.no", "No", "An answer, over the bottom left key: " + ANSWER),
        po.Message("answer.yes", "Yes", "An answer, over the bottom right key: " + ANSWER),
        po.Message("answer.ok", "OK", "Closes a note, over the bottom right key: " + ANSWER),
        po.Message("softkey.exit-help", "Exit Help", "Leaves Help: " + SOFTKEY),
        po.Message("assistant.title", "Remote Assistant",
                   "The note after an activity starts: " + TITLE),
        po.Message("assistant.note", 'If any devices are not setup correctly, press "Help" '
                   "now.", "The Remote Assistant's note, below its title: " + MESSAGE
                   + "; four lines at most"),
        po.Message("assistant.turn-off", "Turn off\nAssistant",
                   "Over the bottom left key, turns the Remote Assistant off: " + ANSWER
                   + ". " + FIXED_LINES),
        po.Message("delays.title", "Delay Fixing",
                   "Help held down, the screen it opens on: " + TITLE),
        po.Message("delays.warning", "You are in an\nadvanced delay\nfixing mode. Do you\n"
                   "want to continue?", "Delay Fixing, above No and Yes: " + MESSAGE + ". "
                   + FIXED_LINES),
        po.Message("delays.select-title", "Select device",
                   "Delay Fixing's list of devices: " + TITLE),
        po.Message("delays.set-default", "Set to default",
                   "A device's delay menu, puts its delays back as they were: " + ROW),
        po.Message("delays.change", "Change Delay", "A device's delay menu: " + ROW),
        po.Message("delays.power-on", "Power On Delay",
                   "Choosing which delay to change: " + ROW),
        po.Message("delays.inter-device", "Inter-device Delay",
                   "Choosing which delay to change: " + ROW),
        po.Message("delays.power-on-title", "Power On delay",
                   "Changing a device's power-on delay: " + TITLE),
        po.Message("delays.inter-device-title", "Inter-device delay",
                   "Changing the delay before a device's next: " + TITLE),
        po.Message("delays.set-power-on", "Set the Power On delay for {device}.",
                   "Changing a device's power-on delay, from the left; {device} is its "
                   "name; about 120 pixels a line, three lines at most", brace_format=True),
        po.Message("delays.set-inter-device", "Set the Inter-device delay for {device}.",
                   "Changing the delay before a device's next, from the left; {device} is "
                   "its name; about 120 pixels a line, three lines at most",
                   brace_format=True),
        po.Message("delays.seconds", "( {seconds} sec )",
                   "The delay being changed, centred above - and +; {seconds} is a number "
                   "such as 4.5; about 120 pixels in the answer font", brace_format=True),
        po.Message("delays.reset", "Delay settings for {device} are now set to default",
                   "After 'Set to default', from the left; {device} is the device's name; "
                   "about 120 pixels a line", brace_format=True),
    ]
    tour = (
        ("Welcome to your {model} remote.", "Press the right arrow to learn more."),
        ("Use the arrow buttons below the screen to move between pages.",
         "Press the right arrow now."),
        ("The activity buttons above give you simple one-touch control.",
         "Press the right arrow to continue."),
        ("The Watch TV button turns on the devices you use for watching TV.",
         "Press Watch TV now."),
        ("Buttons beside the screen select commands you can't find elsewhere on the "
         "remote.", "Try one now."),
        ("The center button below lets you select the item above it.",
         "Press the center button now."),
        ("Use the help button if your activity doesn't start properly.", "Press Help now."),
        ("The More Activities button lists all your activities on the screen.",
         "Press More Activities now."),
        ("The All Off button turns off all your devices.", "Press All Off now."),
        ("You can now enjoy your entertainment system with one-touch activity control.",
         None),
    )
    for number, (text, prompt) in enumerate(tour, start=1):
        out.append(po.Message(
            f"tour.{number}", text, TOUR_NOTE + (
                "; {model} is the remote's name, such as Harmony 650" if number == 1
                else ""), brace_format=number == 1))
        if prompt:
            out.append(po.Message(f"tour.{number}.prompt", prompt, TOUR_PROMPT))
    out.append(po.Message("tour.center-button", "Center Button",
                          "The tour's page about the center button: " + SOFTKEY
                          + "; about 100 pixels here"))
    out.append(po.Message("system.ok", "OK", "Closes a firmware notice, bottom right; "
                          "about 40 pixels"))
    out.append(po.Message("system.exit", "Exit", "Closes a firmware notice, on the softkey "
                          "at the bottom of the screen; about 60 pixels"))
    out.append(po.Message("system.message", "System Message: {number}",
                          "Title of a firmware diagnostic screen: " + TITLE,
                          brace_format=True))
    out += [po.Message(f"notice.{name}", text,
                       "A firmware notice, one line per line break, centred; about 120 "
                       "pixels a line")
            for name, text in NOTICES.items()]
    out += [po.Message(f"clock.weekday.{n}", name,
                       "The status bar's clock, before the time; about 20 pixels in the "
                       "11-pixel font")
            for n, name in enumerate(WEEKDAYS)]
    return out


MESSAGES = _messages()
_ENGLISH = {message.context: message for message in MESSAGES}


def every(key: str) -> set[str]:
    """``key``'s words in English and in every language there is a catalogue for: what
    an import looks for, whatever language the image was built in."""
    out = {_ENGLISH[key].text}
    for path in sorted(LOCALE_DIR.glob("*.po")):
        try:
            found = po.parse(path.read_text("utf-8")).get(key, _ENGLISH[key].text)
        except ValueError:
            continue
        if found:
            out.add(found)
    return out


def has(key: str) -> bool:
    """Whether the catalogue has a message ``key`` - a tour page with a line to press."""
    return key in _ENGLISH


class Words:
    """The words of one language, English where it has none."""

    def __init__(self, catalogue: po.Catalogue | None = None, language: str = "en"):
        self.catalogue = catalogue
        self.language = language

    def __call__(self, key: str, **values) -> str:
        message = _ENGLISH[key]
        found = self.catalogue.get(key, message.text) if self.catalogue else None
        text = found if found is not None else message.text
        if not message.brace_format:
            return text
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError) as exc:
            # a translation's misspelt {field}: the English, and a word in the log naming
            # the message, rather than a build stopped with a bare KeyError
            import logging
            logging.getLogger("afterglow").warning(
                "%s.po, message %s: %r does not fit (%s); English used", self.language,
                key, text, exc)
            return message.text.format(**values)

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
