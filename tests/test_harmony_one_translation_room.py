"""A translation longer than the English takes more lines, where the screen has room for
them, instead of being cut with "..": a German One cut five of its words (a firmware
notice, Screen Sensitivity's confirmation, two Remote Assistant notes and the Tutorial's
pictured question)."""
from __future__ import annotations

import pytest

from afterglow.backends.harmony_one import catalogue, font_index, generate, ui_index

from test_harmony_one_help_manual import PROJECT

pytestmark = pytest.mark.slow

LONG = {
    "system.screen.10": "Afterglow verwenden\nzum aktualisieren der Einstellungen",
    "options.sensitivity-set": "LCD-Empfindlichkeit ist eingestellt auf",
    "assistant.how-to-hide": "Um den Fernbedienungs-Assistenten auszublenden, ändern Sie "
                             "mit der Software die Anzeigeeinstellungen Ihrer Fernbedienung.",
    "assistant.all-off": "Stellen Sie sicher, dass alle Geräte ausgeschaltet sind. Falls "
                         "noch Geräte eingeschaltet sind, drücken Sie jetzt die Taste Help.",
    "tutorial.is-tv-on": "Ist der Fernseher eingeschaltet?",
}


def _drawn(built):
    """Every line of text the image draws, read with its own character tables."""
    image, chars = built["image"], built["characters"]
    fonts = font_index.fonts(image)
    out = []
    for screen in ui_index.screen_slots(image):
        for slot in screen["slots"]:
            stack, seen, attribute = [slot["program_offset"]], set(), None
            while stack:
                at = stack.pop()
                if at in seen:
                    continue
                seen.add(at)
                for item in ui_index.drawing_program(image, at)["instructions"]:
                    if item["opcode"] == "attribute":
                        attribute = item["value"]
                    elif item["opcode"] == "call":
                        stack.append(item["target"])
                    elif item["opcode"] in ("text", "inline_text"):
                        codes = bytes.fromhex(item["glyphs"])
                        width = sum(fonts[attribute]["glyphs"][code]["width"] for code in codes)
                        out.append(("".join(chars[attribute][code] for code in codes),
                                    item["x"], width, item["y"]))
    return out


def test_a_long_translation_wraps_rather_than_being_cut(tmp_path, monkeypatch):
    def entry(key, text):
        english = catalogue.ENGLISH(key).replace("\n", "\\n")
        return [f'msgctxt "{key}"', f'msgid "{english}"',
                'msgstr "' + text.replace("\n", "\\n") + '"', ""]
    lines = ['msgid ""', 'msgstr ""', '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"', ""]
    for key, text in LONG.items():
        lines += entry(key, text)
    (tmp_path / "de.po").write_text("\n".join(lines), "utf-8")
    monkeypatch.setattr(catalogue, "LOCALE_DIR", tmp_path)
    drawn = _drawn(generate.build(dict(PROJECT, settings={"locale": "deu"})))
    words = " ".join(text for text, _x, _width, _y in drawn)
    for text in LONG.values():
        for word in text.replace("\n", " ").split():
            assert word in words, f"{word!r} of {text!r} is not drawn"
    assert not [text for text, _x, _width, _y in drawn if text.endswith("..")
                and not text.endswith("...")]
    assert all(x + width <= 176 for _text, x, width, _y in drawn)

    # and a note longer than the English is centred where the English is, not hung
    # lower from the same top
    def middle(lines, first, last):
        """The middle of one note: its line starting ``first`` to the next ending ``last``."""
        start = next(at for at, line in enumerate(lines) if line[0].startswith(first))
        end = next(at for at in range(start, len(lines)) if lines[at][0].endswith(last))
        return (lines[start][3] + lines[end][3]) / 2
    english = _drawn(generate.build(PROJECT))
    assert abs(middle(drawn, "Um den", "Fernbedienung.")
               - middle(english, "To hide", "remote.")) <= 6
