# Translating the Harmony 800

Every word a generated Harmony 800 draws - its own screens, Options, the firmware's
notices and the clock's weekday names - is in `harmony-800.pot`. Device and command
names are the project's own and are drawn as typed.

To translate:

1. Copy `harmony-800.pot` to `<language>.po` (or start from `en.po`, which holds the
   English), named by the gettext language code:
   `fi.po`, `de.po`, `es.po`, `ru.po`, `nl.po`, `da.po`, `it.po`, `sv.po`.
2. Fill in the `msgstr` lines with Poedit, Weblate or any text editor, and set the
   `Language` and `Plural-Forms` headers for your language.
3. Choose the language in the app's Remote Settings (the project's `settings.locale`).

Each entry's `#.` comment says where the text is drawn and roughly how many pixels it
has; the remote's screen is 240 pixels wide, and a title is cut, a button label wraps
once and is then cut, so shorter is better. A firmware notice may use more or fewer lines
than the English (line breaks are `\n`). Leave `{number}` as it is.

Anything left empty, or marked fuzzy, stays English, so a partial translation still
builds. English is `en.po`: edit it to reword the English remote. After adding or
changing a message in `catalogue.py`, bring the template and `en.po` in step with
`python3 tools/harmony_800_pot.py`.

The remote's typeface, Galmuri, draws Latin with accents, Greek, Cyrillic, Japanese and
Korean. One font slot holds at most 127 different characters in one image.
