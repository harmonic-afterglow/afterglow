# Translating the Harmony 5xx

Every word a generated Harmony 510, 515, 520, 525, 550, 555 or Harmony for Xbox 360 draws
is in `harmony-5xx.pot`. That covers the remote's own screens (the Activities menu, the
Devices list, the Remote Assistant's notes, Help's questions, Starting and Stopping
Activity, the welcome, the firmware's notices) and the page counter. Device, activity
and command names are the project's own and are drawn as typed.

To translate:

1. Copy `harmony-5xx.pot` to `<language>.po` (or start from `en.po`, which holds the
   English), named by the gettext language code:
   `fr.po`, `de.po`, `es.po`, `it.po`, `nl.po` and so on.
2. Fill in the `msgstr` lines with Poedit, Weblate or any text editor, and set the
   `Language` and `Plural-Forms` headers for your language.
3. Put the file here. The language then appears in the app's Remote Settings, named in
   its own language (the project's `settings.locale`); no other file needs changing.

The screen is 96 pixels wide and 64 high, so shorter is better. Each entry's `#.` comment
says where the text is drawn and roughly how many pixels it has. Where Logitech's remote
breaks a text into fixed lines, the English keeps them as line breaks (`\n`). A
translation may use more or fewer. A line too wide is wrapped again between its words,
a text with more lines than there is room for moves up and is then cut, and a title too
wide is cut with "..". A word that does not fit what is left of a line fills it up to its
last hyphen that fits, as Logitech's remote breaks "BD-Panasonic". Put a soft hyphen
(U+00AD) where a long word may also break: it is drawn as "-" only if the word breaks
there. Leave `{device}`, `{input}`, `{name}`, `{number}` and the like as
they are: reading a configuration back finds an input's name in Help's question.

The page counter ("1 OF 3") is drawn 8 pixels high with no room above the capitals: use
capitals and digits there, without accents.

Anything left empty, or marked fuzzy, stays English, so a partial translation still
builds. English is `en.po`. The English a 5xx draws is Logitech's own, so a word reworded
there changes the English remote too. After adding or changing a message in
`catalogue.py`, bring the template and `en.po` in step with
`python3 tools/harmony_5xx_pot.py`.

The remote's typeface, Galmuri, draws Latin with accents, Greek and Cyrillic; a build
carries every character its words use.
