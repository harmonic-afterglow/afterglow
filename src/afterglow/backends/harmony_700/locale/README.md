# Translating the Harmony 700

Every word a generated Harmony 700 draws - its own screens (the Activities menu, the
Devices list, Help and Delay Fixing, the Remote Assistant's note, the welcome tour) and
the firmware's notices and clock - is in `harmony-700.pot`. Device, activity and command
names are the project's own and are drawn as typed; the remote's name in the tour
("Harmony 700") is not translated.

To translate:

1. Copy `harmony-700.pot` to `<language>.po` (or start from `en.po`, which holds the
   English), named by the gettext language code:
   `fi.po`, `de.po`, `es.po`, `ru.po`, `nl.po`, `da.po`, `it.po`, `sv.po`.
2. Fill in the `msgstr` lines with Poedit, Weblate or any text editor, and set the
   `Language` and `Plural-Forms` headers for your language.
3. Add the language to the remote's profile (`interface.languages`), and choose it in
   the app's Remote Settings (the project's `settings.locale`).

Each entry's `#.` comment says where the text is drawn and roughly how many pixels it
has; the screen is 128 pixels wide, so shorter is better. Where Logitech's remote breaks
a text into fixed lines, the English keeps them as line breaks (`\n`): a translation may
use more or fewer, and a line too wide is wrapped again between its words. Leave
`{device}`, `{activity}`, `{number}` and the like as they are.

Anything left empty, or marked fuzzy, stays English, so a partial translation still
builds. English is `en.po`: edit it to reword the English remote. After adding or
changing a message in `catalogue.py`, bring the template and `en.po` in step with
`python3 tools/arch14_pot.py`.

The remote's typeface, Galmuri, draws Latin with accents, Greek, Cyrillic, Japanese and
Korean; a build carries every character its words use.
